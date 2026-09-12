"""Bounded UTC reporting windows, distinct from current workflow state."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

WORKLOAD_PAGE_SIZE = 25
WORKLOAD_PAGE_MAX = 100


class ReportingWindow(StrEnum):
    WEEK = "7d"
    MONTH = "30d"
    QUARTER = "90d"

    @property
    def days(self) -> int:
        return {self.WEEK: 7, self.MONTH: 30, self.QUARTER: 90}[self]


@dataclass(frozen=True)
class Period:
    window: ReportingWindow
    start: datetime
    end: datetime

    @classmethod
    def at(cls, window: ReportingWindow, now: datetime):
        end = now.astimezone(UTC)
        midnight = end.replace(hour=0, minute=0, second=0, microsecond=0)
        return cls(window, midnight - timedelta(days=window.days - 1), end)

    def payload(self) -> dict:
        return {"window": self.window, "start": self.start.isoformat(), "end": self.end.isoformat()}
