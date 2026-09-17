from pathlib import Path

import pytest

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
    }


def test_nginx_profile_has_reviewed_same_origin_resource_boundaries():
    configured = render(NGINX.read_text(encoding="utf-8"), values())

    assert "listen 80 default_server" in configured
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
