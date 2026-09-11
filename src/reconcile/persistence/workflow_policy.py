"""Limits and allowed transitions for the non-financial finding overlay."""

WORKFLOW_TEXT_LIMIT = 4000
EVENT_METADATA_LIMIT = 2048
WORKFLOW_PAGE_SIZE = 25
WORKFLOW_PAGE_MAX = 100
WORKFLOW_FIELDS = frozenset({"assignee_user_id", "due_at", "reminder_at"})
TRANSITIONS = {
    "OPEN": frozenset({"IN_REVIEW", "RESOLVED"}),
    "IN_REVIEW": frozenset({"RESOLVED"}),
    "RESOLVED": frozenset({"OPEN"}),
}
