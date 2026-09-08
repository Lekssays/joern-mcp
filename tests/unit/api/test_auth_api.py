import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from src.api.auth_middleware import AuthMiddleware
from src.api.rest_routes import register_rest_routes
from src.services.auth_service import AuthService
from src.services.project_version_service import ProjectVersionService
from src.utils.postgres_db_manager import PostgresDBManager


@pytest.fixture
def api_env(tmp_path):
    db_file = tmp_path / "test_auth.db"
    db = PostgresDBManager(f"sqlite:///{db_file}")
    db.init_schema()
    version_service = ProjectVersionService(db)
    auth_service = AuthService(db=db, secret_key="test-api-secret")

    # Seed users
    auth_service.seed_user("admin_user", "adminPass", tenant_id="tenant-admin", roles=["admin"])
    auth_service.seed_user("alice", "alicePass", tenant_id="tenant-a", roles=["user"])
    auth_service.seed_user("bob", "bobPass", tenant_id="tenant-b", roles=["user"])

    services = {
        "version_service": version_service,
        "auth_service": auth_service,
        "db_manager": db,
        "archive_service": None,
        "git_sync_service": None,
        "cpg_queue": None,
    }

    app = Starlette()
    register_rest_routes(app, services)

    # Add dummy /health route for testing whitelist
    async def dummy_health(request):
        return JSONResponse({"status": "up"})

    app.add_route("/health", dummy_health, methods=["GET"])

    # Wrap with AuthMiddleware
    app.add_middleware(AuthMiddleware, auth_service=auth_service)
    client = TestClient(app)

    return client, auth_service, version_service


def test_public_endpoints_whitelist(api_env):
    client, _, _ = api_env
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "up"}


def test_protected_endpoint_missing_token(api_env):
    client, _, _ = api_env
    resp = client.get("/projects")
    assert resp.status_code == 401
    assert "Missing authorization token" in resp.json()["error"]


def test_protected_endpoint_invalid_token(api_env):
    client, _, _ = api_env
    resp = client.get("/projects", headers={"Authorization": "Bearer invalid.token.here"})
    assert resp.status_code == 401
    assert "Invalid or expired token" in resp.json()["error"]


def test_auth_login_and_refresh_flow(api_env):
    client, auth_service, _ = api_env

    # Bad login
    bad_resp = client.post("/auth/login", json={"username": "alice", "password": "wrongPassword"})
    assert bad_resp.status_code == 401

    # Good login
    login_resp = client.post("/auth/login", json={"username": "alice", "password": "alicePass"})
    assert login_resp.status_code == 200
    data = login_resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "Bearer"
    assert data["tenant_id"] == "tenant-a"

    access_token = data["access_token"]
    refresh_token = data["refresh_token"]

    # Use access token on protected endpoint
    resp = client.get("/projects", headers={"Authorization": f"Bearer {access_token}"})
    assert resp.status_code == 200

    # Query param token fallback (e.g. for SSE)
    resp_query = client.get(f"/projects?token={access_token}")
    assert resp_query.status_code == 200

    # Refresh token flow
    refresh_resp = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh_resp.status_code == 200
    new_data = refresh_resp.json()
    assert "access_token" in new_data

    # Bad refresh token
    bad_ref = client.post("/auth/refresh", json={"refresh_token": "invalid_refresh"})
    assert bad_ref.status_code == 401


def test_cross_tenant_isolation_on_projects(api_env):
    client, auth_service, _ = api_env

    alice_token = auth_service.create_access_token("usr_alice", "tenant-a", ["user"])
    bob_token = auth_service.create_access_token("usr_bob", "tenant-b", ["user"])
    admin_token = auth_service.create_access_token("usr_admin", "tenant-admin", ["admin"])

    # Alice creates a project
    create_resp = client.post(
        "/projects",
        json={"remote_url": "https://github.com/tenant-a/repo.git"},
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    # Alice can fetch her project
    alice_get = client.get(f"/projects/{proj_id}", headers={"Authorization": f"Bearer {alice_token}"})
    assert alice_get.status_code == 200

    # Bob tries to fetch Alice's project -> 404 fail-closed
    bob_get = client.get(f"/projects/{proj_id}", headers={"Authorization": f"Bearer {bob_token}"})
    assert bob_get.status_code == 404

    # Bob tries to delete Alice's project -> 404 fail-closed
    bob_del = client.delete(f"/projects/{proj_id}", headers={"Authorization": f"Bearer {bob_token}"})
    assert bob_del.status_code == 404

    # Admin can access Alice's project
    admin_get = client.get(f"/projects/{proj_id}", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_get.status_code == 200
