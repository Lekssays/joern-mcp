# Tài Liệu Kỹ Thuật Phase 8: Authorization, Quotas & Security Architecture

Tài liệu giải thích kiến trúc và luồng xử lý kỹ thuật (technical flows) của Phase 8 trong CodeBadger: Xác thực (Authentication), Phân quyền Tenant (Multi-tenancy Authorization), Giới hạn tài nguyên (Quotas & Rate Limiting), Truy vết (Correlation Tracking), Ghi log kiểm toán (Structured Audit Logging) và Khử trùng lỗi (Error Sanitization).

---

## 1. Tổng quan Kiến trúc Middleware & Services

Tất cả request gửi tới CodeBadger REST API & MCP HTTP Transport đều đi qua pipeline phân tầng:

```
[ Incoming HTTP / MCP Request ]
               │
               ▼
┌────────────────────────────────────────┐
│ 1. ConcurrencyLimitMiddleware          │ ➔ Kiểm tra kết nối MCP đồng thời (tối đa 8)
└────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────┐
│ 2. RateLimitMiddleware                 │ ➔ Token Bucket: chặn flood IP/Tenant (HTTP 429)
└────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────┐
│ 3. AuthMiddleware                      │ ➔ Giải mã Bearer JWT, kiểm tra Tenant (HTTP 401)
└────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────┐
│ 4. CorrelationMiddleware               │ ➔ Sinh/chuyển tiếp X-Correlation-ID header
└────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────┐
│ 5. ErrorSanitizerMiddleware            │ ➔ Bắt exception, ẩn stack trace (HTTP 500)
└────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────┐
│ 6. REST Handlers / FastMCP Tools       │ ➔ Kiểm tra Quota (413/429), Tenant ownership (404)
└────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────┐
│ 7. Structured Audit Logger             │ ➔ Ghi JSON event với Correlation ID & Actor
└────────────────────────────────────────┘
```

---

## 2. Luồng Kỹ Thuật Chi Tiết (Detailed Technical Flows)

### Luồng 1: Xác thực người dùng và cấp phát Token (Authentication Flow)

```
Client                      /auth/login                  AuthService                  Postgres DB
  │                              │                            │                            │
  │── POST {username, password} ─>                            │                            │
  │                              │── authenticate_user() ────>│                            │
  │                              │                            │── SELECT FROM users ──────>│
  │                              │                            │<─ salt$pbkdf2_hash ────────│
  │                              │                            │                            │
  │                              │                            │ [PBKDF2-HMAC-SHA256        │
  │                              │                            │  100k rounds check]        │
  │                              │                            │                            │
  │                              │<── return User Entity ─────│                            │
  │                              │                            │                            │
  │                              │── create_access_token() ──>│                            │
  │                              │── create_refresh_token() ─>│                            │
  │                              │                            │ [Sign HMAC-SHA256 with     │
  │                              │                            │  JWT_SECRET_KEY]           │
  │                              │<── tokens {access, ref} ───│                            │
  │                              │                            │                            │
  │                              │── log_event(login_success) ─────────────────────────────┐
  │                              │                                                         ▼
  │<─ 200 OK {access_token, ...} ─                                               Audit Log Stream
```

1. **Mật khẩu an toàn**: Sử dụng thư viện chuẩn `hashlib.pbkdf2_hmac` với thuật toán SHA-256, chu kỳ 100,000 rounds và chuỗi salt ngẫu nhiên (`secrets.token_hex(16)`). So sánh bằng `hmac.compare_digest` để chống tấn công timing attack.
2. **Cấu trúc JWT**:
   - `sub`: User ID duy nhất (`usr_...`).
   - `tenant_id`: Định danh tổ chức / người sở hữu dữ liệu.
   - `roles`: Danh sách quyền (`["user"]` hoặc `["admin"]`).
   - `type`: `access` (hết hạn 60 phút) hoặc `refresh` (hết hạn 7 ngày).
3. **Quản trị người dùng**:
   - Bảng cơ sở dữ liệu `users` lưu thông tin tài khoản.
   - CLI seeding: `scripts/seed_admin.py --username ... --password ... --tenant-id ... --roles ...`.

---

### Luồng 2: Phân quyền Tenant & Cách ly dữ liệu (Tenancy Isolation Flow)

Mọi thao tác can thiệp tới Project, Version, Build và Context đều được cô lập theo `tenant_id`:

```
Client (Tenant A)            AuthMiddleware              REST Handler              ProjectVersionService
  │                                │                           │                             │
  │── GET /projects/{id} ─────────>│                           │                             │
  │   Authorization: Bearer <tok>  │── decode_token()          │                             │
  │                                │   Inject request.state    │                             │
  │                                │   .user = {tenant_a}      │                             │
  │                                │──────────────────────────>│                             │
  │                                                            │── get_project(id, scope) ──>│
  │                                                            │                             │
  │                                                            │   [SQL: WHERE id = %s       │
  │                                                            │    AND owner_scope = %s]    │
  │                                                            │                             │
  │                                                            │<─ None (Project belongs ────│
  │                                                            │   to Tenant B)              │
  │                                                            │                             │
  │<── 404 Not Found (Fail-closed: Không lộ thông tin) ────────│                             │
```

- **Nguyên tắc Fail-closed**: Nếu `tenant_id` trong JWT không trùng với `owner_scope` của dự án, hệ thống trả về HTTP `404 Not Found` (không trả về 403 Forbidden) để ngăn chặn kẻ tấn công dò quét sự tồn tại của tài nguyên ngoại vi.
- **Bypass dành cho Quản trị viên**: Người dùng có role `admin` được phép đọc và ghi trên mọi `owner_scope`.
- **Đồng bộ FastMCP**: Công cụ `version_context`, `version_get`, `project_list`... trong `src/tools/lifecycle_tools.py` đều nhận tham số `owner_scope` khớp với cơ chế REST.

---

### Luồng 3: Giới hạn tần suất & Chống cạn kiệt tài nguyên (Rate Limiting & Quotas)

#### A. Token Bucket Rate Limiting (`RateLimitMiddleware`)
- Mỗi Tenant hoặc IP client được gắn một Token Bucket in-memory.
- Mặc định cấp `RATE_LIMIT_PER_MINUTE = 120` token, hồi phục dần theo từng giây.
- Khi bucket hết token: Ngay lập tức trả về `HTTP 429 Too Many Requests` kèm header `Retry-After: <số giây cần đợi>`.
- Ngoại lệ (Exempt paths): `/health`, `/docs`, `/openapi.json` không bị throttle.

#### B. Giới hạn dung lượng tải lên (`MAX_PAYLOAD_SIZE_BYTES`)
- Khi client upload file nén qua `POST /projects/{id}/versions/archive`:
  1. Kiểm tra header `Content-Length`. Nếu vượt quá 50MB -> Trả về `HTTP 413 Payload Too Large`.
  2. Đọc luồng byte thực tế trong multipart stream. Nếu dung lượng thực tế vượt 50MB -> Trả về `HTTP 413`.

#### C. Giới hạn hàng đợi Build đồng thời (`MAX_CONCURRENT_BUILDS_PER_TENANT`)
- Khi client gọi `POST /versions/{id}/build`:
  1. Đếm số lượng version của tenant đang có trạng thái `queued`, `building`, hoặc `loading`.
  2. Nếu số lượng `>= 2` (ngưỡng cấu hình): Trả về `HTTP 429 Too Many Requests` kèm `Retry-After: 30`, ngăn cản một tenant chiếm dụng toàn bộ worker pool của Joern.

---

### Luồng 4: Truy vết và Kiểm toán (Correlation & Structured Audit Logging)

```
Incoming Request (X-Correlation-ID: optional)
                     │
                     ▼
       ┌───────────────────────────┐
       │   CorrelationMiddleware   │
       └───────────────────────────┘
                     │
                     ├─► Nếu có: chuyển tiếp ID
                     └─► Nếu thiếu: tự sinh UUID4 hex
                     │
                     ├─► Gán vào contextvars: correlation_id_ctx
                     ├─► Gán vào request.state.correlation_id
                     │
                     ▼
           [ Thực thi Request ]
                     │
                     ▼
       ┌───────────────────────────┐
       │       AuditLogger         │
       └───────────────────────────┘
                     │
                     ▼
{
  "timestamp": "2026-09-08T12:30:00.123456+00:00",
  "correlation_id": "c7a8b901...",
  "actor": "usr_9ad4e26a7eac",
  "tenant_id": "tenant-alpha",
  "action": "version.build",
  "resource_id": "5d27898bd82d8f99",
  "status_code": 202,
  "metadata": {}
}
                     │
                     ▼
       In ra logger "codebadger.audit" (stdout/file)
                     │
                     ▼
Response trả về kèm header: [ X-Correlation-ID: c7a8b901... ]
```

- Mọi thay đổi dữ liệu (Project create/delete, Version sync/create/archive/retry/cancel/build, Context read) đều được ghi nhận tự động.
- Chuỗi JSON có cấu trúc giúp hệ thống SIEM / Logstash / Datadog phân tích dễ dàng mà không làm lộ dữ liệu mật.

---

### Luồng 5: Khử trùng lỗi (Error Sanitization Flow)

```
Bất kỳ Unhandled Exception trong Controller / Service
                     │
                     ▼
       ┌───────────────────────────┐
       │ ErrorSanitizerMiddleware  │
       └───────────────────────────┘
                     │
                     ├─► Lấy correlation_id từ request.state
                     ├─► Ghi Log NỘI BỘ (Internal):
                     │     logger.error(stack_trace, exc_info=True)
                     │
                     ▼
        Trả về cho CLIENT (External Response):
        HTTP 500 Internal Server Error
        Headers: X-Correlation-ID: <cid>
        Body:
        {
          "error": "Internal server error",
          "correlation_id": "<cid>"
        }
```

- **Mục tiêu**: Tuyệt đối không để lộ đường dẫn tệp tin máy chủ (`/home/...`, `/opt/...`), chuỗi truy vấn CPGQL nội bộ, cấu trúc SQL hoặc stack trace của Python ra phản hồi bên ngoài.
- **Vận hành**: Quản trị viên chỉ cần lấy mã `correlation_id` từ phản hồi của người dùng và tra cứu trong file log nội bộ để tìm chính xác dòng code và stack trace bị lỗi.

---

## 3. Danh mục Tệp Mã Nguồn Phase 8

| Đường dẫn tệp | Vai trò / Trách nhiệm |
|---|---|
| `src/services/auth_service.py` | Băm mật khẩu PBKDF2, sinh & giải mã JWT token (HS256), phân quyền tenant. |
| `src/api/auth_middleware.py` | ASGI middleware bảo vệ endpoint bằng Bearer token, hỗ trợ fallback query param `?token=`. |
| `src/api/correlation_middleware.py` | Quản lý vòng đời `X-Correlation-ID` qua contextvars và response header. |
| `src/services/audit_logger.py` | Ghi log kiểm toán định dạng JSON cho mọi thao tác đột biến tài nguyên. |
| `src/api/rate_limiter.py` | Triển khai thuật toán Token Bucket rate limiter chống DoS. |
| `src/api/error_sanitizer.py` | Bọc exception toàn cục, ẩn thông tin nhạy cảm khỏi phản hồi HTTP 500. |
| `scripts/seed_admin.py` | Công cụ dòng lệnh (CLI) khởi tạo tài khoản quản trị viên / tenant ban đầu. |
| `tests/unit/services/test_auth_service.py` | Kiểm thử đơn vị cho thuật toán hashing, user seeding và JWT validation. |
| `tests/unit/api/test_auth_api.py` | Kiểm thử endpoint `/auth/login`, `/auth/refresh` và cách ly tenant trên REST. |
| `tests/unit/api/test_audit_logging.py` | Kiểm thử middleware tương quan và luồng ghi audit event. |
| `tests/unit/api/test_quotas_and_sanitization.py` | Kiểm thử rate limiting (429), quota build (429), payload size (413), error mask (500). |
| `tests/integration/test_security_parity.py` | Kiểm thử tích hợp E2E toàn diện tính đồng nhất bảo mật giữa REST và FastMCP. |
