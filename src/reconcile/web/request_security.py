"""Header-only authorization, correlation, and safe operational request logging."""

import json
import logging
from time import perf_counter
from uuid import uuid4

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from reconcile.auth.service_errors import AuthError
from reconcile.web.auth import require_analysis
from reconcile.web.paths import MULTIPART_PATHS

REQUEST_ID_HEADER = "X-Request-ID"
_ACCESS_LOGGER = logging.getLogger("reconcile.access")


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


class OperationalLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = perf_counter()
        status = 500
        response_size = 0

        async def measured_send(message):
            nonlocal status, response_size
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                response_size += len(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, receive, measured_send)
        finally:
            route = scope.get("route")
            template = getattr(route, "path_format", None) or getattr(route, "path", None)
            if not isinstance(template, str) or not template.startswith("/"):
                template = "unmatched"
            event = {
                "event": "http_request",
                "request_id": str(scope.get("state", {}).get("request_id", "unavailable")),
                "method": scope["method"],
                "route": template,
                "status": status,
                "elapsed_ms": round((perf_counter() - started) * 1000, 3),
                "response_size": response_size,
            }
            _ACCESS_LOGGER.info(json.dumps(event, separators=(",", ":"), sort_keys=True))


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
