"""Optional HTTP Basic auth for public deployments. Pure ASGI so SSE responses stream unbuffered."""

import base64
import binascii
import secrets

from starlette.types import ASGIApp, Receive, Scope, Send

PUBLIC_PATHS = frozenset({"/api/health"})  # platform health checks must not need credentials


class BasicAuthMiddleware:
    def __init__(self, app: ASGIApp, *, username: str, password: str) -> None:
        self.app = app
        self.username = username.encode()
        self.password = password.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in PUBLIC_PATHS or self._authorised(scope):
            await self.app(scope, receive, send)
            return
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"www-authenticate", b'Basic realm="Multi-Agent Platform", charset="UTF-8"'),
                    (b"content-type", b"text/plain; charset=utf-8"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": b"Authentication required"})

    def _authorised(self, scope: Scope) -> bool:
        header = dict(scope["headers"]).get(b"authorization", b"")
        scheme, _, encoded = header.partition(b" ")
        if scheme.lower() != b"basic":
            return False
        try:
            username, _, password = base64.b64decode(encoded, validate=True).partition(b":")
        except (binascii.Error, ValueError):
            return False
        return secrets.compare_digest(username, self.username) and secrets.compare_digest(
            password, self.password
        )
