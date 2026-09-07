"""Validated private authentication settings."""

import base64
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

CSRF_HEADER = "X-CSRF-Token"
AUTH_PATH = "/api/v1/auth"
PASSWORD_MIN_LENGTH = 15
PASSWORD_MAX_LENGTH = 128
TOKEN_BYTES = 32
IDENTITY_GROUP = "reconcile_identity"


def origin(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        parts = urlsplit(value)
        valid = (
            parts.scheme in {"http", "https"}
            and parts.hostname
            and not parts.username
            and not parts.password
            and not parts.path
            and not parts.query
            and not parts.fragment
            and parts.port != 0
            and "*" not in value
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Browser origins must be explicit HTTP(S) origins without credentials")
    return value


@dataclass(frozen=True)
class AuthSettings:
    environment: str
    frontend_origin: str
    trusted_origins: tuple[str, ...]
    identity_database_url: str = field(repr=False)
    tenant_database_url: str = field(repr=False)
    csrf_secret: bytes = field(repr=False)
    require_verification: bool = True
    registration_enabled: bool = True
    mail_mode: str = "smtp"
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_username: str = field(default="", repr=False)
    smtp_password: str = field(default="", repr=False)
    smtp_sender: str = ""
    smtp_tls: str = "ssl"
    session_idle_seconds: int = 1800
    session_absolute_seconds: int = 43200
    verification_seconds: int = 86400
    reset_seconds: int = 1800
    login_attempts: int = 5
    login_window_seconds: int = 900
    mail_attempts: int = 3
    mail_window_seconds: int = 3600
    docs_enabled: bool = False

    def __post_init__(self) -> None:
        if self.environment not in {"development", "production"}:
            raise ValueError("APP_ENV must be development or production")
        origins = (origin(self.frontend_origin), *(origin(v) for v in self.trusted_origins))
        if self.frontend_origin not in self.trusted_origins:
            raise ValueError("FRONTEND_PUBLIC_URL must be a trusted browser origin")
        if len(self.csrf_secret) < 32 or len(set(self.csrf_secret)) < 16:
            raise ValueError("AUTH_CSRF_SECRET must contain at least 32 securely random bytes")
        if not self.identity_database_url or not self.tenant_database_url:
            raise ValueError("Identity and tenant database connections are required")
        for setting in (
            self.session_idle_seconds,
            self.session_absolute_seconds,
            self.verification_seconds,
            self.reset_seconds,
            self.login_attempts,
            self.login_window_seconds,
            self.mail_attempts,
            self.mail_window_seconds,
        ):
            if setting <= 0:
                raise ValueError("Authentication lifetimes and limits must be positive")
        if self.session_idle_seconds > self.session_absolute_seconds:
            raise ValueError("Idle lifetime cannot exceed absolute session lifetime")
        if self.mail_mode not in {"smtp", "disabled"}:
            raise ValueError("AUTH_MAIL_MODE must be smtp or disabled")
        if self.mail_mode == "disabled" and (
            self.environment != "development" or self.require_verification
        ):
            raise ValueError("Mail may be disabled only in explicit unverified development mode")
        if self.mail_mode == "smtp" and (
            not self.smtp_host
            or not self.smtp_sender
            or self.smtp_tls not in {"ssl", "starttls"}
            or not 1 <= self.smtp_port <= 65535
        ):
            raise ValueError("SMTP requires a host, sender, valid port, and TLS transport")
        if self.environment == "production" and (
            not self.require_verification or any(not v.startswith("https://") for v in origins)
        ):
            raise ValueError("Production requires email verification and HTTPS browser origins")

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production"

    @property
    def session_cookie(self) -> str:
        return "__Host-reconcile-session" if self.secure_cookies else "reconcile-dev-session"

    @property
    def csrf_cookie(self) -> str:
        return "__Host-reconcile-csrf" if self.secure_cookies else "reconcile-dev-csrf"

    @classmethod
    def from_environment(cls) -> "AuthSettings":
        def boolean(name: str, default: bool) -> bool:
            value = os.environ.get(name, str(default)).lower()
            if value not in {"true", "false"}:
                raise ValueError(f"{name} must be true or false")
            return value == "true"

        def integer(name: str, default: int) -> int:
            try:
                return int(os.environ.get(name, str(default)))
            except ValueError:
                raise ValueError(f"{name} must be an integer") from None

        try:
            encoded = os.environ.get("AUTH_CSRF_SECRET", "")
            secret = base64.b64decode(
                encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
            )
        except ValueError:
            raise ValueError("AUTH_CSRF_SECRET must be URL-safe base64 random bytes") from None
        frontend = origin(os.environ.get("FRONTEND_PUBLIC_URL", ""))
        trusted = tuple(
            dict.fromkeys(
                (
                    frontend,
                    *(
                        origin(v)
                        for v in os.environ.get("RECONCILE_ALLOWED_ORIGINS", "").split(",")
                        if v.strip()
                    ),
                )
            )
        )
        environment = os.environ.get("APP_ENV", "production")
        return cls(
            environment=environment,
            frontend_origin=frontend,
            trusted_origins=trusted,
            identity_database_url=os.environ.get("IDENTITY_DATABASE_URL", ""),
            tenant_database_url=os.environ.get("DATABASE_URL", ""),
            csrf_secret=secret,
            require_verification=boolean("AUTH_REQUIRE_VERIFICATION", True),
            registration_enabled=boolean("AUTH_REGISTRATION_ENABLED", True),
            mail_mode=os.environ.get("AUTH_MAIL_MODE", "smtp"),
            smtp_host=os.environ.get("SMTP_HOST", ""),
            smtp_port=integer("SMTP_PORT", 465),
            smtp_username=os.environ.get("SMTP_USERNAME", ""),
            smtp_password=os.environ.get("SMTP_PASSWORD", ""),
            smtp_sender=os.environ.get("SMTP_SENDER", ""),
            smtp_tls=os.environ.get("SMTP_TLS", "ssl"),
            session_idle_seconds=integer("AUTH_SESSION_IDLE_SECONDS", 1800),
            session_absolute_seconds=integer("AUTH_SESSION_ABSOLUTE_SECONDS", 43200),
            verification_seconds=integer("AUTH_VERIFICATION_SECONDS", 86400),
            reset_seconds=integer("AUTH_RESET_SECONDS", 1800),
            login_attempts=integer("AUTH_LOGIN_ATTEMPTS", 5),
            login_window_seconds=integer("AUTH_LOGIN_WINDOW_SECONDS", 900),
            mail_attempts=integer("AUTH_MAIL_ATTEMPTS", 3),
            mail_window_seconds=integer("AUTH_MAIL_WINDOW_SECONDS", 3600),
            docs_enabled=boolean("AUTH_DOCS_ENABLED", environment == "development"),
        )
