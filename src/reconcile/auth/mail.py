"""Small delivery boundary; secret links are never written to application logs."""

import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from reconcile.auth.config import AuthSettings


@dataclass(frozen=True)
class Mail:
    recipient: str = field(repr=False)
    subject: str
    body: str = field(repr=False)


class Mailer(Protocol):
    def send(self, mail: Mail) -> None: ...


class SmtpMailer:
    def __init__(self, settings: AuthSettings) -> None:
        self.settings = settings

    def send(self, mail: Mail) -> None:
        settings = self.settings
        message = EmailMessage()
        message["From"] = settings.smtp_sender
        message["To"] = mail.recipient
        message["Subject"] = mail.subject
        message.set_content(mail.body)
        context = ssl.create_default_context()
        if settings.smtp_tls == "ssl":
            connection = smtplib.SMTP_SSL(
                settings.smtp_host, settings.smtp_port, timeout=10, context=context
            )
        else:
            connection = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
        with connection:
            if settings.smtp_tls == "starttls":
                connection.starttls(context=context)
            if settings.smtp_username:
                connection.login(settings.smtp_username, settings.smtp_password)
            connection.send_message(message)


class DisabledMailer:
    def send(self, mail: Mail) -> None:
        raise RuntimeError("Email delivery is disabled in this development environment")
