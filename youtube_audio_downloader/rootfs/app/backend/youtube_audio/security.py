"""Network boundary for the Home Assistant Ingress-only application."""

from __future__ import annotations

from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_TRUSTED_CLIENTS = frozenset({"127.0.0.1", "::1", "172.30.32.2"})


class IngressOnlyMiddleware:
    """Reject HTTP traffic that did not arrive from Ingress or local health checks."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            client = scope.get("client")
            if client is None or client[0] not in _TRUSTED_CLIENTS:
                response = JSONResponse(
                    status_code=403,
                    content={
                        "error": {
                            "code": "ingress_required",
                            "message": "Access this application through Home Assistant Ingress.",
                        }
                    },
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
