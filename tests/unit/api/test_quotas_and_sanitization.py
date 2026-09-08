import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from src.api.auth_middleware import AuthMiddleware
from src.api.error_sanitizer import ErrorSanitizerMiddleware
from src.api.rate_limiter import RateLimitMiddleware, TokenBucket
from src.api.rest_routes import register_rest_routes
from src.services.auth_service import AuthService
from src.services.project_version_service import ProjectVersionService
from src.utils.postgres_db_manager import PostgresDBManager


def test_token_bucket_direct():
    bucket = TokenBucket(capacity=2, fill_rate=1.0)
    allowed, _ = bucket.consume(1.0)
    assert allowed is True
    allowed, _ = bucket.consume(1.0)
    assert allowed is True
    # Bucket exhausted
    allowed, retry_after = bucket.consume(1.0)
    assert allowed is False
    assert retry_after >= 1


def test_rate_limiting_middleware():
    app = Starlette()

    async def ping(request):
        return JSONResponse({"msg": "pong"})

    app.add_route("/ping", ping, methods=["GET"])
    app.add_route("/health", ping, methods=["GET"])

    # Limit to 3 requests per minute for quick testing
    app.add_middleware(RateLimitMiddleware, rate_limit_per_minute=3)
    client = TestClient(app)

    # First 3 should pass
    for _ in range(3):
        resp = client.get("/ping")
        assert resp.status_code == 200

    # 4th request must be throttled
    throttled = client.get("/ping")
    assert throttled.status_code == 429
    assert "Too Many Requests" in throttled.json()["error"]
    assert "Retry-After" in throttled.headers

    # Exempt path /health is NOT throttled
    health_resp = client.get("/health")
    assert health_resp.status_code == 200


def test_error_sanitizer_middleware():
    app = Starlette()

    async def buggy_endpoint(request):
        raise RuntimeError("Secret DB connection string leaked at /home/secret/path/db.sqlite")

    app.add_route("/crash", buggy_endpoint, methods=["GET"])
    app.add_middleware(ErrorSanitizerMiddleware)
    client = TestClient(app)

    resp = client.get("/crash")
    assert resp.status_code == 500
    data = resp.json()
    assert data["error"] == "Internal server error"
    assert "correlation_id" in data
    # Sensitive details must NOT be present in body
    raw_text = resp.text
    assert "/home/secret" not in raw_text
    assert "RuntimeError" not in raw_text
    assert "db.sqlite" not in raw_text


def test_payload_size_limit(tmp_path, monkeypatch):
    import src.api.rest_routes as rr
    monkeypatch.setattr(rr, "MAX_PAYLOAD_SIZE_BYTES", 100)  # 100 bytes limit

    db_file = tmp_path / "test_payload.db"
    db = PostgresDBManager(f"sqlite:///{db_file}")
    db.init_schema()

    version_service = ProjectVersionService(db)
    archive_service = type("MockArchiveService", (), {})()
    services = {
        "version_service": version_service,
        "archive_service": archive_service,
    }

    app = Starlette()
    register_rest_routes(app, services)
    client = TestClient(app)

    # Register project
    p = version_service.register_project("https://github.com/org/repo.git")

    # Upload file of 200 bytes (> 100 bytes)
    big_data = b"x" * 200
    files = {"file": ("repo.zip", big_data, "application/zip")}
    resp = client.post(f"/projects/{p.id}/versions/archive", files=files)
    assert resp.status_code == 413
    assert "Payload too large" in resp.json()["error"]


def test_queue_concurrency_quota(tmp_path, monkeypatch):
    import src.api.rest_routes as rr
    monkeypatch.setattr(rr, "MAX_CONCURRENT_BUILDS_PER_TENANT", 2)

    db_file = tmp_path / "test_quota.db"
    db = PostgresDBManager(f"sqlite:///{db_file}")
    db.init_schema()

    version_service = ProjectVersionService(db)
    auth_service = AuthService(db=db, secret_key="test-quota-secret")

    class MockQueue:
        def enqueue(self, item): pass

    services = {
        "version_service": version_service,
        "auth_service": auth_service,
        "cpg_queue": MockQueue(),
        "db_manager": db,
    }

    app = Starlette()
    register_rest_routes(app, services)
    app.add_middleware(AuthMiddleware, auth_service=auth_service)
    client = TestClient(app)

    # Create users
    auth_service.seed_user("alice", "pass", tenant_id="tenant-acme", roles=["user"])
    auth_service.seed_user("admin", "pass", tenant_id="admin-tenant", roles=["admin"])

    alice_token = auth_service.create_access_token("usr_a", "tenant-acme", ["user"])
    admin_token = auth_service.create_access_token("usr_adm", "admin-tenant", ["admin"])

    # Alice creates a project
    p = version_service.register_project("https://github.com/acme/project.git", owner_scope="tenant-acme")

    # Create 2 versions in 'building' status
    v1, _ = version_service.create_or_get_version(p.id, "1"*40, "main", "d1", owner_scope="tenant-acme")
    db.update_version_status(v1.id, "building")

    v2, _ = version_service.create_or_get_version(p.id, "2"*40, "main", "d2", owner_scope="tenant-acme")
    db.update_version_status(v2.id, "queued")

    # Create 3rd version and try to dispatch build
    v3, _ = version_service.create_or_get_version(p.id, "3"*40, "main", "d3", owner_scope="tenant-acme")

    # Alice build request -> 429 quota exceeded
    resp = client.post(
        f"/versions/{v3.id}/build",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert resp.status_code == 429
    assert "quota exceeded" in resp.json()["error"]

    # Admin build request bypasses quota
    db.update_version_status(v3.id, "failed")
    adm_resp = client.post(
        f"/versions/{v3.id}/build",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert adm_resp.status_code == 202
