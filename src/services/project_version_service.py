"""
Project Version Service managing Project, ProjectVersion, and ProjectCredential entities.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..models import Project, ProjectCredential, ProjectVersion
from ..utils.postgres_db_manager import PostgresDBManager
from ..utils.validators import (
    canonicalize_repo_url,
    validate_git_branch,
    validate_github_token,
    validate_repo_url,
)
from .credential_store import (
    CredentialEncryptionAdapter,
    InMemoryCredentialEncryptionAdapter,
)

logger = logging.getLogger(__name__)


def derive_provider(url: str) -> str:
    from urllib.parse import urlparse
    host = urlparse(url).hostname.lower()
    if "github" in host:
        return "github"
    elif "gitlab" in host:
        return "gitlab"
    elif "azure" in host:
        return "azure"
    return "unknown"


def compute_project_id(remote_url: str, owner_scope: str) -> str:
    canonical = canonicalize_repo_url(remote_url)
    raw = f"{owner_scope}:{canonical}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def compute_version_id(project_id: str, commit_sha: str, build_config: Dict[str, Any]) -> str:
    cfg_str = json.dumps(build_config, sort_keys=True)
    raw = f"{project_id}:{commit_sha}:{cfg_str}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class ProjectVersionService:
    """Service to handle immutable project version catalog and credential management."""

    @staticmethod
    def compute_version_id(project_id: str, commit_sha: str, build_config: Dict[str, Any]) -> str:
        return compute_version_id(project_id, commit_sha, build_config)

    def __init__(
        self,
        db_manager: PostgresDBManager,
        encryption_adapter: Optional[CredentialEncryptionAdapter] = None,
    ):
        self.db = db_manager
        self.crypto = encryption_adapter or InMemoryCredentialEncryptionAdapter()

    # --- Project Management ---

    def register_project(
        self,
        remote_url: str,
        default_branch: str = "main",
        owner_scope: str = "default",
        credential: Optional[str] = None,
    ) -> Project:
        validate_repo_url(remote_url)
        validate_git_branch(default_branch)
        if credential:
            validate_github_token(credential)

        canonical_url = canonicalize_repo_url(remote_url)
        provider = derive_provider(canonical_url)
        project_id = compute_project_id(canonical_url, owner_scope)

        now = datetime.now(timezone.utc).isoformat()
        with self.db._connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = %s", (project_id,)).fetchone()
            if row:
                project = Project.from_dict(dict(row))
            else:
                conn.execute(
                    """
                    INSERT INTO projects (id, provider, remote_url, default_branch, owner_scope, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (project_id, provider, canonical_url, default_branch, owner_scope, now, now),
                )
                conn.commit()
                project = Project(
                    id=project_id,
                    provider=provider,
                    remote_url=canonical_url,
                    default_branch=default_branch,
                    owner_scope=owner_scope,
                    created_at=datetime.fromisoformat(now),
                    updated_at=datetime.fromisoformat(now),
                )

        if credential:
            self.set_project_credential(project_id, credential, owner_scope)

        return project

    def get_project(self, project_id: str, owner_scope: Optional[str] = None) -> Optional[Project]:
        with self.db._connect() as conn:
            if owner_scope:
                row = conn.execute(
                    "SELECT * FROM projects WHERE id = %s AND owner_scope = %s",
                    (project_id, owner_scope),
                ).fetchone()
            else:
                row = conn.execute("SELECT * FROM projects WHERE id = %s", (project_id,)).fetchone()
            return Project.from_dict(dict(row)) if row else None

    def list_projects(self, owner_scope: str = "default") -> List[Project]:
        with self.db._connect() as conn:
            rows = conn.execute("SELECT * FROM projects WHERE owner_scope = %s ORDER BY created_at DESC", (owner_scope,)).fetchall()
            return [Project.from_dict(dict(r)) for r in rows]

    def update_project_branch(self, project_id: str, new_branch: str, owner_scope: str = "default") -> bool:
        validate_git_branch(new_branch)
        project = self.get_project(project_id, owner_scope)
        if not project:
            return False
        now = datetime.now(timezone.utc).isoformat()
        with self.db._connect() as conn:
            conn.execute(
                "UPDATE projects SET default_branch = %s, updated_at = %s WHERE id = %s AND owner_scope = %s",
                (new_branch, now, project_id, owner_scope),
            )
            conn.commit()
        return True

    def delete_project(self, project_id: str, owner_scope: str = "default") -> bool:
        project = self.get_project(project_id, owner_scope)
        if not project:
            return False
        with self.db._connect() as conn:
            conn.execute("DELETE FROM projects WHERE id = %s AND owner_scope = %s", (project_id, owner_scope))
            conn.commit()
        return True

    # --- Credential Management ---

    def set_project_credential(self, project_id: str, credential: str, owner_scope: str = "default") -> bool:
        validate_github_token(credential)
        project = self.get_project(project_id, owner_scope)
        if not project:
            return False

        ciphertext = self.crypto.encrypt(credential)
        now = datetime.now(timezone.utc).isoformat()

        with self.db._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_credentials (project_id, ciphertext, key_version, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (project_id) DO UPDATE SET
                    ciphertext = EXCLUDED.ciphertext,
                    key_version = EXCLUDED.key_version,
                    updated_at = EXCLUDED.updated_at
                """,
                (project_id, ciphertext, "v1", now),
            )
            conn.commit()
        return True

    def get_project_credential(self, project_id: str, owner_scope: str = "default") -> Optional[str]:
        project = self.get_project(project_id, owner_scope)
        if not project:
            return None

        with self.db._connect() as conn:
            row = conn.execute("SELECT ciphertext FROM project_credentials WHERE project_id = %s", (project_id,)).fetchone()
            if not row or not row["ciphertext"]:
                return None
            try:
                return self.crypto.decrypt(row["ciphertext"])
            except Exception as e:
                logger.error(f"Failed to decrypt credential for project {project_id}: {e}")
                return None

    def revoke_project_credential(self, project_id: str, owner_scope: str = "default") -> bool:
        project = self.get_project(project_id, owner_scope)
        if not project:
            return False

        with self.db._connect() as conn:
            conn.execute("DELETE FROM project_credentials WHERE project_id = %s", (project_id,))
            conn.commit()
        return True

    # --- Project Version Management ---

    def create_or_get_version(
        self,
        project_id: str,
        commit_sha: str,
        branch: str,
        content_digest: str,
        build_config: Optional[Dict[str, Any]] = None,
        manifest: Optional[Dict[str, Any]] = None,
        source_snapshot_ref: Optional[str] = None,
        owner_scope: str = "default",
    ) -> Tuple[ProjectVersion, str]:
        """Create a new version or return an existing immutable version.

        Returns (ProjectVersion, status) where status is 'created' or 'unchanged'.
        """
        project = self.get_project(project_id, owner_scope)
        if not project:
            raise ValueError(f"Project {project_id} not found or unauthorized")

        if not commit_sha or len(commit_sha) != 40:
            raise ValueError("commit_sha must be a valid 40-character SHA")

        validate_git_branch(branch)

        cfg = build_config or {}
        man = manifest or {}
        version_id = compute_version_id(project_id, commit_sha, cfg)

        now = datetime.now(timezone.utc).isoformat()
        with self.db._connect() as conn:
            row = conn.execute("SELECT * FROM project_versions WHERE id = %s", (version_id,)).fetchone()
            if row:
                existing = ProjectVersion.from_dict(dict(row))
                return existing, "unchanged"

            conn.execute(
                """
                INSERT INTO project_versions (
                    id, project_id, commit_sha, branch, content_digest, build_config, manifest, source_snapshot_ref, build_status, build_metadata, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    version_id,
                    project_id,
                    commit_sha,
                    branch,
                    content_digest,
                    json.dumps(cfg),
                    json.dumps(man),
                    source_snapshot_ref,
                    "queued",
                    json.dumps({}),
                    now,
                    now,
                ),
            )
            conn.commit()

            version = ProjectVersion(
                id=version_id,
                project_id=project_id,
                commit_sha=commit_sha,
                branch=branch,
                content_digest=content_digest,
                build_config=cfg,
                manifest=man,
                source_snapshot_ref=source_snapshot_ref,
                build_status="queued",
                build_metadata={},
                created_at=datetime.fromisoformat(now),
                updated_at=datetime.fromisoformat(now),
            )
            return version, "created"

    def get_version(self, version_id: str, owner_scope: Optional[str] = None) -> Optional[ProjectVersion]:
        with self.db._connect() as conn:
            if owner_scope:
                row = conn.execute(
                    """
                    SELECT pv.* FROM project_versions pv
                    JOIN projects p ON pv.project_id = p.id
                    WHERE pv.id = %s AND p.owner_scope = %s
                    """,
                    (version_id, owner_scope),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM project_versions WHERE id = %s",
                    (version_id,),
                ).fetchone()
            return ProjectVersion.from_dict(dict(row)) if row else None

    def cancel_version_build(
        self,
        version_id: str,
        codebase_hash: Optional[str] = None,
        partial_artifacts: Optional[List[str]] = None,
        owner_scope: str = "default",
    ) -> Tuple[ProjectVersion, bool]:
        """Cancel an in-flight version build and clean up partial artifacts.

        Raises ValueError if current build_status is 'ready' or 'failed'.
        """
        version = self.get_version(version_id, owner_scope)
        if not version:
            raise ValueError(f"Version {version_id} not found or unauthorized")

        if version.build_status == "ready":
            raise ValueError("cannot cancel a ready build")
        if version.build_status == "failed":
            raise ValueError("cannot cancel a failed build")

        now = datetime.now(timezone.utc).isoformat()
        with self.db._connect() as conn:
            row = conn.execute(
                """
                UPDATE project_versions
                SET build_status = 'cancelled', updated_at = %s
                WHERE id = %s AND build_status IN ('queued', 'building', 'loading')
                RETURNING *
                """,
                (now, version_id),
            ).fetchone()
            if not row:
                conn.rollback()
                # Re-check status to raise appropriate error
                v = self.get_version(version_id, owner_scope)
                if v and v.build_status == "ready":
                    raise ValueError("cannot cancel a ready build")
                if v and v.build_status == "failed":
                    raise ValueError("cannot cancel a failed build")
                return version, False

            conn.commit()
            cancelled_version = ProjectVersion.from_dict(dict(row))

        # Cancel job in job store if active
        if codebase_hash:
            with self.db._connect() as conn:
                conn.execute(
                    "UPDATE jobs SET status = 'failed', error = 'Cancelled by user', updated_at = %s "
                    "WHERE codebase_hash = %s AND status IN ('queued', 'running')",
                    (now, codebase_hash),
                )
                conn.commit()

        # Clean up partial artifacts
        import os
        import shutil
        if partial_artifacts:
            for art in partial_artifacts:
                if os.path.isdir(art):
                    shutil.rmtree(art, ignore_errors=True)
                elif os.path.isfile(art):
                    try:
                        os.remove(art)
                    except OSError:
                        pass

        return cancelled_version, True

    def retry_version_build(
        self,
        version_id: str,
        queue: Optional[Any] = None,
        owner_scope: str = "default",
    ) -> Tuple[ProjectVersion, str]:
        """Retry a failed or cancelled version build idempotently.

        Returns (ProjectVersion, status) where status is 'queued' or 'already_active'.
        """
        version = self.get_version(version_id, owner_scope)
        if not version:
            raise ValueError(f"Version {version_id} not found or unauthorized")

        if version.build_status == "ready":
            raise ValueError("cannot retry a ready build")

        if version.build_status in ("queued", "building", "loading"):
            return version, "already_active"

        if version.build_status not in ("failed", "cancelled"):
            raise ValueError(f"cannot retry build in status {version.build_status}")

        # Increment retry_count in build_metadata
        current_meta = dict(version.build_metadata) if isinstance(version.build_metadata, dict) else {}
        current_retry = current_meta.get("retry_count", 0)
        current_meta["retry_count"] = current_retry + 1

        now = datetime.now(timezone.utc).isoformat()
        with self.db._connect() as conn:
            row = conn.execute(
                """
                UPDATE project_versions
                SET build_status = 'queued', build_metadata = %s, updated_at = %s
                WHERE id = %s AND build_status IN ('failed', 'cancelled')
                RETURNING *
                """,
                (json.dumps(current_meta), now, version_id),
            ).fetchone()
            if not row:
                conn.rollback()
                v = self.get_version(version_id, owner_scope)
                if v and v.build_status in ("queued", "building", "loading"):
                    return v, "already_active"
                if v and v.build_status == "ready":
                    raise ValueError("cannot retry a ready build")
                raise ValueError("Retry state update failed")

            conn.commit()
            updated_version = ProjectVersion.from_dict(dict(row))

        # Enqueue build job if queue provided
        if queue:
            codebase_hash = updated_version.id
            job = {
                "version_id": version_id,
                "project_id": updated_version.project_id,
                "commit_sha": updated_version.commit_sha,
                "branch": updated_version.branch,
                "build_config": updated_version.build_config,
            }
            # Enqueue job synchronously or via submit if async context
            self.db.enqueue_job(codebase_hash, "generate_cpg", job)

        return updated_version, "queued"

    def list_versions(self, project_id: str, owner_scope: Optional[str] = None) -> List[ProjectVersion]:
        with self.db._connect() as conn:
            if owner_scope:
                rows = conn.execute(
                    """
                    SELECT pv.* FROM project_versions pv
                    JOIN projects p ON pv.project_id = p.id
                    WHERE pv.project_id = %s AND p.owner_scope = %s
                    ORDER BY pv.created_at DESC
                    """,
                    (project_id, owner_scope),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM project_versions
                    WHERE project_id = %s
                    ORDER BY created_at DESC
                    """,
                    (project_id,),
                ).fetchall()
            return [ProjectVersion.from_dict(dict(r)) for r in rows]
