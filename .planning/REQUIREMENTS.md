# Requirements: CodeBadger v0.7 Codebase Context Backend

**Defined:** 2026-08-09
**Core Value:** AI agents can obtain bounded, cited, source-backed context from an immutable codebase version through a stable backend contract.

## v1 Requirements

### Ingestion & Catalog

- [ ] **INGEST-01**: An authenticated client can register a GitHub, GitLab, or Azure DevOps remote plus selected branch and explicitly synchronize it without waiting for CPG generation.
- [ ] **INGEST-02**: The system creates an immutable project version from the resolved commit SHA with content digest, manifest summary, language/build configuration, and lifecycle timestamps.
- [ ] **INGEST-03**: The system validates provider URL and branch, uses Git CLI only in an isolated workspace, keeps encrypted credentials out of URLs/config/logs/responses, and returns the existing version when the resolved commit/config is unchanged.

### CPG Lifecycle

- [ ] **CPG-01**: A version can enqueue exactly one durable CPG build using the existing Postgres queue and Joern worker pool.
- [ ] **CPG-02**: Clients can observe stable queued/building/loading/ready/failed/cancelled states with phase, queue position, elapsed time, retry count, and sanitized errors.
- [ ] **CPG-03**: Failed builds can be retried idempotently, cancellable work cleans partial artifacts, and startup reconciliation repairs interrupted jobs.
- [ ] **CPG-04**: Equivalent source content and build options reuse the existing content-addressed CPG cache without mutating a ready version.

### Backend API

- [ ] **API-01**: REST endpoints support project creation, archive upload, version listing/detail, build/status, and deletion.
- [ ] **API-02**: MCP lifecycle tools call the same application services and return IDs/status schemas compatible with REST.
- [x] **API-03**: Authentication, project/version authorization, and an audit record protect every public lifecycle and context operation.
- [x] **API-04**: Upload/build/context operations enforce quotas, queue backpressure, correlation IDs, metrics, and sanitized operator diagnostics.

### Agent Context

- [ ] **CTX-01**: A ready version produces an index of symbols, files, and source spans suitable for retrieval.
- [ ] **CTX-02**: Context retrieval combines exact symbol resolution, lexical search, and bounded Joern graph expansion with ranking and deduplication.
- [ ] **CTX-03**: Retrieval enforces item/byte/token/node/time budgets and explicitly reports truncation.
- [ ] **CTX-04**: Every context response includes project/version identity, immutable digest, relative file path, 1-based line range, symbol when known, and selection reason.
- [ ] **CTX-05**: Raw CPGQL remains restricted to an administrative/internal interface; public context operations expose only validated parameters.

## v2 Requirements

- **RETR-01**: Embedding/vector retrieval and reranking for large repositories.
- **ISOL-01**: Full multi-tenant worker sandbox with per-tenant storage isolation and quotas.
- **DIFF-01**: Version-to-version context and change-impact comparison.
- **OPS-01**: Kubernetes or multi-host scheduling and automated deployment pipeline.

## Out of Scope

| Feature | Reason |
|---------|--------|
| General code hosting, browsing UI, or collaboration workflows | v0.7 is an analysis/context backend, not a repository product. |
| Archive upload as the primary sync mechanism | Continuously changing codebases are synchronized from their configured Git branch. |
| Public unrestricted CPGQL | Joern's Scala execution surface is not a security boundary. |
| Embedding-first vector database | Prove explainable lexical + graph retrieval first. |
| Kubernetes/multi-host orchestration | Requires a separate infrastructure milestone. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INGEST-01 | Phase 5 | Pending |
| INGEST-02 | Phase 5 | Pending |
| INGEST-03 | Phase 5 | Pending |
| CPG-01 | Phase 6 | Pending |
| CPG-02 | Phase 6 | Pending |
| CPG-03 | Phase 6 | Pending |
| CPG-04 | Phase 6 | Pending |
| API-01 | Phase 6 | Pending |
| API-02 | Phase 6 | Pending |
| API-03 | Phase 8 | Satisfied |
| API-04 | Phase 8 | Satisfied |
| CTX-01 | Phase 7 | Pending |
| CTX-02 | Phase 7 | Pending |
| CTX-03 | Phase 7 | Pending |
| CTX-04 | Phase 7 | Pending |
| CTX-05 | Phase 7 | Pending |

**Coverage:** 16 v1 requirements; 16 mapped; 0 unmapped ✓.

---
*Requirements defined: 2026-08-09*
*Last updated: 2026-08-09 after v0.7 requirements approval*
