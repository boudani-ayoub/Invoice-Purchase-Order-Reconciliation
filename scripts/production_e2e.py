"""Run the production API profile against a launcher-owned disposable database."""

import argparse
import os
import secrets

import uvicorn

from reconcile.auth.runtime import AuthRuntime
from scripts.postgres_testing import provision_database

DEFAULT_MANAGER_EMAIL = "deployment-manager@example.com"
DEFAULT_OUTSIDER_EMAIL = "deployment-outsider@example.com"
DEFAULT_PASSWORD = "synthetic deployment passphrase"


def _seed_accounts() -> None:
    runtime = AuthRuntime.from_environment()
    try:
        runtime.accounts.register(
            os.environ.get("PRODUCTION_E2E_MANAGER_EMAIL", DEFAULT_MANAGER_EMAIL),
            os.environ.get("PRODUCTION_E2E_PASSWORD", DEFAULT_PASSWORD),
            "Deployment manager",
            "Deployment acceptance organization",
        )
        runtime.accounts.register(
            os.environ.get("PRODUCTION_E2E_OUTSIDER_EMAIL", DEFAULT_OUTSIDER_EMAIL),
            os.environ.get("PRODUCTION_E2E_PASSWORD", DEFAULT_PASSWORD),
            "Deployment outsider",
            "Isolated acceptance organization",
        )
    finally:
        runtime.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--frontend-origin", default="https://localhost")
    args = parser.parse_args()
    configured = os.environ.get("TEST_DATABASE_ADMIN_URL")
    if not configured:
        raise SystemExit("TEST_DATABASE_ADMIN_URL must identify a disposable PostgreSQL server")

    with provision_database(configured) as database:
        database_environment = {
            "DATABASE_URL": database.runtime.url.render_as_string(hide_password=False),
            "IDENTITY_DATABASE_URL": database.identity.url.render_as_string(hide_password=False),
        }
        os.environ.update(
            {
                **database_environment,
                "APP_ENV": "development",
                "AUTH_REQUIRE_VERIFICATION": "false",
                "AUTH_MAIL_MODE": "disabled",
                "AUTH_CSRF_SECRET": secrets.token_urlsafe(32),
                "FRONTEND_PUBLIC_URL": args.frontend_origin,
                "RECONCILE_ALLOWED_ORIGINS": args.frontend_origin,
            }
        )
        _seed_accounts()
        os.environ.update(
            {
                **database_environment,
                "APP_ENV": "production",
                "AUTH_REQUIRE_VERIFICATION": "true",
                "AUTH_REGISTRATION_ENABLED": "false",
                "AUTH_DOCS_ENABLED": "false",
                "AUTH_MAIL_MODE": "smtp",
                "SMTP_HOST": "127.0.0.1",
                "SMTP_PORT": "1025",
                "SMTP_TLS": "starttls",
                "SMTP_SENDER": "acceptance@example.com",
            }
        )
        uvicorn.run(
            "reconcile.web.app:app",
            host=args.host,
            port=args.port,
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1",
            limit_concurrency=16,
            backlog=64,
            timeout_keep_alive=5,
            access_log=False,
        )


if __name__ == "__main__":
    main()
