"""Bounded windows and pages for read-only intelligence queries."""

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from reconcile.auth.service_errors import AuthError

INTELLIGENCE_PAGE_SIZE = 25
INTELLIGENCE_PAGE_MAX = 100


class IntelligenceWindow(StrEnum):
    WEEK = "7d"
    MONTH = "30d"
    QUARTER = "90d"

    @property
    def days(self) -> int:
        return {self.WEEK: 7, self.MONTH: 30, self.QUARTER: 90}[self]


@dataclass(frozen=True)
class Period:
    start: datetime
    end: datetime
    window: IntelligenceWindow

    @classmethod
    def at(cls, window: IntelligenceWindow, now: datetime) -> "Period":
        end = now.astimezone(UTC)
        return cls(end - timedelta(days=window.days), end, window)

    def payload(self) -> dict[str, str]:
        return {
            "window": self.window.value,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "time_field": "occurred_at",
        }


def encode_cursor(values: list[str]) -> str:
    raw = json.dumps(values, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value: str, size: int) -> list[str]:
    try:
        if not 1 <= len(value) <= 512:
            raise ValueError
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        parsed = json.loads(raw)
        if (
            not isinstance(parsed, list)
            or len(parsed) != size
            or not all(isinstance(item, str) and item for item in parsed)
        ):
            raise ValueError
        return parsed
    except (ValueError, TypeError, OverflowError, binascii.Error):
        raise AuthError(400, "invalid_cursor", "The intelligence cursor is invalid.") from None
