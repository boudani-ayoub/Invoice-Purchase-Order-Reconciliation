"""Header-only upload authorization and server-owned request correlation."""

from uuid import uuid4

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from reconcile.auth.service_errors import AuthError
from reconcile.web.auth import require_analysis
from reconcile.web.paths import MULTIPART_PATHS

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4()
        scope.setdefault("state", {})["request_id"] = request_id

        async def identified_send(message):
            if message["type"] == "http.response.start":
                message["headers"].append(
                    (REQUEST_ID_HEADER.lower().encode(), str(request_id).encode())
                )
            await send(message)

        await self.app(scope, receive, identified_send)


class AnalysisGateMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] == "POST"
            and scope["path"].rstrip("/") in MULTIPART_PATHS
        ):
            try:
                await run_in_threadpool(require_analysis, Request(scope))
            except AuthError as error:
                await JSONResponse(
                    {"error": error.code, "message": error.message},
                    status_code=error.status,
                    headers={"Cache-Control": "no-store"},
                )(scope, receive, send)
                return
        await self.app(scope, receive, send)
