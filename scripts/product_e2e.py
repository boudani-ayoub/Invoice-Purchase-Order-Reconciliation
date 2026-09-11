"""Launch a real authenticated API with a disposable, migrated PostgreSQL database."""

import argparse
import os
import secrets

import uvicorn

from scripts.postgres_testing import provision_database


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--frontend-origin", required=True)
    args = parser.parse_args()
    configured = os.environ.get("TEST_DATABASE_ADMIN_URL")
    if not configured:
        raise SystemExit("TEST_DATABASE_ADMIN_URL must identify a disposable PostgreSQL server")
    with provision_database(configured) as database:
        os.environ.update(
            {
                "APP_ENV": "development",
                "AUTH_REQUIRE_VERIFICATION": "false",
                "AUTH_MAIL_MODE": "disabled",
                "AUTH_CSRF_SECRET": secrets.token_urlsafe(32),
                "FRONTEND_PUBLIC_URL": args.frontend_origin,
                "RECONCILE_ALLOWED_ORIGINS": args.frontend_origin,
                "DATABASE_URL": database.runtime.url.render_as_string(hide_password=False),
                "IDENTITY_DATABASE_URL": database.identity.url.render_as_string(
                    hide_password=False
                ),
            }
        )
        if seed := os.environ.get("E2E_WORKFLOW_SEED"):
            from scripts.workflow_e2e_seed import seed_workflow_accounts

            seed_workflow_accounts(database, seed)
        uvicorn.run("reconcile.web.app:app", host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
