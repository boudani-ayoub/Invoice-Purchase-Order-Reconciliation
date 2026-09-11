import pytest

pytest.importorskip("sqlalchemy")
from pydantic import ValidationError

from reconcile.web.workflow import CommentInput, TransitionInput, WorkflowInput


@pytest.mark.parametrize("value", ["", " \n\t", "bad\x00text", "\ud800", "x" * 4001])
@pytest.mark.parametrize("kind", ["comment", "resolution"])
def test_workflow_text_rejects_unsafe_or_empty_values(value, kind):
    with pytest.raises(ValidationError):
        if kind == "comment":
            CommentInput(text=value)
        else:
            TransitionInput(expected_version=1, target_status="RESOLVED", resolution_note=value)


def test_plain_text_is_trimmed_not_interpreted():
    markup = '<img src=x onerror="alert(1)"> é 🧾'
    assert CommentInput(text=f" {markup}\n").text == markup
    assert CommentInput(text="🧾" * 4000).text == "🧾" * 4000


@pytest.mark.parametrize("extra", ["actor_user_id", "organization_id", "request_id", "status"])
def test_workflow_bodies_forbid_mass_assignment(extra):
    with pytest.raises(ValidationError):
        WorkflowInput.model_validate({"expected_version": 1, "due_at": None, extra: "injected"})
    with pytest.raises(ValidationError):
        CommentInput.model_validate({"text": "Hello", extra: "injected"})


@pytest.mark.parametrize("version", [0, -1, "1", True, 1.2])
def test_version_must_be_positive_strict_integer(version):
    with pytest.raises(ValidationError):
        WorkflowInput(expected_version=version, due_at=None)


@pytest.mark.parametrize("date", ["2026-01-01", "2026-01-01T01:00:00", 12345, "Infinity"])
def test_schedule_requires_aware_timestamp(date):
    with pytest.raises(ValidationError):
        WorkflowInput(expected_version=1, due_at=date)


def test_schedule_normalizes_offsets_and_preserves_explicit_null():
    fields = WorkflowInput(expected_version=1, due_at="2026-01-01T03:00:00+03:00")
    assert fields.due_at.isoformat() == "2026-01-01T00:00:00+00:00"
    assert WorkflowInput(expected_version=1, due_at=None).model_fields_set == {
        "expected_version",
        "due_at",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"expected_version": 1, "target_status": "RESOLVED"},
        {"expected_version": 1, "target_status": "OPEN", "resolution_note": "Not resolving"},
        {"expected_version": 1, "target_status": "APPROVED"},
    ],
)
def test_invalid_transition_contract(payload):
    with pytest.raises(ValidationError):
        TransitionInput.model_validate(payload)


def test_empty_workflow_patch_rejected():
    with pytest.raises(ValidationError):
        WorkflowInput(expected_version=1)


@pytest.mark.parametrize("value", ["9999-12-31T23:59:59-23:00", "0001-01-01T00:00:00+23:00"])
def test_timestamp_conversion_cannot_overflow_utc(value):
    with pytest.raises(ValidationError):
        WorkflowInput(expected_version=1, due_at=value)
