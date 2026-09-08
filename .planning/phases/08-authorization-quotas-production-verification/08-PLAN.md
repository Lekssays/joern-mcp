# Phase 8: Authorization, Quotas & Production Verification — Execution Plan

**Phase:** 08
**Milestone:** v0.7 Codebase Context Backend
**Requirements Covered:** API-03, API-04

---

## Plan Overview

- **08-01-PLAN (Task 1): JWT Authentication, User Seeding & Tenancy Service**
  - Implement `src/services/auth_service.py` with:
    - Secret key loaded from `JWT_SECRET_KEY` environment variable.
    - Password hashing & verification with salt via standard library `hashlib.pbkdf2_hmac`.
    - User storage / seeding mechanism (e.g. `seed_admin_user(username, password)` CLI script `scripts/seed_admin.py`).
    - JWT signing and verification using `PyJWT` (HS256).
    - Access token (short-lived, 1h) and Refresh token (long-lived, 7d).
    - Claims schema: `{"sub": user_id, "tenant_id": tenant_id, "roles": ["user"|"admin"], "exp": ..., "iat": ...}`.
    - Tenant ownership enforcement logic: `authorize_project(user_ctx, project_id) -> bool` (returns 404 fail-closed if tenant mismatch, unless admin).
  - Add unit tests: `tests/unit/services/test_auth_service.py`.

- **08-02-PLAN (Task 2): Auth Middleware & Route/MCP Protection (API-03)**
  - Implement Starlette ASGI middleware / auth dependency in `src/api/auth_middleware.py`:
    - Reads `Authorization: Bearer <token>` or query parameter fallback for SSE connections.
    - Whitelist public endpoints: `/health`, `/docs`, `/openapi.json`, `/auth/login`, `/auth/refresh`.
    - Returns 401 Unauthorized for missing/invalid/expired token.
  - Implement `/auth/login` and `/auth/refresh` endpoints in `src/api/rest_routes.py`.
  - Wire tenancy validation into existing REST routes:
    - `/projects/{id}`: GET/DELETE
    - `/projects/{id}/versions`: GET/POST
    - `/versions/{id}`: GET/DELETE
    - `/versions/{id}/build`: POST
    - `/versions/{id}/context`: GET
  - Wire tenancy checks into FastMCP tools (`src/tools/mcp_tools.py` & core tools).
  - Add unit tests: `tests/unit/api/test_auth_api.py`.

- **08-03-PLAN (Task 3): Correlation Tracking & Structured Audit Logging (API-04)**
  - Implement Correlation Middleware:
    - Propagates or generates `X-Correlation-ID` header using `uuid.uuid4()`.
    - Sets contextvar `correlation_id` for downstream logging.
  - Implement `src/services/audit_logger.py`:
    - Structured JSON audit logging outputting:
      `{"timestamp": "...", "correlation_id": "...", "actor": "...", "tenant_id": "...", "action": "...", "resource_id": "...", "status_code": ...}`
    - Audit hooks attached to mutations (`POST /versions`, `POST /build`, `POST /cancel`, `DELETE /versions`, `GET /context`).
  - Add unit tests: `tests/unit/api/test_audit_logging.py`.

- **08-04-PLAN (Task 4): Rate Limiting, Backpressure Quotas & Error Sanitization (API-04)**
  - In-memory Token Bucket rate limiter middleware (`src/api/rate_limiter.py`):
    - Configurable requests per minute per IP / tenant.
    - Returns HTTP 429 Too Many Requests with `Retry-After: <seconds>`.
  - Build queue backpressure guard:
    - Check active queued/building jobs per tenant/project against configured threshold (e.g., max 2 concurrent builds per tenant).
    - Rejects with HTTP 429 when quota exceeded.
  - Payload size check:
    - Enforce max upload bytes on archive/git payload (HTTP 413 Payload Too Large).
  - Error sanitization:
    - Global exception handler masking stack traces, raw CPGQL traces, internal filesystem paths in HTTP responses.
  - Add unit tests: `tests/unit/api/test_quotas_and_sanitization.py`.

- **08-05-PLAN (Task 5): End-to-End & Security Parity Verification**
  - Cross-tenant isolation verification test (Tenant A token cannot access Tenant B project/version/context -> 404 fail-closed).
  - Quota and backpressure verification tests (rate limit triggers 429, payload limit triggers 413).
  - REST & MCP parity test verifying unauthorized/forbidden responses match expectations.
  - Test suite: `tests/integration/test_security_parity.py`.
