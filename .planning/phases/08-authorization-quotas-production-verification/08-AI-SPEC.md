# AI-SPEC — Phase 8: Authorization, Quotas & Production Verification

> AI design contract generated for Phase 8. Consumed by planner and implementation.

---

## 1. System Classification

**System Type:** Security, JWT authentication, tenant authorization, rate-limiting, and operational observability infrastructure for CodeBadger backend APIs (REST and MCP).

**Description:**
Phase 8 introduces JWT-based authentication (/auth/login, /auth/refresh), tenant isolation on projects/versions, resource quotas, structured audit trails, and correlation IDs across all public REST endpoints and MCP tools. Ensures agents and users cannot bypass project permissions, exhaust backend resources via DoS/bursts, or leak sensitive diagnostic information.

**Critical Failure Modes:**
1. Cross-project authorization leak (e.g., Tenant A accessing or querying CPG context of Tenant B's version).
2. Unauthenticated or unvalidated MCP tool execution bypassing REST-level security.
3. Resource exhaustion (unbounded upload sizes, unrestricted queue spamming, token bucket exhaustion).
4. Information disclosure in error responses (stack traces, internal paths, raw CPGQL traces).
5. Missing correlation IDs or un-audited sensitive lifecycle events.

---

## 2. Architecture & Decisions

### 1. Authentication & Tenancy Model (API-03)
- **Endpoints**:
  - `POST /auth/login`: verifies credentials, returns access_token, refresh_token, token_type: Bearer, expires_in.
  - `POST /auth/refresh`: validates refresh token, returns new access_token.
- **JWT Tokens**:
  - Signed with HMAC-SHA256 via PyJWT.
  - Claims: sub (user_id), tenant_id, roles (admin / tenant), iat, exp.
- **Authorization**:
  - All `/projects`, `/versions`, `/cpg`, `/context` endpoints require `Authorization: Bearer <token>`.
  - Tenancy check: User/Tenant can only access projects owned by their tenant_id (or if role is admin). Non-matching returns 404/403 fail-closed.
  - Public bypass: `/health`, `/docs`, `/openapi.json`, `/auth/login`, `/auth/refresh`.

### 2. Audit Logging & Correlation Tracking (API-04)
- **Correlation ID**:
  - Injected or propagated via `X-Correlation-ID` header.
  - Contextvar for request lifecycle.
- **Audit Logs**:
  - Structured JSON logs printed to stdout/logger for mutations, build dispatches, and context access:
    timestamp, correlation_id, actor, tenant_id, action, resource, status.

### 3. Rate Limiting & Queue Backpressure (API-04)
- **Token Bucket Rate Limiter**:
  - Per-tenant / per-IP token bucket in memory.
  - Exceeding limit returns HTTP 429 Too Many Requests with Retry-After header.
- **Queue Concurrency Quota**:
  - Check active queued/building jobs per project/tenant in PostgresJobStore before enqueuing new build.
  - Limit exceeded returns HTTP 429 with error message explaining queue quota.
- **Payload Size Limits**:
  - Reject archives/payloads exceeding configured byte threshold with HTTP 413 Payload Too Large.

### 4. Error Sanitization & Diagnostics (API-04)
- Public error responses contain sanitized error messages and correlation_id.
- Strips stack traces, internal filesystem paths, and database details.
