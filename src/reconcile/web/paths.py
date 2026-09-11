"""API resource paths shared by routing and the pre-body boundary."""

from reconcile.analysis.models import AnalysisMode

ANALYSES_PATH = "/api/v1/analyses"
RUNS_PATH = "/api/v1/runs"
FINDINGS_PATH = "/api/v1/findings"
WORKFLOW_PATH = "/api/v1/workflow"
MULTIPART_PATHS = frozenset(
    {
        "/api/v1/reconcile",
        *(f"{prefix}/{mode}" for prefix in (ANALYSES_PATH, RUNS_PATH) for mode in AnalysisMode),
    }
)
