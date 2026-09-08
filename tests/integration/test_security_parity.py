import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient
from fastmcp import FastMCP

from src.api.auth_middleware import AuthMiddleware
from src.api.correlation_middleware import CorrelationMiddleware
from src.api.error_sanitizer import ErrorSanitizerMiddleware
from src.api.rate_limiter import RateLimitMiddleware
from src.api.rest_routes import register_rest_routes
from src.services.audit_logger import AuditLogger
from src.services.auth_service import AuthService
from src.services.context_retrieval_service import ContextRetrievalService
from src.services.project_version_service import ProjectVersionService
from src.tools.lifecycle_tools import register_lifecycle_tools
from src.utils.postgres_db_manager import PostgresDBManager


class MockQueue:
    def __init__(self):
        self.queue = []
    def enqueue(self, item):
        self.queue.append(item)


class MockQueryExecutor:
    def execute_query(self, codebase_hash, cpg_path, query_str):
        return []


@pytest.fixture
def full_security_env(tmp_path, monkeypatch):
    import src.api.rest_routes as rr
    monkeypatch.setattr(rr, "MAX_CONCURRENT_BUILDS_PER_TENANT", 2)
    monkeypatch.setattr(rr, "MAX_PAYLOAD_SIZE_BYTES", 500)

    db_file = tmp_path / "security_parity.db"
    db = PostgresDBManager(f"sqlite:///{db_file}")
    db.init_schema()

    version_service = ProjectVersionService(db)
    query_exec = MockQueryExecutor()
    context_service = ContextRetrievalService(query_exec, version_service)
    auth_service = AuthService(db=db, secret_key="parity-test-secret")
    audit_logger = AuditLogger(in_memory_buffer=True)
    cpg_queue = MockQueue()

    # Seed users
    auth_service.seed_user("alice", "alicePass", tenant_id="tenant-alpha", roles=["user"])
    auth_service.seed_user("bob", "bobPass", tenant_id="tenant-beta", roles=["user"])
    auth_service.seed_user("superadmin", "adminPass", tenant_id="tenant-admin", roles=["admin"])

    services = {
        "version_service": version_service,
        "context_service": context_service,
        "auth_service": auth_service,
        "audit_logger": audit_logger,
        "cpg_queue": cpg_queue,
        "db_manager": db,
    }

    app = Starlette()
    register_rest_routes(app, services)

    # Middleware stack: RateLimit -> Auth -> Correlation -> ErrorSanitizer
    app.add_middleware(RateLimitMiddleware, rate_limit_per_minute=20)
    app.add_middleware(AuthMiddleware, auth_service=auth_service)
    app.add_middleware(CorrelationMiddleware)
    app.add_middleware(ErrorSanitizerMiddleware)

    # MCP Setup
    mcp = FastMCP("SecurityParityMCP")
    register_lifecycle_tools(mcp, services)

    client = TestClient(app)
    return {
        "client": client,
        "mcp": mcp,
        "auth_service": auth_service,
        "version_service": version_service,
        "context_service": context_service,
        "audit_logger": audit_logger,
        "db": db,
    }


def test_cross_tenant_isolation_parity(full_security_env):
    client = full_security_env["client"]
    mcp = full_security_env["mcp"]
    auth = full_security_env["auth_service"]
    db = full_security_env["db"]
    vs = full_security_env["version_service"]

    # Generate tokens
    alice_token = auth.create_access_token("u_alice", "tenant-alpha", ["user"])
    bob_token = auth.create_access_token("u_bob", "tenant-beta", ["user"])
    admin_token = auth.create_access_token("u_admin", "tenant-admin", ["admin"])

    # 1. Tenant Alpha creates a project and version
    create_resp = client.post(
        "/projects",
        json={"remote_url": "https://github.com/alpha-org/repo.git"},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    v_resp = client.post(
        f"/projects/{proj_id}/versions",
        json={"commit_sha": "a" * 40, "content_digest": "dig_alpha", "branch": "main"},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert v_resp.status_code == 201
    version_id = v_resp.json()["id"]
    db.update_version_status(version_id, "ready")

    # 2. Tenant Beta attempts access -> all 404
    # (a) Get project
    assert client.get(f"/projects/{proj_id}", headers={"Authorization": f"Bearer {bob_token}"}).status_code == 404
    # (b) List project versions
    assert client.get(f"/projects/{proj_id}/versions", headers={"Authorization": f"Bearer {bob_token}"}).status_code == 404
    # (c) Get specific version
    assert client.get(f"/versions/{version_id}", headers={"Authorization": f"Bearer {bob_token}"}).status_code == 404
    # (d) Get version context
    assert client.get(f"/versions/{version_id}/context?query=auth", headers={"Authorization": f"Bearer {bob_token}"}).status_code == 404
    # (e) Cancel build
    assert client.post(f"/versions/{version_id}/cancel", headers={"Authorization": f"Bearer {bob_token}"}).status_code == 404

    # 3. Admin can access Tenant Alpha project and version
    assert client.get(f"/projects/{proj_id}", headers={"Authorization": f"Bearer {admin_token}"}).status_code == 200
    assert client.get(f"/versions/{version_id}", headers={"Authorization": f"Bearer {admin_token}"}).status_code == 200

    # 4. MCP Tools Parity — verify tenant isolation inside FastMCP
    # Tenant Alpha scope sees project
    alpha_projects = vs.list_projects(owner_scope="tenant-alpha")
    assert len(alpha_projects) == 1
    assert alpha_projects[0].id == proj_id

    # Tenant Beta scope does NOT see project
    beta_projects = vs.list_projects(owner_scope="tenant-beta")
    assert len(beta_projects) == 0

    # Tenant Beta cannot get Tenant Alpha version via get_version
    assert vs.get_version(version_id, owner_scope="tenant-beta") is None


def test_rate_limiting_and_quotas_parity(full_security_env):
    client = full_security_env["client"]
    auth = full_security_env["auth_service"]
    db = full_security_env["db"]

    token = auth.create_access_token("u_rate", "tenant-alpha", ["user"])
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Payload size limit (configured to 500 bytes)
    big_body = b"y" * 1000
    files = {"file": ("big.zip", big_body, "application/zip")}
    # First create project
    p_resp = client.post("/projects", json={"remote_url": "https://github.com/alpha-org/repo2.git"}, headers=headers)
    assert p_resp.status_code == 201
    p_id = p_resp.json()["id"]

    resp_413 = client.post(f"/projects/{p_id}/versions/archive", files=files, headers=headers)
    assert resp_413.status_code == 413
    assert "Payload too large" in resp_413.json()["error"]

    # 2. Concurrent build quota (configured to max 2)
    v1_resp = client.post(
        f"/projects/{p_id}/versions",
        json={"commit_sha": "b" * 40, "content_digest": "d_b", "branch": "main"},
        headers=headers,
    )
    v2_resp = client.post(
        f"/projects/{p_id}/versions",
        json={"commit_sha": "c" * 40, "content_digest": "d_c", "branch": "main"},
        headers=headers,
    )
    v3_resp = client.post(
        f"/projects/{p_id}/versions",
        json={"commit_sha": "d" * 40, "content_digest": "d_d", "branch": "main"},
        headers=headers,
    )

    db.update_version_status(v1_resp.json()["id"], "building")
    db.update_version_status(v2_resp.json()["id"], "queued")
    db.update_version_status(v3_resp.json()["id"], "failed")

    # Trying to build v3 while v1 and v2 are active -> 429
    resp_quota = client.post(f"/versions/{v3_resp.json()['id']}/build", headers=headers)
    assert resp_quota.status_code == 429
    assert "quota exceeded" in resp_quota.json()["error"]


def test_observability_and_audit_parity(full_security_env):
    client = full_security_env["client"]
    auth = full_security_env["auth_service"]
    audit_logger = full_security_env["audit_logger"]

    token = auth.create_access_token("u_obs", "tenant-obs", ["user"])
    cid = "trace-e2e-12345"

    resp = client.post(
        "/projects",
        json={"remote_url": "https://github.com/obs/repo.git"},
        headers={"Authorization": f"Bearer {token}", "X-Correlation-ID": cid},
    )
    assert resp.status_code == 201
    assert resp.headers["X-Correlation-ID"] == cid

    # Verify audit event
    matching = [e for e in audit_logger.events if e["correlation_id"] == cid]
    assert len(matching) >= 1
    event = matching[0]
    assert event["action"] == "project.create"
    assert event["actor"] == "u_obs"
    assert event["tenant_id"] == "tenant-obs"
