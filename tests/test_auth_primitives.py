import base64
import os
from dataclasses import replace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("argon2")
from reconcile.auth.config import AuthSettings, origin
from reconcile.auth.crypto import (
    Passwords,
    csrf_token,
    csrf_valid,
    new_token,
    password_valid,
    token_hash,
)
from reconcile.auth.mail import Mail, SmtpMailer


@pytest.fixture
def settings():
    return AuthSettings(
        environment="production",
        frontend_origin="https://reconcile.example.com",
        trusted_origins=("https://reconcile.example.com",),
        identity_database_url="postgresql://identity@example.com/product",
        tenant_database_url="postgresql://tenant@example.com/product",
        csrf_secret=bytes(range(32)),
        smtp_host="mail.example.com",
        smtp_sender="accounts@example.com",
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"environment": "staging"},
        {"csrf_secret": b"secret"},
        {"csrf_secret": b"x" * 32},
        {"require_verification": False},
        {"mail_mode": "disabled"},
        {"smtp_tls": "none"},
        {"smtp_host": ""},
        {"smtp_port": 0},
        {"session_idle_seconds": 0},
        {"session_idle_seconds": 43201},
        {"identity_database_url": ""},
        {"trusted_origins": ("*",)},
        {
            "frontend_origin": "http://reconcile.example.com",
            "trusted_origins": ("http://reconcile.example.com",),
        },
    ],
)
def test_contradictory_or_weak_settings_fail_closed(settings, changes):
    with pytest.raises(ValueError):
        replace(settings, **changes)


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "https://*.example.com",
        "https://name:private@example.com",
        "https://example.com/path",
        "https://example.com:99999",
        "https://example.com?token=private",
    ],
)
def test_origin_errors_never_echo_supplied_secrets(value):
    with pytest.raises(ValueError) as error:
        origin(value)
    assert "private" not in str(error.value)


def test_development_cookie_names_are_separate(settings):
    development = replace(
        settings, environment="development", require_verification=False, mail_mode="disabled"
    )
    assert development.session_cookie != settings.session_cookie
    assert development.csrf_cookie != settings.csrf_cookie
    assert not development.secure_cookies and settings.secure_cookies
    assert settings.session_cookie.startswith("__Host-")


def test_environment_defaults_to_production_and_hides_secrets(monkeypatch, settings):
    for key in list(os.environ):
        if key.startswith(("AUTH_", "SMTP_")) or key in {"APP_ENV", "RECONCILE_ALLOWED_ORIGINS"}:
            monkeypatch.delenv(key)
    for key, value in {
        "FRONTEND_PUBLIC_URL": settings.frontend_origin,
        "DATABASE_URL": settings.tenant_database_url,
        "IDENTITY_DATABASE_URL": settings.identity_database_url,
        "AUTH_CSRF_SECRET": base64.urlsafe_b64encode(settings.csrf_secret).decode(),
        "SMTP_HOST": settings.smtp_host,
        "SMTP_SENDER": settings.smtp_sender,
        "SMTP_PASSWORD": "smtp-private-value",
    }.items():
        monkeypatch.setenv(key, value)
    loaded = AuthSettings.from_environment()
    assert loaded.environment == "production" and not loaded.docs_enabled
    assert "smtp-private-value" not in repr(loaded)
    assert "postgresql://" not in repr(loaded)
    monkeypatch.setenv("AUTH_CSRF_SECRET", "not a valid secret!")
    with pytest.raises(ValueError) as error:
        AuthSettings.from_environment()
    assert "not a valid secret!" not in str(error.value)


@pytest.mark.parametrize(
    "password, valid",
    [
        ("x" * 14, False),
        (" " * 15, True),
        ("é" * 128, True),
        ("😀" * 128, True),
        ("x" * 129, False),
        ("x" * 15 + "\ud800", False),
    ],
)
def test_password_length_counts_unicode_without_composition_rules(password, valid):
    assert password_valid(password) is valid


def test_password_hash_preserves_spaces_and_unicode():
    passwords = Passwords()
    password = "  a long café passphrase  "
    encoded = passwords.hash(password)
    assert passwords.verify(encoded, password)
    assert not passwords.verify(encoded, password.strip())
    assert not passwords.verify(encoded, password.replace("é", "e\u0301"))
    assert not passwords.verify(None, password)
    assert not passwords.needs_rehash(encoded)


def test_csrf_binds_cookie_session_nonce_and_signing_key(settings):
    context, session = new_token(), new_token()
    proof = csrf_token(settings.csrf_secret, context, session)
    assert csrf_valid(settings.csrf_secret, context, session, proof)
    assert not csrf_valid(settings.csrf_secret, new_token(), session, proof)
    assert not csrf_valid(settings.csrf_secret, context, new_token(), proof)
    assert not csrf_valid(b"changed-key", context, session, proof)
    assert not csrf_valid(settings.csrf_secret, context, session, "invalid")
    assert csrf_token(settings.csrf_secret, context, session) != proof
    assert len(session) == 43 and len(token_hash(session)) == 64
    assert session not in token_hash(session)


@pytest.mark.parametrize("mode", ["ssl", "starttls"])
def test_smtp_uses_verified_tls_and_keeps_tokens_out_of_repr(settings, monkeypatch, mode):
    settings = replace(
        settings, smtp_tls=mode, smtp_username="account", smtp_password="private-smtp-password"
    )
    connection = MagicMock()
    connection.__enter__.return_value = connection
    factory = MagicMock(return_value=connection)
    monkeypatch.setattr(
        "reconcile.auth.mail.smtplib.SMTP_SSL"
        if mode == "ssl"
        else "reconcile.auth.mail.smtplib.SMTP",
        factory,
    )
    mail = Mail("recipient@example.com", "Verify email", "private-token")
    SmtpMailer(settings).send(mail)
    assert "private-token" not in repr(mail) and mail.recipient not in repr(mail)
    context = (
        factory.call_args.kwargs["context"]
        if mode == "ssl"
        else connection.starttls.call_args.kwargs["context"]
    )
    assert context.check_hostname
    connection.login.assert_called_once_with("account", "private-smtp-password")
    connection.send_message.assert_called_once()
