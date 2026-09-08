import os
import tempfile
import time
from datetime import timedelta
import pytest
import jwt

from src.services.auth_service import AuthService, hash_password, verify_password
from src.utils.postgres_db_manager import PostgresDBManager


def test_password_hashing():
    pwd = "superSecretPassword123"
    hashed = hash_password(pwd)
    assert "$" in hashed
    assert verify_password(pwd, hashed) is True
    assert verify_password("wrongPassword", hashed) is False
    assert verify_password("", hashed) is False
    assert verify_password(pwd, "") is False


def test_auth_service_in_memory():
    auth = AuthService(secret_key="test-secret")
    user = auth.seed_user("alice", "alicePass", tenant_id="tenant-a", roles=["user"])
    assert user["username"] == "alice"
    assert user["tenant_id"] == "tenant-a"
    assert user["roles"] == ["user"]

    # Authenticate success
    authed = auth.authenticate_user("alice", "alicePass")
    assert authed is not None
    assert authed["tenant_id"] == "tenant-a"

    # Authenticate failure
    assert auth.authenticate_user("alice", "wrong") is None
    assert auth.authenticate_user("nonexistent", "pass") is None


def test_auth_service_sqlite_db():
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db = PostgresDBManager(f"sqlite:///{tmp.name}")
        auth = AuthService(db=db, secret_key="test-secret")

        user = auth.seed_user("bob", "bobPass", tenant_id="tenant-b", roles=["user", "admin"])
        assert user["username"] == "bob"

        # Lookup
        db_user = auth.get_user_by_username("bob")
        assert db_user is not None
        assert db_user["tenant_id"] == "tenant-b"
        assert set(db_user["roles"]) == {"user", "admin"}

        # Authenticate
        assert auth.authenticate_user("bob", "bobPass") is not None
        assert auth.authenticate_user("bob", "wrong") is None

        # Update existing user
        updated = auth.seed_user("bob", "newPass", tenant_id="tenant-b2", roles=["admin"])
        assert updated["tenant_id"] == "tenant-b2"
        assert auth.authenticate_user("bob", "newPass") is not None
        assert auth.authenticate_user("bob", "bobPass") is None


def test_jwt_tokens():
    auth = AuthService(secret_key="my-jwt-key")
    access_token = auth.create_access_token("user1", "tenant1", ["user"], expires_delta=timedelta(minutes=5))
    refresh_token = auth.create_refresh_token("user1", "tenant1", ["user"], expires_delta=timedelta(days=1))

    # Decode valid tokens
    payload = auth.decode_token(access_token, expected_type="access")
    assert payload["sub"] == "user1"
    assert payload["tenant_id"] == "tenant1"
    assert payload["roles"] == ["user"]
    assert payload["type"] == "access"

    ref_payload = auth.decode_token(refresh_token, expected_type="refresh")
    assert ref_payload["sub"] == "user1"
    assert ref_payload["type"] == "refresh"

    # Reject type mismatch
    with pytest.raises(jwt.InvalidTokenError):
        auth.decode_token(access_token, expected_type="refresh")

    # Reject wrong signature
    other_auth = AuthService(secret_key="different-key")
    with pytest.raises(jwt.InvalidSignatureError):
        other_auth.decode_token(access_token)


def test_jwt_expiration():
    auth = AuthService(secret_key="my-jwt-key")
    short_token = auth.create_access_token("user1", "tenant1", ["user"], expires_delta=timedelta(seconds=-1))
    with pytest.raises(jwt.ExpiredSignatureError):
        auth.decode_token(short_token)


def test_authorize_project():
    auth = AuthService()

    class MockVersionService:
        def get_project(self, project_id, owner_scope):
            if project_id == "proj_a" and owner_scope == "tenant_a":
                return {"id": "proj_a"}
            return None

    vs = MockVersionService()

    # Admin role bypasses tenant check
    admin_claims = {"sub": "u_admin", "tenant_id": "other", "roles": ["admin"]}
    assert auth.authorize_project(admin_claims, "proj_a", vs) is True

    # Matching tenant passes
    tenant_a_claims = {"sub": "u_a", "tenant_id": "tenant_a", "roles": ["user"]}
    assert auth.authorize_project(tenant_a_claims, "proj_a", vs) is True

    # Mismatched tenant fails
    tenant_b_claims = {"sub": "u_b", "tenant_id": "tenant_b", "roles": ["user"]}
    assert auth.authorize_project(tenant_b_claims, "proj_a", vs) is False
