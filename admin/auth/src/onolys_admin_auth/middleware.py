"""Pure ASGI middleware. Never logs the token or the email."""

import json
import logging

from onolys_admin_auth.config import AdminAuthConfig
from onolys_admin_auth.verifier import IdTokenVerifier, InvalidToken, UpstreamUnavailable

log = logging.getLogger("onolys_admin_auth")


class AdminAuthMiddleware:
    def __init__(self, app, config: AdminAuthConfig, verifier=None) -> None:
        if config.enabled and not config.allowed_emails:
            raise ValueError("allowlist is empty: refusing to start with auth on")
        self.app = app
        self.config = config
        self.verifier = verifier or (IdTokenVerifier(config.project) if config.enabled else None)

    async def __call__(self, scope, receive, send):
        if not self.config.enabled or scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 1008})
        # Preflight is answered by the CORS layer; it carries no credentials.
        if scope["method"] == "OPTIONS":
            return await self.app(scope, receive, send)
        token = _bearer(scope)
        if token is None:
            return await self._deny(send, 401, "unauthenticated", "Authentication required.")
        try:
            claims = self.verifier.verify(token)
        except InvalidToken:
            log.info("admin auth denied: invalid token")
            return await self._deny(send, 401, "unauthenticated", "Authentication required.")
        except UpstreamUnavailable:
            log.warning("admin auth: signing keys unavailable")
            return await self._deny(
                send, 503, "upstream_unavailable", "Service temporarily unavailable."
            )
        email = claims.get("email")
        if claims.get("email_verified") is not True or not isinstance(email, str) or not email:
            log.info("admin auth denied: email not verified")
            return await self._deny(send, 403, "forbidden", "Not allowed.")
        if email.strip().lower() not in self.config.allowed_emails:
            log.info("admin auth denied: not on allowlist")
            return await self._deny(send, 403, "forbidden", "Not allowed.")
        await self.app(scope, receive, send)

    @staticmethod
    async def _deny(send, status: int, code: str, message: str) -> None:
        body = json.dumps({"error": {"code": code, "message": message}}).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]
        if status == 401:
            headers.append((b"www-authenticate", b"Bearer"))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})


def _bearer(scope) -> str | None:
    for k, v in scope["headers"]:
        if k == b"authorization":
            parts = v.decode("latin-1").split(None, 1)
            if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
                return parts[1].strip()
            return None
    return None
