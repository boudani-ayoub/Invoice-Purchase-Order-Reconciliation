"""Bound small authentication JSON requests before parsing or hashing."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from reconcile.auth.config import AUTH_PATH
from reconcile.web.paths import MULTIPART_PATHS, RUNS_PATH

AUTH_BODY_LIMIT = 16 * 1024


class AuthBodyLimitMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] not in {"POST", "PATCH"}
            or not scope["path"].startswith((f"{AUTH_PATH}/", f"{RUNS_PATH}/"))
            or scope["path"].rstrip("/") in MULTIPART_PATHS
        ):
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > AUTH_BODY_LIMIT:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error": "request_too_large",
                        "message": "Request is too large.",
                    },
                    headers={"Cache-Control": "no-store"},
                )
                await response(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
