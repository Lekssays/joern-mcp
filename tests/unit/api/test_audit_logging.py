import json
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from src.api.auth_middleware import AuthMiddleware
from src.api.correlation_middleware import CorrelationMiddleware, get_current_correlation_id
from src.api.rest_routes import register_rest_routes
from src.services.audit_logger import AuditLogger
from src.services.auth_service import AuthService
from src.services.project_version_service import ProjectVersionService
from src.utils.postgres_db_manager import PostgresDBManager


def test_correlation_middleware_propagation():
    app = Starlette()

    async def ping(request):
        cid = get_current_correlation_id()
        return JSONResponse({"correlation_id": cid})

    app.add_route("/ping", ping)

    app.add_middleware(CorrelationMiddleware)
    client = TestClient(app)

    # 1. Custom correlation ID propagated
    custom_cid = "custom-uuid-1234-abcd"
    resp = client.get("/ping", headers={"X-Correlation-ID": custom_cid})
    assert resp.status_code == 200
    assert resp.headers["X-Correlation-ID"] == custom_cid
    assert resp.json()["correlation_id"] == custom_cid

    # 2. Auto-generated when absent
    resp2 = client.get("/ping")
    assert resp2.status_code == 200
    assert "X-Correlation-ID" in resp2.headers
    assert len(resp2.headers["X-Correlation-ID"]) > 0
    assert resp2.json()["correlation_id"] == resp2.headers["X-Correlation-ID"]


def test_audit_logger_direct():
    audit_logger = AuditLogger(in_memory_buffer=True)
    event = audit_logger.log_event(
        action="project.create",
        resource_id="proj_123",
        status_code=201,
        actor="usr_alice",
        tenant_id="tenant_x",
        correlation_id="cid_999",
        metadata={"extra": "data"},
    )
    assert event["action"] == "project.create"
    assert event["resource_id"] == "proj_123"
    assert event["status_code"] == 201
    assert event["actor"] == "usr_alice"
    assert event["tenant_id"] == "tenant_x"
    assert event["correlation_id"] == "cid_999"
    assert event["metadata"] == {"extra": "data"}
    assert "timestamp" in event
    assert len(audit_logger.events) == 1


def test_audit_logging_with_api(tmp_path):
    db_file = tmp_path / "test_audit.db"
    db = PostgresDBManager(f"sqlite:///{db_file}")
    db.init_schema()

    version_service = ProjectVersionService(db)
    auth_service = AuthService(db=db, secret_key="test-audit-key")
    audit_logger = AuditLogger(in_memory_buffer=True)

    auth_service.seed_user("alice", "alicePass", tenant_id="tenant-acme", roles=["user"])
    token = auth_service.create_access_token("usr_alice_id", "tenant-acme", ["user"])

    services = {
        "version_service": version_service,
        "auth_service": auth_service,
        "audit_logger": audit_logger,
        "db_manager": db,
    }

    app = Starlette()
    register_rest_routes(app, services)

    # Wrap with middlewares
    app.add_middleware(AuthMiddleware, auth_service=auth_service)
    app.add_middleware(CorrelationMiddleware)

    client = TestClient(app)

    # Issue project create
    cid = "corr-id-test-777"
    resp = client.post(
        "/projects",
        json={"remote_url": "https://github.com/acme/project.git"},
        headers={"Authorization": f"Bearer {token}", "X-Correlation-ID": cid},
    )
    assert resp.status_code == 201
    proj_id = resp.json()["id"]

    # Verify audit event was captured
    events = [e for e in audit_logger.events if e["action"] == "project.create"]
    assert len(events) == 1
    ev = events[0]
    assert ev["resource_id"] == proj_id
    assert ev["actor"] == "usr_alice_id"
    assert ev["tenant_id"] == "tenant-acme"
    assert ev["correlation_id"] == cid
    assert ev["status_code"] == 201
