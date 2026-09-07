"""Persistent identifier limits; each attempt is charged in its own transaction."""

import hashlib
import hmac
from datetime import datetime, timedelta

from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from reconcile.auth.config import AuthSettings
from reconcile.persistence.auth_models import AuthThrottle


class Throttle:
    def __init__(self, engine: Engine, settings: AuthSettings) -> None:
        self.engine = engine
        self.settings = settings

    def bucket(self, action: str, identifier: str) -> str:
        return hmac.new(
            self.settings.csrf_secret, f"throttle:{action}:{identifier}".encode(), hashlib.sha256
        ).hexdigest()

    def allow(self, action: str, identifier: str, now: datetime) -> bool:
        key = self.bucket(action, identifier)
        login = action == "login"
        maximum = self.settings.login_attempts if login else self.settings.mail_attempts
        window = self.settings.login_window_seconds if login else self.settings.mail_window_seconds
        with Session(self.engine) as session, session.begin():
            session.execute(
                insert(AuthThrottle)
                .values(bucket_hash=key, attempts=0, window_started_at=now)
                .on_conflict_do_nothing(index_elements=[AuthThrottle.bucket_hash])
            )
            row = session.scalar(
                select(AuthThrottle).where(AuthThrottle.bucket_hash == key).with_for_update()
            )
            if row.window_started_at + timedelta(seconds=window) <= now:
                row.window_started_at, row.attempts = now, 0
            if row.attempts >= maximum:
                return False
            row.attempts += 1
            return True

    def clear_login(self, session: Session, email: str) -> None:
        row = session.scalar(
            select(AuthThrottle)
            .where(AuthThrottle.bucket_hash == self.bucket("login", email))
            .with_for_update()
        )
        if row:
            row.attempts = 0
