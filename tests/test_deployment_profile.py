import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from reconcile.web import health
from scripts.production_e2e import _production_environment
from scripts.render_nginx_config import render

ROOT = Path(__file__).parents[1]
NGINX = ROOT / "deploy" / "nginx" / "reconcile.conf.example"


def values():
    return {
        "PUBLIC_HOST": "reconcile.example.com",
        "TLS_CERTIFICATE": "/etc/reconcile/tls/fullchain.pem",
        "TLS_PRIVATE_KEY": "/etc/reconcile/tls/private.key",
        "CLIENT_BODY_TEMP": "/var/cache/nginx/reconcile-client-temp",
        "ACCESS_LOG": "/var/log/nginx/reconcile-access.log",
        "ERROR_LOG": "/var/log/nginx/reconcile-error.log",
        "API_PORT": "8000",
        "WEB_PORT": "3000",
        "LISTEN_ADDRESS": "0.0.0.0",
        "HTTP_PORT": "80",
        "HTTPS_PORT": "443",
    }


def test_nginx_profile_has_reviewed_same_origin_resource_boundaries():
    configured = render(NGINX.read_text(encoding="utf-8"), values())

    assert "listen 0.0.0.0:80 default_server" in configured
    assert "return 308 https://reconcile.example.com$request_uri" in configured
    assert "ssl_protocols TLSv1.2 TLSv1.3" in configured
    assert "server 127.0.0.1:8000" in configured
    assert "server 127.0.0.1:3000" in configured
    assert "proxy_set_header X-Forwarded-For $remote_addr" in configured
    assert "proxy_set_header X-Forwarded-Proto https" in configured
    assert "proxy_add_x_forwarded_for" not in configured
    log_format = configured.split("log_format reconcile_safe", 1)[1].split(";", 1)[0]
    assert "$request_uri" not in log_format and "$request " not in log_format
    assert '"request_id":"$sent_http_x_request_id"' in configured
    assert "client_max_body_size 32m" in configured
    assert "client_max_body_size 32k" in configured
    assert "limit_conn reconcile_per_ip 4" in configured
    assert "limit_req zone=reconcile_auth" in configured
    assert "unsafe-eval" not in configured
    assert "ssl_certificate /etc/reconcile/tls/fullchain.pem" in configured
    assert "{{" not in configured


@pytest.mark.parametrize(
    "field,value",
    [
        ("PUBLIC_HOST", "Example.COM"),
        ("PUBLIC_HOST", "example.com; include /tmp/private"),
        ("TLS_PRIVATE_KEY", "relative/private.key"),
        ("CLIENT_BODY_TEMP", "/tmp/path with spaces"),
        ("API_PORT", "0"),
        ("WEB_PORT", "65536"),
        ("LISTEN_ADDRESS", "0.0.0.0; include /tmp/private"),
    ],
)
def test_nginx_renderer_rejects_fragment_injection(field, value):
    configured = values()
    configured[field] = value
    with pytest.raises((ValueError, TypeError)):
        render(NGINX.read_text(encoding="utf-8"), configured)


@pytest.mark.parametrize(
    "service,command",
    [
        (
            "reconcile-api.service.example",
            "--host 127.0.0.1 --port 8000 --workers 2 --proxy-headers "
            "--forwarded-allow-ips=127.0.0.1 --limit-concurrency 16",
        ),
        (
            "reconcile-web.service.example",
            "--hostname 127.0.0.1 --port 3000",
        ),
    ],
)
def test_services_are_unprivileged_loopback_and_bounded(service, command):
    unit = (ROOT / "deploy" / "systemd" / service).read_text(encoding="utf-8")
    assert "User=reconcile" in unit and "Group=reconcile" in unit
    assert command in unit
    assert "Restart=on-failure" in unit
    assert "TimeoutStopSec=30s" in unit
    assert "LimitNOFILE=4096" in unit
    assert "NoNewPrivileges=true" in unit
    assert "ProtectSystem=strict" in unit
    assert "0.0.0.0" not in unit and "forwarded-allow-ips=*" not in unit


def test_local_acceptance_can_use_unprivileged_loopback_ports():
    configured = render(
        NGINX.read_text(encoding="utf-8"),
        {**values(), "LISTEN_ADDRESS": "127.0.0.1", "HTTP_PORT": "8080", "HTTPS_PORT": "8443"},
    )
    assert "listen 127.0.0.1:8443 ssl" in configured
    assert "return 308 https://reconcile.example.com:8443$request_uri" in configured
    assert "proxy_set_header Host reconcile.example.com:8443" in configured


@pytest.mark.parametrize("client,trusted", [("198.51.100.10", False), ("127.0.0.1", True)])
def test_only_the_actual_proxy_can_supply_forwarded_origin_and_client(client, trusted):
    async def application(scope, receive, send):
        await JSONResponse({"scheme": scope["scheme"], "client": scope["client"][0]})(
            scope, receive, send
        )

    proxy = ProxyHeadersMiddleware(application, trusted_hosts="127.0.0.1")
    browser = TestClient(proxy, client=(client, 12345))
    try:
        response = browser.get(
            "/",
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-For": "192.0.2.42"},
        )
    finally:
        browser.close()
    assert response.json() == {
        "scheme": "https" if trusted else "http",
        "client": "192.0.2.42" if trusted else client,
    }


def test_readiness_response_does_not_wait_for_a_blocked_database_probe(monkeypatch):
    def blocked_probe(engine, timeout):
        time.sleep(0.8)

    monkeypatch.setattr(health, "_probe", blocked_probe)
    runtime = SimpleNamespace(
        settings=SimpleNamespace(readiness_timeout_seconds=0.05), identity=None, tenant=None
    )
    started = time.monotonic()
    assert not asyncio.run(health.databases_ready(runtime))
    assert time.monotonic() - started < 0.5


def test_production_logging_explicitly_enables_only_safe_access_events():
    configured = json.loads((ROOT / "deploy" / "logging.json").read_text(encoding="utf-8"))
    assert configured["loggers"]["reconcile.access"]["level"] == "INFO"
    assert configured["loggers"]["uvicorn.access"]["handlers"] == []
    assert configured["formatters"]["safe"]["format"] == "%(message)s"


def test_acceptance_http_child_does_not_inherit_operator_or_provider_secrets(monkeypatch):
    monkeypatch.setenv("TEST_DATABASE_ADMIN_URL", "private-admin-url")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "private-owner-url")
    monkeypatch.setenv("SMTP_PASSWORD", "private-provider-password")
    monkeypatch.setenv("GITHUB_TOKEN", "private-provider-token")
    restricted = {
        "DATABASE_URL": "restricted-tenant",
        "IDENTITY_DATABASE_URL": "restricted-identity",
    }
    environment = _production_environment(restricted, "https://localhost:8443")
    assert all(not value.startswith("private-") for value in environment.values())
    assert environment["DATABASE_URL"] == restricted["DATABASE_URL"]
    assert environment["IDENTITY_DATABASE_URL"] == restricted["IDENTITY_DATABASE_URL"]
    assert environment["APP_ENV"] == "production"
    assert environment["AUTH_DOCS_ENABLED"] == "false"
