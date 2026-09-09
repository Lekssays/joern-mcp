# Milestone Summary: v0.7 Codebase Context Backend

**Phiên bản:** v0.7 Codebase Context Backend  
**Ngày hoàn thành:** 2026-09-08  
**Trạng thái kiểm thử:** 130/130 tests PASSED (0 failures, 0 regressions)  
**Tài liệu kỹ thuật bổ trợ:** `docs/phase-8-architecture-and-flows.md`, `.planning/v0.7-MILESTONE-AUDIT.md`

---

## 1. Tổng quan Dự án (Executive Overview)

Milestone **v0.7** đã chuyển đổi hoàn toàn CodeBadger từ một máy chủ phân tích Joern tĩnh cục bộ thành một **Codebase Context Backend** chuẩn doanh nghiệp dành cho AI Agents. Hệ thống cho phép agent tương tác với các phiên bản mã nguồn bất biến (immutable versions), tra cứu ngữ cảnh mã nguồn chính xác theo dòng/hàm (cited hybrid context), đồng thời được bảo vệ bởi lớp bảo mật phân quyền tenant, giới hạn tài nguyên và kiểm toán toàn diện.

---

## 2. Các Tính Năng Mới Đã Xây Dựng (Key Features Built)

### A. Phase 5: Secure Ingestion & Version Catalog (Nạp mã nguồn an toàn & Danh mục phiên bản)
1. **Đồng bộ kho mã nguồn Git đa nền tảng (`INGEST-01`, `INGEST-03`)**:
   - Hỗ trợ kết nối và đồng bộ từ GitHub, GitLab, Azure DevOps.
   - Thao tác Git thực hiện hoàn toàn trong workspace cô lập, ngăn chặn command injection.
   - Quản lý thông tin xác thực (token/key) qua adapter mã hóa AES-GCM (`CredentialEncryptionAdapter`), không bao giờ để lộ token trong URL, log hay cấu hình Git.
2. **Phiên bản mã nguồn bất biến (`INGEST-02`)**:
   - Mỗi commit SHA kết hợp cấu hình build tạo ra một `version_id` duy nhất và bất biến (immutable version).
   - Tạo mã băm nội dung (`content_digest`) và lưu trữ manifest tóm tắt cấu trúc thư mục.
   - Cơ chế tự động khử trùng lặp (deduplication): Nếu branch không có commit mới, hệ thống trả về phiên bản hiện có thay vì tạo bản ghi rác.
3. **Tải lên mã nguồn dạng nén an toàn (`ArchiveUploadService`)**:
   - Cho phép nạp mã nguồn qua tệp `.zip` và `.tar.gz`.
   - Cơ chế bảo vệ chống Zip-Slip (path traversal) và Zip Bomb (giới hạn dung lượng bung nén & số lượng tệp tin).

---

### B. Phase 6: Durable CPG Lifecycle & Backend Contract (Hàng đợi CPG bền vững & Hợp đồng API)
1. **Hàng đợi sinh CPG bền vững (`CPG-01`, `CPG-02`)**:
   - Tích hợp vòng đời phiên bản vào hàng đợi bền bỉ (Durable CPG Queue) trên PostgreSQL/SQLite.
   - Quản lý trạng thái vòng đời chuẩn xác: `queued` ➔ `building` ➔ `loading` ➔ `ready` (hoặc `failed` / `cancelled`).
   - Cung cấp siêu dữ liệu chi tiết: `queue_position`, `elapsed_ms`, `queue_time_ms`, `cpg_size_bytes`, `peak_memory_mb`.
2. **Khôi phục và tự phục hồi khi có sự cố (`CPG-03`, `CPG-04`)**:
   - Hỗ trợ thử lại (`retry`) an toàn, có tính lũy thừa (idempotent).
   - Hủy bỏ (`cancel`) tiến trình đang build và dọn dẹp triệt để các tệp CPG sinh dở dang.
   - Cơ chế khởi động lại tự động hòa giải (startup reconciliation): Quét và chuyển các job bị đứt gãy do restart server sang hàng đợi xử lý tiếp.
   - Tái sử dụng CPG cache đã lưu nếu mã nguồn có cùng content digest.
3. **Đồng nhất hợp đồng REST và FastMCP (`API-01`, `API-02`)**:
   - Cung cấp đầy đủ REST endpoints chuẩn OpenAPI 3.1.0 (Swagger UI tại `/docs`).
   - Cung cấp bộ công cụ FastMCP Tools tương đương (`project_create`, `project_list`, `project_delete`, `version_sync`, `version_list`, `version_get`, `version_retry`, `version_cancel`).

---

### C. Phase 7: Cited Hybrid Context Retrieval (Truy xuất ngữ cảnh lai kèm trích dẫn)
1. **Truy xuất ngữ cảnh kết hợp (Hybrid Retrieval - `CTX-01`, `CTX-02`)**:
   - Tích hợp bộ máy giải quyết ký hiệu chính xác (exact symbol resolution) trên đồ thị CPG của Joern.
   - Kết hợp tìm kiếm cấu trúc mã nguồn (methods, callers, call hierarchy).
2. **Ngân sách tài nguyên & Trích dẫn nguồn minh bạch (`CTX-03`, `CTX-04`)**:
   - Thực thi nghiêm ngặt ngân sách token/byte/item (`max_items`, `max_bytes`), tự động gắn cờ `truncated` khi vượt quá giới hạn.
   - Mỗi mẩu ngữ cảnh trả về cho AI Agent đều đi kèm trích dẫn chi tiết: `version_id`, `relative_file_path`, khoảng dòng bắt đầu và kết thúc (`lineNumber`, `lineNumberEnd`), chữ ký hàm (`signature`) và lý do lựa chọn.
3. **An toàn bảo mật CPGQL (`CTX-05`)**:
   - Đóng cổng CPGQL thô đối với người dùng công khai. Chỉ mở các tham số truy vấn ngữ cảnh an toàn đã được kiểm định kiểu dữ liệu.

---

### D. Phase 8: Authorization, Quotas & Production Verification (Xác thực, Hạn ngạch & Bảo mật)
1. **Xác thực JWT & Phân quyền Tenant (`API-03`)**:
   - Hệ thống xác thực bằng JSON Web Token (PyJWT HS256) với Access Token (1h) và Refresh Token (7d).
   - Băm mật khẩu an toàn theo chuẩn `PBKDF2-HMAC-SHA256` (100,000 vòng lặp) kèm chuỗi salt ngẫu nhiên.
   - Cơ chế phân quyền nhiều tổ chức (Multi-tenant isolation) theo nguyên tắc **Fail-closed (HTTP 404)**: Client từ Tenant B tuyệt đối không thể đọc hay can thiệp vào Project/Version của Tenant A (tránh việc dò quét dữ liệu).
   - Cung cấp CLI khởi tạo tài khoản quản trị: `scripts/seed_admin.py`.
2. **Giới hạn tốc độ & Ngăn chặn DoS (`API-04`)**:
   - Middleware Token Bucket rate limiter per-tenant/IP (`HTTP 429 Too Many Requests` kèm header `Retry-After`).
   - Hạn ngạch hàng đợi: Giới hạn tối đa 2 tác vụ build đồng thời cho mỗi tenant (`MAX_CONCURRENT_BUILDS_PER_TENANT = 2`).
   - Hạn ngạch kích thước tải lên: Giới hạn file nén tối đa 50MB (`HTTP 413 Payload Too Large`).
3. **Truy vết và Ghi log kiểm toán có cấu trúc (`API-04`)**:
   - `CorrelationMiddleware` tự động sinh hoặc chuyển tiếp header `X-Correlation-ID` xuyên suốt các service và trả về trong response.
   - `AuditLogger` xuất bản nhật ký kiểm toán định dạng JSON có cấu trúc cho toàn bộ các thao tác tạo/sửa/xóa và truy xuất ngữ cảnh.
4. **Khử trùng lỗi (Error Sanitization - `API-04`)**:
   - Bọc exception toàn cục, ẩn toàn bộ stack trace, đường dẫn máy chủ cục bộ và lỗi cơ sở dữ liệu khỏi người dùng ngoài. Trả về mã lỗi chung kèm `correlation_id` để tra cứu trong log nội bộ.

---

## 3. Kiến trúc Tổng thể Hệ thống v0.7

```
                     [ AI Agents & HTTP Clients ]
                                  │
                                  ▼
 ┌─────────────────────────────────────────────────────────────────┐
 │                   Security & Middleware Pipeline                │
 │  • ConcurrencyLimit (Max 8 MCP)                                 │
 │  • RateLimitMiddleware (Token Bucket -> 429)                    │
 │  • AuthMiddleware (Bearer JWT / ?token= -> 401)                 │
 │  • CorrelationMiddleware (X-Correlation-ID)                     │
 │  • ErrorSanitizerMiddleware (Mask stack traces -> 500)          │
 └────────────────────────────────┬────────────────────────────────┘
                                  │
          ┌───────────────────────┴───────────────────────┐
          ▼                                               ▼
┌──────────────────┐                            ┌───────────────────┐
│ REST API Routes  │                            │ FastMCP Tools     │
│ (/projects,      │                            │ (project_*,       │
│  /versions,      │                            │  version_*)       │
│  /auth/*, etc.)  │                            │                   │
└─────────┬────────┘                            └─────────┬─────────┘
          │                                               │
          └───────────────────────┬───────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                        Core Services                             │
│  • AuthService & Tenancy Enforcement                             │
│  • GitSyncService & ArchiveUploadService                         │
│  • ProjectVersionService (Immutable Catalog)                     │
│  • ContextRetrievalService (Exact Symbols & Bounded Graph)       │
│  • AuditLogger (Structured JSON logs)                            │
└─────────────────────────────────┬────────────────────────────────┘
                                  │
          ┌───────────────────────┴───────────────────────┐
          ▼                                               ▼
┌──────────────────────────────────┐   ┌───────────────────────────┐
│ Database (Postgres / SQLite)     │   │ Joern Worker Pool & CPGs  │
│ • projects & project_versions    │   │ • Durable CPG Queue       │
│ • users & credentials (AES-GCM)  │   │ • Content-addressed cache │
│ • codebases & findings           │   │ • Bounded Query Executor  │
└──────────────────────────────────┘   └───────────────────────────┘
```

---

## 4. Bảng Tra cứu Yêu cầu (Requirements Traceability - 16/16)

| Mã yêu cầu | Nhóm | Trạng thái | Minh chứng kiểm thử |
|---|---|---|---|
| **INGEST-01** | Ingestion | Đạt | `tests/test_git_sync.py` |
| **INGEST-02** | Catalog | Đạt | `tests/test_project_version_contract.py` |
| **INGEST-03** | Security | Đạt | `tests/test_archive_upload_service.py` |
| **CPG-01** | CPG Queue | Đạt | `tests/test_version_lifecycle_recovery.py` |
| **CPG-02** | Observability | Đạt | `tests/test_backend_contract_parity.py` |
| **CPG-03** | Recovery | Đạt | `tests/test_version_lifecycle_recovery.py` |
| **CPG-04** | Caching | Đạt | `tests/test_archive_upload_service.py` |
| **API-01** | REST Surface | Đạt | `tests/test_backend_contract_parity.py` |
| **API-02** | MCP Parity | Đạt | `tests/test_backend_contract_parity.py` |
| **API-03** | Auth & Audit | Đạt | `tests/unit/api/test_auth_api.py`, `tests/integration/test_security_parity.py` |
| **API-04** | Quotas & Errors | Đạt | `tests/unit/api/test_quotas_and_sanitization.py`, `tests/unit/api/test_audit_logging.py` |
| **CTX-01** | Symbol Index | Đạt | `tests/test_code_browsing_tools.py` |
| **CTX-02** | Hybrid Search | Đạt | `tests/unit/api/test_context_api.py` |
| **CTX-03** | Budgets | Đạt | `tests/unit/api/test_context_api.py` |
| **CTX-04** | Citations | Đạt | `tests/unit/api/test_context_api.py` |
| **CTX-05** | Safe Context | Đạt | `tests/unit/api/test_context_api.py` |

---

## 5. Hướng dẫn Dành cho Người mới Bắt đầu (Getting Started)

1. **Khởi chạy môi trường máy chủ**:
   ```bash
   ./scripts/deploy.sh up
   ```
2. **Khởi tạo tài khoản quản trị viên**:
   ```bash
   .venv/bin/python scripts/seed_admin.py --username admin --password secretpassword --tenant-id default --roles admin
   ```
3. **Đăng nhập lấy Access Token**:
   ```bash
   curl -X POST http://localhost:4242/auth/login \
     -H "Content-Type: application/json" \
     -d '{"username": "admin", "password": "secretpassword"}'
   ```
4. **Đăng ký dự án Git & đồng bộ phiên bản**:
   ```bash
   curl -X POST http://localhost:4242/projects \
     -H "Authorization: Bearer <TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"remote_url": "https://github.com/my-org/my-repo.git", "default_branch": "main"}'
   ```
5. **Tra cứu tài liệu API**:
   - Truy cập giao diện Swagger UI: `http://localhost:4242/docs`
   - Kiểm tra sức khỏe hệ thống: `http://localhost:4242/health`
