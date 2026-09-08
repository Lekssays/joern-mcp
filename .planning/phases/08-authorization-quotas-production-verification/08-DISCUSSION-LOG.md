# Phase 8: Authorization, Quotas & Production Verification - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md & 08-AI-SPEC.md — this log preserves the alternatives considered.

**Date:** 2026-09-08
**Phase:** 8-Authorization, Quotas & Production Verification
**Areas discussed:** Authentication mechanism, Audit logging, Quotas & Backpressure, REST/MCP Parity

---

## 1. Authentication & Tenancy Model (API-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Static API Key Map / DB | API Key mapping to tenant ID in env or DB. | |
| JWT Login & Refresh Token | Auth endpoints (/auth/login, /auth/refresh) issuing JWT access & refresh tokens with PyJWT. | ✓ |

**User's choice:** JWT Login & Refresh Token.
**Notes:** Users/agents authenticate via username/password, obtain JWT Bearer tokens with expiration & refresh rotation. Protected endpoints inspect  and enforce tenant isolation.

---

## 2. Audit Logging & Correlation Tracking (API-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Structured JSON to stdout with Correlation ID | Injects/propagates , logs structured JSON events for mutations and context queries. | ✓ |
| Dedicated Audit Table in DB | Writes full audit log rows to PostgreSQL. | |

**Decision:** Structured JSON to stdout with Correlation ID. Zero DB bloat, log-aggregator friendly, standard container pattern.

---

## 3. Rate Limiting & Queue Backpressure (API-04)

| Option | Description | Selected |
|--------|-------------|----------|
| In-memory Token Bucket + DB Queue Concurrency Check | Token bucket middleware for HTTP rate limit (429) + Postgres queue active build check per project. Max payload size check (413). | ✓ |
| Full Redis Token Bucket | All throttling and concurrency handled exclusively in Redis. | |

**Decision:** In-memory Token Bucket + DB Queue Concurrency Check. Fast, no external network overhead on every HTTP request, leverages existing PostgresJobStore.

---

## 4. REST & MCP Security Parity

| Option | Description | Selected |
|--------|-------------|----------|
| Shared SecurityService | Decoupled auth/authz context validator used identically by Starlette middleware and MCP tool handlers. | ✓ |

**Decision:** Shared SecurityService. Guarantees fail-closed parity across protocols.
