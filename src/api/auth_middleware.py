"""
Authentication Middleware (Phase 8 - API-03)

ASGI Starlette middleware enforcing JWT Bearer token authentication
and tenant context extraction across CodeBadger REST & MCP endpoints.

Separation of Concerns:
- MCP endpoints (/mcp, /sse, /messages): accept 'mcp' (permanent) or 'access' tokens.
- REST endpoints (/projects, /versions, etc.): require 'access' tokens with standard expiration.
"""

import logging
from typing import Optional, Set
import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

DEFAULT_PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/openapi.json",
    "/auth/login",
    "/auth/refresh",
    "/auth/mcp-token",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """ASGI Middleware verifying Bearer JWT tokens and injecting tenant identity."""

    def __init__(
        self,
        app,
        auth_service=None,
        public_paths: Optional[Set[str]] = None,
    ):
        super().__init__(app)
        if auth_service is None:
            from ..services.auth_service import AuthService
            auth_service = AuthService()
        self.auth_service = auth_service
        self.public_paths = public_paths or DEFAULT_PUBLIC_PATHS

    def _is_public(self, path: str) -> bool:
        if path in self.public_paths:
            return True
        if path.startswith("/docs") or path.startswith("/openapi.json"):
            return True
        return False

    def _is_mcp_request(self, path: str) -> bool:
        """Check if request targets FastMCP transport routes."""
        return (
            path == "/mcp"
            or path.startswith("/mcp/")
            or path == "/sse"
            or path.startswith("/sse/")
            or path == "/messages"
            or path.startswith("/messages/")
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if self._is_public(path):
            return await call_next(request)

        # Extract token from Authorization header or query parameter fallback (e.g. SSE)
        token = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        elif "token" in request.query_params:
            token = request.query_params["token"]
        elif "access_token" in request.query_params:
            token = request.query_params["access_token"]

        if not token:
            return JSONResponse(
                {"error": "Missing authorization token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            # Differentiate allowed token types by route
            if self._is_mcp_request(path):
                # MCP endpoints accept permanent 'mcp' tokens or short-lived 'access' tokens
                payload = self.auth_service.decode_token(token, allowed_types=["mcp", "access"])
            else:
                # REST endpoints require standard short-lived 'access' tokens
                payload = self.auth_service.decode_token(token, expected_type="access")
        except jwt.ExpiredSignatureError:
            return JSONResponse(
                {"error": "Token has expired"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        except Exception as e:
            logger.debug(f"JWT authentication failed: {e}")
            return JSONResponse(
                {"error": "Invalid or expired token"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Set user context in request scope and state
        request.scope["user"] = payload
        request.state.user = payload

        return await call_next(request)
