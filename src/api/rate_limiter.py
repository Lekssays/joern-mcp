"""
Rate Limiting Middleware (Phase 8 - API-04)

In-memory Token Bucket rate limiter per tenant / client IP.
Returns HTTP 429 Too Many Requests with Retry-After header when exhausted.
"""

import math
import time
from typing import Dict, Optional, Set, Tuple
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ..config import RATE_LIMIT_PER_MINUTE

DEFAULT_EXEMPT_PATHS = {
    "/health",
    "/docs",
    "/openapi.json",
}


class TokenBucket:
    def __init__(self, capacity: int, fill_rate: float):
        self.capacity = float(capacity)
        self.fill_rate = float(fill_rate)  # tokens per second
        self.tokens = float(capacity)
        self.last_update = time.monotonic()

    def consume(self, amount: float = 1.0) -> Tuple[bool, int]:
        """Attempt to consume tokens. Returns (success, retry_after_seconds)."""
        now = time.monotonic()
        elapsed = now - self.last_update
        self.last_update = now

        # Replenish
        self.tokens = min(self.capacity, self.tokens + elapsed * self.fill_rate)

        if self.tokens >= amount:
            self.tokens -= amount
            return True, 0

        # Calculate wait time
        needed = amount - self.tokens
        retry_after = max(1, math.ceil(needed / self.fill_rate)) if self.fill_rate > 0 else 60
        return False, retry_after


class RateLimitMiddleware(BaseHTTPMiddleware):
    """ASGI Token Bucket Rate Limiter per tenant / client IP."""

    def __init__(
        self,
        app,
        rate_limit_per_minute: int = RATE_LIMIT_PER_MINUTE,
        exempt_paths: Optional[Set[str]] = None,
    ):
        super().__init__(app)
        self.capacity = rate_limit_per_minute
        self.fill_rate = rate_limit_per_minute / 60.0
        self.exempt_paths = exempt_paths or DEFAULT_EXEMPT_PATHS
        self._buckets: Dict[str, TokenBucket] = {}

    def _get_key(self, request: Request) -> str:
        # Check tenant identity from auth middleware if available
        user = getattr(request.state, "user", None) or request.scope.get("user")
        if user and user.get("tenant_id"):
            return f"tenant:{user['tenant_id']}"

        # Fallback to client IP
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            ip = forwarded.split(",")[0].strip()
            return f"ip:{ip}"
        client = request.client
        ip = client.host if client else "unknown"
        return f"ip:{ip}"

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path in self.exempt_paths or path.startswith("/docs") or path.startswith("/openapi.json"):
            return await call_next(request)

        key = self._get_key(request)
        if key not in self._buckets:
            self._buckets[key] = TokenBucket(capacity=self.capacity, fill_rate=self.fill_rate)

        bucket = self._buckets[key]
        allowed, retry_after = bucket.consume(1.0)
        if not allowed:
            return JSONResponse(
                {"error": "Too Many Requests", "retry_after": retry_after},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
