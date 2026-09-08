"""
Error Sanitization Middleware (Phase 8 - API-04)

Catches unhandled exceptions, logs detailed traces with correlation IDs internally,
and masks internal paths, CPGQL errors, and stack traces from public responses.
"""

import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .correlation_middleware import get_current_correlation_id

logger = logging.getLogger("codebadger.api.errors")


class ErrorSanitizerMiddleware(BaseHTTPMiddleware):
    """ASGI Middleware masking internal diagnostics and stack traces in error responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            return await call_next(request)
        except Exception as exc:
            cid = getattr(request.state, "correlation_id", None) or get_current_correlation_id()
            logger.error(
                f"Unhandled exception during {request.method} {request.url.path} [correlation_id={cid}]: {exc}",
                exc_info=True,
            )
            return JSONResponse(
                {
                    "error": "Internal server error",
                    "correlation_id": cid,
                },
                status_code=500,
                headers={"X-Correlation-ID": cid},
            )
