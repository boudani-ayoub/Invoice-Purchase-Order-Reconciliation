"""Keep driver error details out of ASGI server tracebacks."""

import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_LOGGER = logging.getLogger(__name__)


class SafeErrorsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False
        completed = False

        async def track_send(message):
            nonlocal started, completed
            if message["type"] == "http.response.start":
                started = True
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                completed = True
            await send(message)

        try:
            await self.app(scope, receive, track_send)
        except Exception as error:
            _LOGGER.error(
                "Unhandled reconciliation API error (%s), request_id=%s",
                type(error).__name__,
                scope.get("state", {}).get("request_id"),
            )
            if not started:
                await JSONResponse(
                    status_code=500,
                    content={"error": "internal_error", "message": "Internal server error."},
                    headers={"Cache-Control": "no-store"},
                )(scope, receive, send)
            elif not completed:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
