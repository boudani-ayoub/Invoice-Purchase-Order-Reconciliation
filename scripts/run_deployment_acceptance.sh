#!/usr/bin/env bash
set -Eeuo pipefail

repository="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime="$(mktemp -d /tmp/reconcile-deployment.XXXXXXXX)"
http_port="${PRODUCTION_E2E_HTTP_PORT:-8080}"
https_port="${PRODUCTION_E2E_HTTPS_PORT:-8443}"
origin="https://localhost:$https_port"
api_pid=""
web_pid=""
nginx_started=false

cleanup() {
  set +e
  if [[ "$nginx_started" == true ]]; then
    nginx -s quit -c "$runtime/nginx.conf" -p "$runtime"
  fi
  [[ -n "$web_pid" ]] && kill -TERM "$web_pid" 2>/dev/null
  [[ -n "$api_pid" ]] && kill -TERM "$api_pid" 2>/dev/null
  [[ -n "$web_pid" ]] && wait "$web_pid" 2>/dev/null
  [[ -n "$api_pid" ]] && wait "$api_pid" 2>/dev/null
  if [[ "$runtime" == /tmp/reconcile-deployment.* && -d "$runtime" ]]; then
    rm -rf -- "$runtime"
  fi
}
trap cleanup EXIT

for command in nginx openssl curl ss npm python; do
  command -v "$command" >/dev/null || {
    echo "Required deployment acceptance command is unavailable: $command" >&2
    exit 1
  }
done
[[ -n "${TEST_DATABASE_ADMIN_URL:-}" ]] || {
  echo "TEST_DATABASE_ADMIN_URL must identify a disposable PostgreSQL server" >&2
  exit 1
}

mkdir -p "$runtime/client-body" "$runtime/logs" "$runtime/releases/rejected"
ln -s "$repository/frontend" "$runtime/releases/known-good"
ln -s "$runtime/releases/known-good" "$runtime/current"
chmod 755 "$runtime" "$runtime/logs"
chmod 700 "$runtime/client-body"

openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -keyout "$runtime/private.key" \
  -out "$runtime/certificate.pem" \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost" >/dev/null 2>&1
chmod 600 "$runtime/private.key"

python -m scripts.render_nginx_config \
  --template "$repository/deploy/nginx/reconcile.conf.example" \
  --output "$runtime/reconcile.conf" \
  --host localhost \
  --certificate "$runtime/certificate.pem" \
  --private-key "$runtime/private.key" \
  --client-body-temp "$runtime/client-body" \
  --access-log "$runtime/logs/access.log" \
  --error-log "$runtime/logs/error.log" \
  --api-port 8000 \
  --web-port 3000 \
  --listen-address 127.0.0.1 \
  --http-port "$http_port" \
  --https-port "$https_port"

cat >"$runtime/nginx.conf" <<EOF
worker_processes 1;
pid $runtime/nginx.pid;
error_log $runtime/logs/main-error.log crit;
events { worker_connections 128; }
http {
    include ${NGINX_MIME_TYPES:-/etc/nginx/mime.types};
    default_type application/octet-stream;
    include $runtime/reconcile.conf;
}
EOF

cd "$repository"
python -m scripts.production_e2e \
  --host 127.0.0.1 \
  --port 8000 \
  --frontend-origin "$origin" >"$runtime/logs/api.log" 2>&1 &
api_pid=$!

(
  cd "$runtime/current"
  exec env -i PATH="$PATH" NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 \
    node "$repository/frontend/node_modules/next/dist/bin/next" start --hostname 127.0.0.1 --port 3000
) >"$runtime/logs/web.log" 2>&1 &
web_pid=$!

for attempt in {1..60}; do
  if curl --fail --silent http://127.0.0.1:8000/health >/dev/null && \
    curl --fail --silent http://127.0.0.1:3000/login >/dev/null; then
    break
  fi
  [[ "$attempt" -lt 60 ]] || {
    echo "Loopback application services did not become ready" >&2
    exit 1
  }
  sleep 1
done

[[ "$(ss -H -ltn 'sport = :8000' | awk '{print $4}')" == "127.0.0.1:8000" ]]
[[ "$(ss -H -ltn 'sport = :3000' | awk '{print $4}')" == "127.0.0.1:3000" ]]
database_port="$(python -c 'import os; from sqlalchemy.engine import make_url; url=make_url(os.environ["TEST_DATABASE_ADMIN_URL"]); assert url.host in {"localhost", "127.0.0.1"}; print(url.port or 5432)')"
[[ "$(ss -H -ltn "sport = :$database_port" | awk '{print $4}')" == "127.0.0.1:$database_port" ]]

nginx -t -c "$runtime/nginx.conf" -p "$runtime"
nginx -c "$runtime/nginx.conf" -p "$runtime"
nginx_started=true
[[ "$(ss -H -ltn "sport = :$https_port" | awk '{print $4}')" == "127.0.0.1:$https_port" ]]

for attempt in {1..30}; do
  if curl --fail --silent --insecure "$origin/health/ready" >/dev/null; then
    break
  fi
  [[ "$attempt" -lt 30 ]] || {
    echo "HTTPS deployment profile did not become ready" >&2
    exit 1
  }
  sleep 1
done
curl --fail --silent --insecure --tlsv1.2 --tls-max 1.2 "$origin/health" >/dev/null
curl --fail --silent --insecure --tlsv1.3 "$origin/health" >/dev/null

(
  cd frontend
  export PRODUCTION_E2E_ORIGIN="$origin"
  export PRODUCTION_E2E_HTTP_ORIGIN="http://localhost:$http_port"
  export WSLENV="${WSLENV:-}:PRODUCTION_E2E_ORIGIN:PRODUCTION_E2E_HTTP_ORIGIN"
  if [[ "$#" -gt 0 ]]; then
    "$@"
  else
    npx playwright test --config=playwright.deployment.config.ts
  fi
)

nginx -s reload -c "$runtime/nginx.conf" -p "$runtime"
curl --fail --silent --insecure "$origin/health/ready" >/dev/null

kill -TERM "$web_pid"
for attempt in {1..30}; do
  if ! kill -0 "$web_pid" 2>/dev/null; then
    wait "$web_pid" || [[ "$?" == 143 ]]
    web_pid=""
    break
  fi
  [[ "$attempt" -lt 30 ]] || {
    echo "Next.js did not stop gracefully" >&2
    exit 1
  }
  sleep 1
done
ln -sfn "$runtime/releases/rejected" "$runtime/current"
(
  cd "$runtime/current"
  exec env -i PATH="$PATH" NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 \
    node "$repository/frontend/node_modules/next/dist/bin/next" start --hostname 127.0.0.1 --port 3000
) >"$runtime/logs/rejected-release.log" 2>&1 &
web_pid=$!
for attempt in {1..30}; do
  if ! kill -0 "$web_pid" 2>/dev/null; then
    if wait "$web_pid"; then
      echo "An unbuilt release unexpectedly started" >&2
      exit 1
    fi
    web_pid=""
    break
  fi
  [[ "$attempt" -lt 30 ]] || { echo "Rejected release did not exit" >&2; exit 1; }
  sleep 1
done
[[ "$(curl --silent --insecure -o /dev/null -w '%{http_code}' "$origin/login")" == 503 ]]
curl --fail --silent --insecure "$origin/health/ready" >/dev/null
ln -sfn "$runtime/releases/known-good" "$runtime/current"
(
  cd "$runtime/current"
  exec env -i PATH="$PATH" NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 \
    node "$repository/frontend/node_modules/next/dist/bin/next" start --hostname 127.0.0.1 --port 3000
) >"$runtime/logs/web-restart.log" 2>&1 &
web_pid=$!
for attempt in {1..30}; do
  if curl --fail --silent --insecure "$origin/login" >/dev/null; then
    break
  fi
  [[ "$attempt" -lt 30 ]] || {
    echo "Next.js did not recover after the graceful restart" >&2
    exit 1
  }
  sleep 1
done

if grep -R --quiet "deployment-log-private-marker" "$runtime/logs"; then
  echo "A deployment log retained the private regression marker" >&2
  exit 1
fi

grep --quiet '"event":"http_request"' "$runtime/logs/api.log"
grep --quiet '"request_id"' "$runtime/logs/access.log"
[[ -z "$(find "$runtime/client-body" -type f -print -quit)" ]]

curl --fail --silent --insecure -o /dev/null \
  -w 'Synthetic readiness sample: total=%{time_total}s status=%{http_code}\n' "$origin/health/ready"
echo "Synthetic API resident memory (KiB): $(ps -o rss= --ppid "$api_pid" | tr -d ' ')"
echo "Synthetic frontend resident memory (KiB): $(ps -o rss= -p "$web_pid" | tr -d ' ')"

echo "Production deployment acceptance passed."
