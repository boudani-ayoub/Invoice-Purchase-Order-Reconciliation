#!/usr/bin/env bash
set -Eeuo pipefail

repository="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime="$(mktemp -d)"
api_pid=""
web_pid=""
nginx_started=false

cleanup() {
  set +e
  if [[ "$nginx_started" == true ]]; then
    sudo nginx -s quit -c "$runtime/nginx.conf" -p "$runtime"
  fi
  [[ -n "$web_pid" ]] && kill -TERM "$web_pid" 2>/dev/null
  [[ -n "$api_pid" ]] && kill -TERM "$api_pid" 2>/dev/null
  [[ -n "$web_pid" ]] && wait "$web_pid" 2>/dev/null
  [[ -n "$api_pid" ]] && wait "$api_pid" 2>/dev/null
  rm -rf -- "$runtime"
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

mkdir -p "$runtime/client-body" "$runtime/logs"
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
  --web-port 3000

cat >"$runtime/nginx.conf" <<EOF
user $(id -un);
worker_processes 1;
pid $runtime/nginx.pid;
error_log $runtime/logs/main-error.log crit;
events { worker_connections 128; }
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    include $runtime/reconcile.conf;
}
EOF

cd "$repository"
python -m scripts.production_e2e \
  --host 127.0.0.1 \
  --port 8000 \
  --frontend-origin https://localhost >"$runtime/logs/api.log" 2>&1 &
api_pid=$!

(
  cd frontend
  NEXT_PUBLIC_API_BASE_URL=https://localhost npm run start -- \
    --hostname 127.0.0.1 --port 3000
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

api_socket="$(ss -H -ltn 'sport = :8000')"
web_socket="$(ss -H -ltn 'sport = :3000')"
[[ "$api_socket" == *"127.0.0.1:8000"* && "$api_socket" != *"0.0.0.0:8000"* ]]
[[ "$web_socket" == *"127.0.0.1:3000"* && "$web_socket" != *"0.0.0.0:3000"* ]]

sudo nginx -t -c "$runtime/nginx.conf" -p "$runtime"
sudo nginx -c "$runtime/nginx.conf" -p "$runtime"
nginx_started=true

for attempt in {1..30}; do
  if curl --fail --silent --insecure https://localhost/health/ready >/dev/null; then
    break
  fi
  [[ "$attempt" -lt 30 ]] || {
    echo "HTTPS deployment profile did not become ready" >&2
    exit 1
  }
  sleep 1
done

(
  cd frontend
  PRODUCTION_E2E_ORIGIN=https://localhost \
    npx playwright test --config=playwright.deployment.config.ts
)

sudo nginx -s reload -c "$runtime/nginx.conf" -p "$runtime"
curl --fail --silent --insecure https://localhost/health/ready >/dev/null

kill -TERM "$web_pid"
for attempt in {1..30}; do
  if ! kill -0 "$web_pid" 2>/dev/null; then
    wait "$web_pid"
    web_pid=""
    break
  fi
  [[ "$attempt" -lt 30 ]] || {
    echo "Next.js did not stop gracefully" >&2
    exit 1
  }
  sleep 1
done
(
  cd frontend
  NEXT_PUBLIC_API_BASE_URL=https://localhost npm run start -- \
    --hostname 127.0.0.1 --port 3000
) >"$runtime/logs/web-restart.log" 2>&1 &
web_pid=$!
for attempt in {1..30}; do
  if curl --fail --silent --insecure https://localhost/login >/dev/null; then
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

echo "Production deployment acceptance passed."
