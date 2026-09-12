from datetime import UTC, datetime, timedelta, timezone

import pytest

from reconcile.persistence.dashboard_policy import Period, ReportingWindow


@pytest.mark.parametrize("window", list(ReportingWindow))
@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2024, 3, 1, 15, 30, tzinfo=UTC),
        datetime(2026, 9, 12, 2, tzinfo=timezone(timedelta(hours=8))),
    ],
)
def test_windows_cover_requested_utc_calendar_days_including_partial_today(window, now):
    period = Period.at(window, now)
    assert period.end == now.astimezone(UTC)
    assert period.start.time().isoformat() == "00:00:00"
    assert (period.end.date() - period.start.date()).days == window.days - 1
    assert period.payload()["window"] == window.value
