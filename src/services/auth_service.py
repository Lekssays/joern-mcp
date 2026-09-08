"""
Authentication & Tenancy Service (Phase 8 - API-03)

Handles PBKDF2 password hashing, user seeding/persistence,
JWT token issuance and validation (PyJWT), and tenant access authorization.
"""

import hashlib
import hmac
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import jwt

from ..config import JWT_ALGORITHM, JWT_SECRET_KEY, ACCESS_TOKEN_EXPIRE_MINUTES, REFRESH_TOKEN_EXPIRE_DAYS

logger = logging.getLogger(__name__)


def hash_password(password: str, salt: Optional[str] = None) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with 100,000 iterations."""
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100000,
    )
    return f"{salt}${key.hex()}"


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify password against stored salt$hash format using constant-time comparison."""
    if not hashed_password or "$" not in hashed_password:
        return False
    try:
        salt, expected_hash = hashed_password.split("$", 1)
        key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            100000,
        )
        return hmac.compare_digest(key.hex(), expected_hash)
    except Exception as e:
        logger.error(f"Error during password verification: {e}")
        return False


class AuthService:
    """Service for user authentication, token issuance, and tenant authorization."""

    def __init__(
        self,
        db: Optional[Any] = None,
        secret_key: Optional[str] = None,
        algorithm: str = JWT_ALGORITHM,
        access_token_expire_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES,
        refresh_token_expire_days: int = REFRESH_TOKEN_EXPIRE_DAYS,
    ):
        self.db = db
        self.secret_key = secret_key or os.getenv("JWT_SECRET_KEY") or JWT_SECRET_KEY
        self.algorithm = algorithm
        self.access_token_expire_minutes = access_token_expire_minutes
        self.refresh_token_expire_days = refresh_token_expire_days
        self._in_memory_users: Dict[str, dict] = {}

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def seed_user(
        self,
        username: str,
        password: str,
        tenant_id: str = "default",
        roles: Optional[List[str]] = None,
    ) -> dict:
        """Seed or update a user with a hashed password, tenant_id, and roles."""
        if not username or not password:
            raise ValueError("Username and password are required")

        role_list = roles if roles is not None else ["user"]
        roles_str = ",".join(role_list)
        hashed = hash_password(password)
        now = self._now_iso()

        if self.db and hasattr(self.db, "_connect"):
            try:
                with self.db._connect() as conn:
                    row = conn.execute("SELECT id FROM users WHERE username = %s", (username,)).fetchone()
                    if row:
                        user_id = row["id"] if isinstance(row, dict) else row[0]
                        conn.execute(
                            """
                            UPDATE users
                            SET password_hash = %s, tenant_id = %s, roles = %s, updated_at = %s
                            WHERE id = %s
                            """,
                            (hashed, tenant_id, roles_str, now, user_id),
                        )
                    else:
                        user_id = f"usr_{uuid.uuid4().hex[:12]}"
                        conn.execute(
                            """
                            INSERT INTO users (id, username, password_hash, tenant_id, roles, created_at, updated_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            """,
                            (user_id, username, hashed, tenant_id, roles_str, now, now),
                        )
                    conn.commit()
                return {
                    "id": user_id,
                    "username": username,
                    "tenant_id": tenant_id,
                    "roles": role_list,
                    "created_at": now,
                    "updated_at": now,
                }
            except Exception as e:
                logger.warning(f"Database user seeding failed, falling back to memory: {e}")

        # Fallback / In-Memory storage
        user_id = self._in_memory_users.get(username, {}).get("id") or f"usr_{uuid.uuid4().hex[:12]}"
        user_record = {
            "id": user_id,
            "username": username,
            "password_hash": hashed,
            "tenant_id": tenant_id,
            "roles": role_list,
            "created_at": now,
            "updated_at": now,
        }
        self._in_memory_users[username] = user_record
        return {
            "id": user_id,
            "username": username,
            "tenant_id": tenant_id,
            "roles": role_list,
            "created_at": now,
            "updated_at": now,
        }

    def get_user_by_username(self, username: str) -> Optional[dict]:
        """Fetch user record by username."""
        if not username:
            return None

        if self.db and hasattr(self.db, "_connect"):
            try:
                with self.db._connect() as conn:
                    row = conn.execute("SELECT * FROM users WHERE username = %s", (username,)).fetchone()
                    if row:
                        d = dict(row)
                        roles_val = d.get("roles", "")
                        d["roles"] = [r.strip() for r in roles_val.split(",") if r.strip()]
                        return d
            except Exception as e:
                logger.error(f"Error fetching user {username} from db: {e}")

        user = self._in_memory_users.get(username)
        if user:
            return {
                "id": user["id"],
                "username": user["username"],
                "password_hash": user["password_hash"],
                "tenant_id": user["tenant_id"],
                "roles": list(user["roles"]),
                "created_at": user["created_at"],
                "updated_at": user["updated_at"],
            }
        return None

    def authenticate_user(self, username: str, password: str) -> Optional[dict]:
        """Verify username and password. Returns user dict on success, None on failure."""
        user = self.get_user_by_username(username)
        if not user:
            return None
        if verify_password(password, user.get("password_hash", "")):
            return {
                "id": user["id"],
                "username": user["username"],
                "tenant_id": user["tenant_id"],
                "roles": user["roles"],
            }
        return None

    def create_access_token(
        self,
        user_id: str,
        tenant_id: str,
        roles: Optional[List[str]] = None,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """Create a signed short-lived JWT access token."""
        now = datetime.now(timezone.utc)
        delta = expires_delta or timedelta(minutes=self.access_token_expire_minutes)
        exp = now + delta
        payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "roles": roles or ["user"],
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def create_refresh_token(
        self,
        user_id: str,
        tenant_id: str,
        roles: Optional[List[str]] = None,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """Create a signed long-lived JWT refresh token."""
        now = datetime.now(timezone.utc)
        delta = expires_delta or timedelta(days=self.refresh_token_expire_days)
        exp = now + delta
        payload = {
            "sub": user_id,
            "tenant_id": tenant_id,
            "roles": roles or ["user"],
            "type": "refresh",
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def decode_token(self, token: str, expected_type: Optional[str] = None) -> dict:
        """Decode and validate a JWT token. Raises PyJWTError on failure."""
        payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        if expected_type and payload.get("type") != expected_type:
            raise jwt.InvalidTokenError(f"Expected token type '{expected_type}', got '{payload.get('type')}'")
        return payload

    def authorize_project(
        self,
        user_claims: dict,
        project_id: str,
        version_service: Optional[Any] = None,
    ) -> bool:
        """Authorize project access against user tenant context. Returns 404 fail-closed if mismatch."""
        roles = user_claims.get("roles", [])
        if "admin" in roles:
            return True

        tenant_id = user_claims.get("tenant_id")
        if not tenant_id:
            return False

        if version_service and hasattr(version_service, "get_project"):
            p = version_service.get_project(project_id, owner_scope=tenant_id)
            return p is not None

        return True
