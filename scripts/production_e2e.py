"""Run the production API profile against a launcher-owned disposable database."""

import argparse
import os
import secrets
import signal
import subprocess
import sys
from pathlib import Path

from reconcile.auth.runtime import AuthRuntime
from scripts.postgres_testing import provision_database

DEFAULT_MANAGER_EMAIL = "deployment-manager@example.com"
DEFAULT_OUTSIDER_EMAIL = "deployment-outsider@example.com"
DEFAULT_PASSWORD = "synthetic deployment passphrase"


def _production_environment(database_environment: dict[str, str], origin: str) -> dict[str, str]:
    environment = {
        key: os.environ[key]
        for key in (
            "PATH",
            "PYTHONPATH",
            "PYTHONHOME",
            "SYSTEMROOT",
            "TEMP",
            "TMP",
            "LD_LIBRARY_PATH",
        )
        if key in os.environ
    }
    return {
        **environment,
        **database_environment,
        "APP_ENV": "production",
        "AUTH_REQUIRE_VERIFICATION": "true",
        "AUTH_REGISTRATION_ENABLED": "false",
        "AUTH_DOCS_ENABLED": "false",
        "AUTH_MAIL_MODE": "smtp",
        "AUTH_CSRF_SECRET": secrets.token_urlsafe(32),
        "FRONTEND_PUBLIC_URL": origin,
        "RECONCILE_ALLOWED_ORIGINS": origin,
        "SMTP_HOST": "127.0.0.1",
        "SMTP_PORT": "1025",
        "SMTP_TLS": "starttls",
        "SMTP_SENDER": "acceptance@example.com",
    }


def _serve(environment: dict[str, str], host: str, port: int) -> None:
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "reconcile.web.app:app",
        "--host",
        host,
        "--port",
        str(port),
        "--proxy-headers",
        "--forwarded-allow-ips=127.0.0.1",
        "--limit-concurrency=16",
        "--backlog=64",
        "--timeout-keep-alive=5",
        "--timeout-graceful-shutdown=25",
        "--no-access-log",
        "--log-config",
        str(Path(__file__).parents[1] / "deploy" / "logging.json"),
    ]
    with subprocess.Popen(command, env=environment) as process:
        previous_handlers = {
            value: signal.getsignal(value) for value in (signal.SIGINT, signal.SIGTERM)
        }

        def stop(signum, frame):
            process.terminate()

        for value in previous_handlers:
            signal.signal(value, stop)
        try:
            status = process.wait()
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            for value, handler in previous_handlers.items():
                signal.signal(value, handler)
    if status:
        raise SystemExit("Production acceptance API exited unsuccessfully")


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
    if args.host != "127.0.0.1":
        raise SystemExit("The disposable acceptance API must bind to IPv4 loopback")
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
        _serve(
            _production_environment(database_environment, args.frontend_origin),
            args.host,
            args.port,
        )


if __name__ == "__main__":
    main()
