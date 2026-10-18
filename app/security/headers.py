"""Security headers and request body size enforcement middleware."""

from typing import Optional
from starlette import status
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

MAX_REQUEST_BODY_SIZE_BYTES = 25 * 1024 * 1024  # 25 MB

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
}


class SecurityHeadersAndBodySizeMiddleware:
    """
    ASGI middleware that:
    1. Enforces HTTP security headers on all responses:
       - X-Content-Type-Options: nosniff
       - X-Frame-Options: DENY
       - Referrer-Policy: strict-origin-when-cross-origin
    2. Rejects request bodies exceeding 25 MB with HTTP 413 Payload Too Large.
    """

    def __init__(self, app: ASGIApp, max_body_size: int = MAX_REQUEST_BODY_SIZE_BYTES):
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def custom_send(message):
            if message.get("type") == "http.response.start":
                raw_headers = list(message.get("headers", []))
                # Filter out existing security headers to prevent duplicates
                raw_headers = [
                    h for h in raw_headers
                    if h[0].lower() not in (
                        b"x-content-type-options",
                        b"x-frame-options",
                        b"referrer-policy",
                    )
                ]
                raw_headers.append((b"x-content-type-options", b"nosniff"))
                raw_headers.append((b"x-frame-options", b"DENY"))
                raw_headers.append((b"referrer-policy", b"strict-origin-when-cross-origin"))
                message["headers"] = raw_headers
            await send(message)

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                if int(content_length) > self.max_body_size:
                    response = JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={"detail": "Request body exceeds 25 MB limit"},
                        headers=SECURITY_HEADERS,
                    )
                    await response(scope, receive, custom_send)
                    return
            except (ValueError, TypeError):
                pass

        bytes_received = 0

        async def custom_receive():
            nonlocal bytes_received
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                bytes_received += len(body)
                if bytes_received > self.max_body_size:
                    response = JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={"detail": "Request body exceeds 25 MB limit"},
                        headers=SECURITY_HEADERS,
                    )
                    await response(scope, receive, custom_send)
                    return
            return message

        await self.app(scope, custom_receive, custom_send)
