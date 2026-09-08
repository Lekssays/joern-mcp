"""
Correlation ID Middleware (Phase 8 - API-04)

Extracts or generates X-Correlation-ID for each request,
sets contextvar for structured logging, and injects X-Correlation-ID into response headers.
"""

import contextvars
import uuid
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

correlation_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


def get_current_correlation_id() -> str:
    """Return the correlation ID for the current async task context."""
    cid = correlation_id_ctx.get()
    return cid or str(uuid.uuid4())


class CorrelationMiddleware(BaseHTTPMiddleware):
    """ASGI Middleware to trace requests across services via X-Correlation-ID."""

    async def dispatch(self, request: Request, call_next) -> Response:
        cid = request.headers.get("X-Correlation-ID") or request.headers.get("x-correlation-id")
        if not cid:
            cid = uuid.uuid4().hex

        token = correlation_id_ctx.set(cid)
        request.scope["correlation_id"] = cid
        request.state.correlation_id = cid

        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = cid
            return response
        finally:
            correlation_id_ctx.reset(token)
