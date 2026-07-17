"""Network and authentication boundary for Ingress and companion integration."""

from __future__ import annotations

import secrets

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_TRUSTED_CLIENTS = frozenset({"127.0.0.1", "::1", "172.30.32.2"})


class AppAccessMiddleware:
    """Allow Ingress, local health checks, and bearer-authenticated API clients."""

    def __init__(self, app: ASGIApp, auth_token: str) -> None:
        self.app = app
        self.auth_token = auth_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            client = scope.get("client")
            if client is None or client[0] not in _TRUSTED_CLIENTS:
                path = str(scope.get("path", ""))
                if path.startswith("/api/") and self._has_valid_token(scope):
                    await self.app(scope, receive, send)
                    return
                is_api = path.startswith("/api/")
                response = JSONResponse(
                    status_code=401 if is_api else 403,
                    content={
                        "error": {
                            "code": "authentication_required" if is_api else "ingress_required",
                            "message": (
                                "Provide the integration bearer token."
                                if is_api
                                else "Access this application through Home Assistant Ingress."
                            ),
                        }
                    },
                    headers={"WWW-Authenticate": "Bearer"} if is_api else None,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)

    def _has_valid_token(self, scope: Scope) -> bool:
        headers = {name.lower(): value for name, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        scheme, separator, supplied = authorization.partition(" ")
        return (
            bool(separator)
            and scheme.casefold() == "bearer"
            and secrets.compare_digest(supplied, self.auth_token)
        )
