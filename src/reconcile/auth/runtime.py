"""Provisioned identity and tenant connections, never a migration-owner request path."""

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import Engine, text

from reconcile.auth.accounts import Accounts
from reconcile.auth.config import IDENTITY_GROUP, AuthSettings
from reconcile.auth.crypto import Passwords
from reconcile.auth.mail import DisabledMailer, Mailer, SmtpMailer
from reconcile.auth.sessions import Sessions
from reconcile.persistence.session import RUNTIME_GROUP, database_engine


def utc_now() -> datetime:
    return datetime.now(UTC)


def verify_database_role(engine: Engine, *, identity: bool) -> None:
    expected = IDENTITY_GROUP if identity else RUNTIME_GROUP
    forbidden = RUNTIME_GROUP if identity else IDENTITY_GROUP
    with engine.connect() as connection:
        flags = connection.execute(
            text(
                "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
                "FROM pg_roles WHERE rolname = current_user"
            )
        ).one()
        if any(flags):
            raise ValueError("HTTP database roles must not hold administrative privileges")
        if not connection.scalar(
            text("SELECT pg_has_role(current_user, :role, 'MEMBER')"), {"role": expected}
        ):
            raise ValueError("HTTP database role lacks its provisioned privilege group")
        if connection.scalar(
            text("SELECT pg_has_role(current_user, :role, 'MEMBER')"), {"role": forbidden}
        ):
            raise ValueError("Identity and tenant privilege groups must be separated")
        if connection.scalar(
            text(
                "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' "
                "AND pg_has_role(current_user, tableowner, 'MEMBER')"
            )
        ):
            raise ValueError("HTTP database roles must not own or inherit ownership of tables")
        if connection.scalar(text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")):
            raise ValueError("HTTP database roles must not create schema objects")
        forbidden_tables = (
            (
                "invoices",
                "purchase_orders",
                "goods_receipts",
                "findings",
                "result_snapshots",
                "suppliers",
                "items",
                "source_files",
                "purchase_order_lines",
                "goods_receipt_lines",
                "invoice_lines",
                "analysis_runs",
                "analysis_sources",
                "audit_events",
                "finding_events",
            )
            if identity
            else ("users", "user_credentials", "auth_sessions", "email_tokens", "auth_throttles")
        )
        for table in forbidden_tables:
            if connection.scalar(
                text(
                    "SELECT has_table_privilege(current_user, :table, "
                    "'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')"
                ),
                {"table": table},
            ):
                raise ValueError("HTTP database role crosses the identity/tenant trust boundary")


class AuthRuntime:
    def __init__(
        self,
        settings: AuthSettings,
        identity: Engine,
        tenant: Engine,
        *,
        mailer: Mailer | None = None,
        clock: Callable[[], datetime] = utc_now,
        passwords: Passwords | None = None,
    ) -> None:
        self.settings, self.identity, self.tenant, self.clock = settings, identity, tenant, clock
        delivery = mailer or (
            SmtpMailer(settings) if settings.mail_mode == "smtp" else DisabledMailer()
        )
        self.accounts = Accounts(identity, settings, passwords or Passwords(), delivery, clock)
        self.sessions = Sessions(identity, tenant, settings, clock)

    @classmethod
    def from_environment(cls) -> "AuthRuntime":
        settings = AuthSettings.from_environment()
        identity = database_engine(settings.identity_database_url)
        tenant = database_engine(settings.tenant_database_url)
        try:
            verify_database_role(identity, identity=True)
            verify_database_role(tenant, identity=False)
            return cls(settings, identity, tenant)
        except Exception:
            identity.dispose()
            tenant.dispose()
            raise ValueError(
                "Authentication database initialization failed; "
                "check private configuration and migrations"
            ) from None

    def close(self) -> None:
        self.identity.dispose()
        self.tenant.dispose()
