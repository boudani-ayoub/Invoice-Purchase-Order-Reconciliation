"""Isolate accepted upload/report tests; auth integration uses the real security boundary."""

from types import SimpleNamespace

from reconcile.web.app import create_app
from reconcile.web.auth import require_analysis
from reconcile.web.request_security import AnalysisGateMiddleware


def create_analysis_test_app(**kwargs):
    app = create_app(auth=SimpleNamespace(settings=SimpleNamespace(docs_enabled=True)), **kwargs)
    app.dependency_overrides[require_analysis] = lambda: None
    app.user_middleware = [m for m in app.user_middleware if m.cls is not AnalysisGateMiddleware]
    return app
