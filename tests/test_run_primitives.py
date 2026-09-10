import base64
from datetime import UTC, datetime
from uuid import uuid4

import pytest

pytest.importorskip("sqlalchemy")
from reconcile.auth.service_errors import AuthError
from reconcile.persistence.runs import decode_cursor
from reconcile.web.provenance import safe_filename


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "source.csv"),
        ("", "source.csv"),
        ("..", "source.csv"),
        ("/tmp/path.csv", "path.csv"),
        ("C:\\fakepath\\invoice.csv", "invoice.csv"),
        ("\x00\n\r", "source.csv"),
        ("abc\u202edef.csv", "abcdef.csv"),
        ("a" * 300, "a" * 255),
        ("فاتورة.csv", "فاتورة.csv"),
    ],
)
def test_safe_filename_is_metadata_not_path(value, expected):
    assert safe_filename(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "!!",
        "e30",
        "W10",
        "WyJhIiwiYiIsImMiXQ",
        "x" * 257,
        base64.urlsafe_b64encode(b'["2026-01-01", "invalid"]').decode(),
    ],
)
def test_bad_cursor_is_a_safe_client_error(value):
    with pytest.raises(AuthError) as error:
        decode_cursor(value)
    assert error.value.status == 400


def test_cursor_preserves_the_utc_ordering_key():
    import json

    identifier = uuid4()
    raw = json.dumps(["2026-09-08T15:00:00+03:00", str(identifier)]).encode()
    assert decode_cursor(base64.urlsafe_b64encode(raw).decode()) == (
        datetime(2026, 9, 8, 12, tzinfo=UTC),
        identifier,
    )
