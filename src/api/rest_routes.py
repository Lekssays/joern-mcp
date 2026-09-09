"""
REST Endpoints for CodeBadger Server (Phase 5, 6, 7 & 8)
Supports Projects, Versions, Builds, Context Retrieval, and OpenAPI/Swagger Documentation.
"""

import json
import logging
from typing import Any, Dict, Optional, Tuple

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

from ..models import ProjectVersion
from ..config import MAX_CONCURRENT_BUILDS_PER_TENANT, MAX_PAYLOAD_SIZE_BYTES

logger = logging.getLogger(__name__)


def format_version_response(version: ProjectVersion) -> Dict[str, Any]:
    """Format a ProjectVersion model into the canonical backend contract dictionary.
    
    Translates raw build_metadata into top-level contract keys:
    status, phase, queue_position, elapsed_ms, retry_count, error.
    """
    raw_meta = getattr(version, "build_metadata", {})
    if isinstance(raw_meta, str):
        try:
            meta = json.loads(raw_meta)
        except Exception:
            meta = {}
    elif isinstance(raw_meta, dict):
        meta = raw_meta
    else:
        meta = {}
        
    return {
        "id": version.id,
        "project_id": version.project_id,
        "commit_sha": version.commit_sha,
        "branch": version.branch,
        "content_digest": version.content_digest,
        "status": version.build_status,
        "phase": meta.get("phase", "init" if version.build_status == "queued" else version.build_status),
        "queue_position": meta.get("queue_position", 0 if version.build_status == "queued" else None),
        "elapsed_ms": meta.get("elapsed_ms", 0),
        "retry_count": meta.get("retry_count", 0),
        "error": meta.get("error", None),
        "build_config": version.build_config if hasattr(version, "build_config") else {},
        "manifest": version.manifest if hasattr(version, "manifest") else {},
        "source_snapshot_ref": getattr(version, "source_snapshot_ref", None),
        "created_at": version.created_at.isoformat() if hasattr(version.created_at, "isoformat") else str(version.created_at),
        "updated_at": version.updated_at.isoformat() if hasattr(version.updated_at, "isoformat") else str(version.updated_at),
        "build_metadata": meta,
        "observability": {
            "queue_time_ms": meta.get("queue_time_ms"),
            "build_duration_ms": meta.get("build_duration_ms"),
            "cpg_size_bytes": meta.get("cpg_size_bytes"),
            "peak_memory_mb": meta.get("peak_memory_mb"),
            "log_snippet": meta.get("log_snippet"),
            "failure_reason": meta.get("failure_reason"),
        }
    }


def check_tenant_build_quota(version_service: Any, tenant_id: str, max_concurrent: int) -> bool:
    """Check if tenant active builds are under quota threshold."""
    if not version_service or not hasattr(version_service, "db") or not version_service.db:
        return True
    try:
        with version_service.db._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) FROM project_versions pv
                JOIN projects p ON pv.project_id = p.id
                WHERE p.owner_scope = %s AND pv.build_status IN ('queued', 'building', 'loading')
                """,
                (tenant_id,),
            ).fetchone()
            count = row[0] if row else 0
            return count < max_concurrent
    except Exception as e:
        logger.warning(f"Error checking tenant build quota: {e}")
        return True


def get_actor_info(request: Request) -> Tuple[str, str]:
    """Extract actor and tenant_id from request auth context."""
    user = getattr(request.state, "user", None) or request.scope.get("user")
    if user:
        return user.get("sub", "unknown"), user.get("tenant_id", "default")
    return "anonymous", request.query_params.get("owner_scope", "default")


def get_tenant_context(request: Request) -> Tuple[Optional[str], bool]:
    """Extract tenant_id and is_admin from authenticated request context.

    Falls back to query parameter or 'default' if auth middleware is not mounted.
    """
    user = getattr(request.state, "user", None) or request.scope.get("user")
    if user:
        roles = user.get("roles", [])
        is_admin = "admin" in roles
        return user.get("tenant_id"), is_admin
    return request.query_params.get("owner_scope", "default"), False


def build_openapi_schema() -> dict:
    """Return OpenAPI 3.1.0 specification dictionary for all REST endpoints."""
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "CodeBadger Ingestion & Version Catalog API",
            "version": "1.0.0",
            "description": "REST endpoints managing projects, source uploads, immutable versions, CPG build dispatch, and context retrieval."
        },
        "paths": {
            "/auth/mcp-token": {
                "post": {
                    "summary": "Generate a permanent non-expiring JWT token specifically for MCP clients",
                    "requestBody": {"required": True, "content": {"application/json": {}}},
                    "responses": {"200": {"description": "MCP token generated"}, "401": {"description": "Invalid credentials"}}
                }
            },
            "/auth/login": {
                "post": {
                    "summary": "Authenticate user credentials and receive JWT access/refresh tokens",
                    "requestBody": {"required": True, "content": {"application/json": {}}},
                    "responses": {"200": {"description": "Authenticated"}, "401": {"description": "Invalid credentials"}}
                }
            },
            "/auth/refresh": {
                "post": {
                    "summary": "Refresh JWT access token",
                    "requestBody": {"required": True, "content": {"application/json": {}}},
                    "responses": {"200": {"description": "Token refreshed"}, "401": {"description": "Invalid refresh token"}}
                }
            },
            "/projects": {
                "post": {
                    "summary": "Register a new Git project repository",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["remote_url"],
                                    "properties": {
                                        "remote_url": {"type": "string"},
                                        "default_branch": {"type": "string", "default": "main"},
                                        "owner_scope": {"type": "string", "default": "default"},
                                        "credential": {"type": "string"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "201": {"description": "Project registered successfully"},
                        "400": {"description": "Invalid parameters"}
                    }
                },
                "get": {
                    "summary": "List registered projects",
                    "parameters": [
                        {"name": "owner_scope", "in": "query", "required": False, "schema": {"type": "string", "default": "default"}}
                    ],
                    "responses": {
                        "200": {"description": "List of projects"}
                    }
                }
            },
            "/projects/{id}": {
                "get": {
                    "summary": "Get a specific project by ID",
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Project details"},
                        "404": {"description": "Project not found"}
                    }
                },
                "delete": {
                    "summary": "Delete a project and its credentials",
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Project deleted"},
                        "404": {"description": "Project not found"}
                    }
                }
            },
            "/projects/{id}/sync": {
                "post": {
                    "summary": "Trigger Git sync and queue build for branch",
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Version already up-to-date"},
                        "201": {"description": "New version created and build queued"},
                        "404": {"description": "Project not found"}
                    }
                }
            },
            "/projects/{id}/versions": {
                "get": {
                    "summary": "List all version build states for a project",
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "List of versions"}
                    }
                },
                "post": {
                    "summary": "Create or fetch an immutable version with explicit commit SHA",
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["commit_sha", "content_digest"],
                                    "properties": {
                                        "commit_sha": {"type": "string"},
                                        "branch": {"type": "string", "default": "main"},
                                        "content_digest": {"type": "string"},
                                        "build_config": {"type": "object"},
                                        "manifest": {"type": "object"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {"description": "Existing version returned"},
                        "201": {"description": "New version created"},
                        "400": {"description": "Validation error"}
                    }
                }
            },
            "/projects/{id}/versions/archive": {
                "post": {
                    "summary": "Ingest project version via tar.gz or zip archive upload",
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "required": ["file"],
                                    "properties": {
                                        "file": {"type": "string", "format": "binary"},
                                        "branch": {"type": "string", "default": "main"},
                                        "commit_sha": {"type": "string"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "201": {"description": "Archive extracted and version registered"},
                        "400": {"description": "Invalid archive or zip bomb detected"}
                    }
                }
            },
            "/versions": {
                "get": {
                    "summary": "List versions across projects or query by project",
                    "parameters": [{"name": "project_id", "in": "query", "required": False, "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "List of versions"}}
                }
            },
            "/versions/{id}": {
                "get": {
                    "summary": "Get version build status and observability metadata",
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Version details"},
                        "404": {"description": "Version not found"}
                    }
                }
            },
            "/versions/{id}/retry": {
                "post": {
                    "summary": "Retry a failed or cancelled version build",
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "202": {"description": "Build requeued"},
                        "400": {"description": "Cannot retry ready or already active build"},
                        "404": {"description": "Version not found"}
                    }
                }
            },
            "/versions/{id}/cancel": {
                "post": {
                    "summary": "Cancel an in-flight build and purge partial artifacts",
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "200": {"description": "Build cancelled"},
                        "400": {"description": "Cannot cancel completed build"},
                        "404": {"description": "Version not found"}
                    }
                }
            },
            "/versions/{id}/build": {
                "post": {
                    "summary": "Enqueue or trigger a CPG build for an existing version",
                    "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                    "responses": {
                        "202": {"description": "Build queued"},
                        "200": {"description": "Build already in flight"},
                        "404": {"description": "Version not found"}
                    }
                }
            },
            "/versions/{id}/context": {
                "get": {
                    "summary": "Retrieve focused code context from ready CPG",
                    "parameters": [
                        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                        {"name": "query", "in": "query", "required": True, "schema": {"type": "string"}},
                        {"name": "max_items", "in": "query", "required": False, "schema": {"type": "integer", "default": 10}},
                        {"name": "max_bytes", "in": "query", "required": False, "schema": {"type": "integer", "default": 50000}}
                    ],
                    "responses": {
                        "200": {"description": "Context response with exact methods and callers"},
                        "400": {"description": "Missing query or invalid parameters"},
                        "404": {"description": "Version not found or not ready"},
                        "503": {"description": "Context service unavailable"}
                    }
                }
            }
        }
    }


def openapi_schema_endpoint(request: Request) -> JSONResponse:
    return JSONResponse(build_openapi_schema())


def docs_swagger_endpoint(request: Request) -> HTMLResponse:
    html = """<!DOCTYPE html>
<html>
<head>
  <title>CodeBadger API Docs</title>
  <meta charset="utf-8"/>
  <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" >
</head>
<body>
  <div id="swagger-ui"></div>
  <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"> </script>
  <script>
    window.onload = function() {
      SwaggerUIBundle({
        url: "/openapi.json",
        dom_id: '#swagger-ui',
        deepLinking: true,
        presets: [
          SwaggerUIBundle.presets.apis,
          SwaggerUIBundle.SwaggerUIStandalonePreset
        ],
      });
    };
  </script>
</body>
</html>"""
    return HTMLResponse(html)


def register_rest_routes(app: Any, services: Dict[str, Any]) -> None:
    """Register REST, Auth, and documentation routes on Starlette or FastMCP."""

    if "auth_service" not in services:
        from ..services.auth_service import AuthService
        db = services.get("db_manager")
        if not db and "version_service" in services:
            db = getattr(services["version_service"], "db", None)
        services["auth_service"] = AuthService(db=db)

    if "audit_logger" not in services:
        from ..services.audit_logger import AuditLogger
        services["audit_logger"] = AuditLogger()
    audit_logger = services["audit_logger"]

    async def auth_mcp_token(request: Request) -> JSONResponse:
        """Issue permanent non-expiring JWT token for MCP clients (Claude Code, Cursor, etc.)."""
        auth_service = services.get("auth_service")
        if not auth_service:
            return JSONResponse({"error": "Auth service not configured"}, status_code=503)
        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            return JSONResponse({"error": "Username and password are required"}, status_code=400)

        user = auth_service.authenticate_user(username, password)
        if not user:
            audit_logger.log_event("auth.mcp_token_failure", resource_id="", status_code=401, actor=username, tenant_id="unknown")
            return JSONResponse({"error": "Invalid username or password"}, status_code=401)

        mcp_token = auth_service.create_mcp_token(
            user_id=user["id"],
            tenant_id=user["tenant_id"],
            roles=user.get("roles", ["user"]),
        )
        audit_logger.log_event("auth.mcp_token_issued", resource_id=user["id"], status_code=200, actor=user["username"], tenant_id=user["tenant_id"])
        return JSONResponse({
            "mcp_token": mcp_token,
            "token_type": "Bearer",
            "tenant_id": user["tenant_id"],
            "roles": user.get("roles", ["user"]),
            "expires_in": None,
            "description": "Permanent MCP client token. Safe to save in mcp.json or claude_desktop_config.json",
        })

    async def auth_login(request: Request) -> JSONResponse:
        auth_service = services.get("auth_service")
        if not auth_service:
            return JSONResponse({"error": "Auth service not configured"}, status_code=503)
        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            return JSONResponse({"error": "Username and password are required"}, status_code=400)

        user = auth_service.authenticate_user(username, password)
        if not user:
            audit_logger.log_event("auth.login_failure", resource_id="", status_code=401, actor=username, tenant_id="unknown")
            return JSONResponse({"error": "Invalid username or password"}, status_code=401)
        audit_logger.log_event("auth.login_success", resource_id=user["id"], status_code=200, actor=user["username"], tenant_id=user["tenant_id"])

        access_token = auth_service.create_access_token(
            user_id=user["id"],
            tenant_id=user["tenant_id"],
            roles=user.get("roles", ["user"]),
        )
        refresh_token = auth_service.create_refresh_token(
            user_id=user["id"],
            tenant_id=user["tenant_id"],
            roles=user.get("roles", ["user"]),
        )
        return JSONResponse({
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer",
            "expires_in": auth_service.access_token_expire_minutes * 60,
            "tenant_id": user["tenant_id"],
            "roles": user.get("roles", ["user"]),
        })

    async def auth_refresh(request: Request) -> JSONResponse:
        auth_service = services.get("auth_service")
        if not auth_service:
            return JSONResponse({"error": "Auth service not configured"}, status_code=503)
        try:
            data = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

        token = data.get("refresh_token")
        if not token:
            return JSONResponse({"error": "Missing refresh_token"}, status_code=400)

        try:
            payload = auth_service.decode_token(token, expected_type="refresh")
        except Exception:
            return JSONResponse({"error": "Invalid or expired refresh token"}, status_code=401)

        audit_logger.log_event("auth.refresh", resource_id=payload["sub"], status_code=200, actor=payload["sub"], tenant_id=payload["tenant_id"])
        access_token = auth_service.create_access_token(
            user_id=payload["sub"],
            tenant_id=payload["tenant_id"],
            roles=payload.get("roles", ["user"]),
        )
        return JSONResponse({
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": auth_service.access_token_expire_minutes * 60,
        })

    async def create_project(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        data = await request.json()
        tenant_id, is_admin = get_tenant_context(request)
        owner_scope = data.get("owner_scope") if (is_admin and "owner_scope" in data) else (tenant_id or "default")
        try:
            p = version_service.register_project(
                remote_url=data.get("remote_url"),
                default_branch=data.get("default_branch", "main"),
                owner_scope=owner_scope,
                credential=data.get("credential"),
            )
            actor, tenant = get_actor_info(request)
            audit_logger.log_event("project.create", resource_id=p.id, status_code=201, actor=actor, tenant_id=tenant)
            return JSONResponse(p.to_dict(), status_code=201)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def list_projects(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        tenant_id, is_admin = get_tenant_context(request)
        if is_admin:
            owner_scope = request.query_params.get("owner_scope")
            projects = version_service.list_projects(owner_scope=owner_scope) if owner_scope else version_service.list_projects(owner_scope=tenant_id or "default")
        else:
            projects = version_service.list_projects(owner_scope=tenant_id or "default")
        return JSONResponse([p.to_dict() for p in projects])

    async def get_project(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        project_id = request.path_params["id"]
        tenant_id, is_admin = get_tenant_context(request)
        p = version_service.get_project(project_id, owner_scope=None if is_admin else tenant_id)
        if not p:
            return JSONResponse({"error": "Project not found"}, status_code=404)
        return JSONResponse(p.to_dict())

    async def delete_project(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        project_id = request.path_params["id"]
        tenant_id, is_admin = get_tenant_context(request)
        p = version_service.get_project(project_id, owner_scope=None if is_admin else tenant_id)
        if not p:
            return JSONResponse({"error": "Project not found"}, status_code=404)
        ok = version_service.delete_project(project_id, owner_scope=p.owner_scope)
        if not ok:
            return JSONResponse({"error": "Project not found"}, status_code=404)
        actor, tenant = get_actor_info(request)
        audit_logger.log_event("project.delete", resource_id=project_id, status_code=200, actor=actor, tenant_id=tenant)
        return JSONResponse({"status": "deleted"})

    async def sync_version(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        git_sync_service = services.get("git_sync_service")
        if not git_sync_service:
            return JSONResponse({"error": "Git sync service not available"}, status_code=503)

        project_id = request.path_params["id"]
        tenant_id, is_admin = get_tenant_context(request)
        p = version_service.get_project(project_id, owner_scope=None if is_admin else tenant_id)
        if not p:
            return JSONResponse({"error": "Project not found"}, status_code=404)

        data = await request.json() if request.headers.get("content-type") == "application/json" else {}
        branch = data.get("branch")
        build_config = data.get("build_config")

        try:
            v_dict, status = await git_sync_service.sync_project_branch(project_id, branch, build_config)
            v = version_service.get_version(v_dict["id"], owner_scope=None if is_admin else tenant_id)
            status_code = 201 if status == "created" else 200
            actor, tenant = get_actor_info(request)
            audit_logger.log_event("version.sync", resource_id=v.id, status_code=status_code, actor=actor, tenant_id=tenant)
            return JSONResponse(format_version_response(v), status_code=status_code)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def list_versions(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        project_id = request.path_params["id"]
        tenant_id, is_admin = get_tenant_context(request)
        p = version_service.get_project(project_id, owner_scope=None if is_admin else tenant_id)
        if not p:
            return JSONResponse({"error": "Project not found"}, status_code=404)
        versions = version_service.list_versions(project_id, owner_scope=None if is_admin else tenant_id)
        return JSONResponse([format_version_response(v) for v in versions])

    async def create_version(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        project_id = request.path_params["id"]
        tenant_id, is_admin = get_tenant_context(request)
        p = version_service.get_project(project_id, owner_scope=None if is_admin else tenant_id)
        if not p:
            return JSONResponse({"error": "Project not found"}, status_code=404)

        data = await request.json()
        try:
            v, status = version_service.create_or_get_version(
                project_id=project_id,
                commit_sha=data.get("commit_sha"),
                branch=data.get("branch", "main"),
                content_digest=data.get("content_digest"),
                build_config=data.get("build_config"),
                manifest=data.get("manifest"),
                source_snapshot_ref=data.get("source_snapshot_ref"),
                owner_scope=p.owner_scope,
            )
            status_code = 201 if status == "created" else 200
            actor, tenant = get_actor_info(request)
            audit_logger.log_event("version.create", resource_id=v.id, status_code=status_code, actor=actor, tenant_id=tenant)
            return JSONResponse(format_version_response(v), status_code=status_code)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def upload_archive(request: Request) -> JSONResponse:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_PAYLOAD_SIZE_BYTES:
                    return JSONResponse(
                        {"error": f"Payload too large. Maximum allowed size is {MAX_PAYLOAD_SIZE_BYTES} bytes"},
                        status_code=413,
                    )
            except ValueError:
                pass

        form = await request.form()
        archive_file = form.get("file")
        if not archive_file:
            return JSONResponse({"error": "Missing 'file' field in form"}, status_code=400)

        content = await archive_file.read()
        if len(content) > MAX_PAYLOAD_SIZE_BYTES:
            return JSONResponse(
                {"error": f"Payload too large. Maximum allowed size is {MAX_PAYLOAD_SIZE_BYTES} bytes"},
                status_code=413,
            )

        version_service = services["version_service"]
        archive_service = services.get("archive_service")
        if not archive_service:
            return JSONResponse({"error": "Archive service not available"}, status_code=503)

        project_id = request.path_params["id"]
        tenant_id, is_admin = get_tenant_context(request)
        p = version_service.get_project(project_id, owner_scope=None if is_admin else tenant_id)
        if not p:
            return JSONResponse({"error": "Project not found"}, status_code=404)

        branch = form.get("branch", "main")
        commit_sha = form.get("commit_sha")

        try:
            v_dict, status = await archive_service.process_archive_upload(
                project_id=project_id,
                file_bytes=content,
                filename=archive_file.filename or "upload.zip",
                branch=branch,
                commit_sha=commit_sha,
                owner_scope=p.owner_scope,
            )
            v = version_service.get_version(v_dict["id"], owner_scope=None if is_admin else tenant_id)
            status_code = 201 if status == "created" else 200
            actor, tenant = get_actor_info(request)
            audit_logger.log_event("version.sync", resource_id=v.id, status_code=status_code, actor=actor, tenant_id=tenant)
            return JSONResponse(format_version_response(v), status_code=status_code)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def get_version(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        version_id = request.path_params["id"]
        tenant_id, is_admin = get_tenant_context(request)
        v = version_service.get_version(version_id, owner_scope=None if is_admin else tenant_id)
        if not v:
            return JSONResponse({"error": "Version not found"}, status_code=404)
        return JSONResponse(format_version_response(v))

    async def retry_version(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        version_id = request.path_params["id"]
        tenant_id, is_admin = get_tenant_context(request)
        v = version_service.get_version(version_id, owner_scope=None if is_admin else tenant_id)
        if not v:
            return JSONResponse({"error": "Version not found"}, status_code=404)

        cpg_queue = services.get("cpg_queue")
        try:
            v_retried, status = version_service.retry_version_build(
                version_id, queue=cpg_queue, owner_scope=None if is_admin else tenant_id
            )
            actor, tenant = get_actor_info(request)
            audit_logger.log_event("version.retry", resource_id=version_id, status_code=202, actor=actor, tenant_id=tenant)
            return JSONResponse(format_version_response(v_retried), status_code=202)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def cancel_version(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        version_id = request.path_params["id"]
        tenant_id, is_admin = get_tenant_context(request)
        v = version_service.get_version(version_id, owner_scope=None if is_admin else tenant_id)
        if not v:
            return JSONResponse({"error": "Version not found"}, status_code=404)

        try:
            v_cancelled, ok = version_service.cancel_version_build(
                version_id, owner_scope=None if is_admin else tenant_id
            )
            actor, tenant = get_actor_info(request)
            audit_logger.log_event("version.cancel", resource_id=version_id, status_code=200, actor=actor, tenant_id=tenant)
            return JSONResponse(format_version_response(v_cancelled))
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def build_version(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        version_id = request.path_params["id"]
        tenant_id, is_admin = get_tenant_context(request)
        v = version_service.get_version(version_id, owner_scope=None if is_admin else tenant_id)
        if not v:
            return JSONResponse({"error": "Version not found"}, status_code=404)

        if not is_admin and not check_tenant_build_quota(version_service, tenant_id or "default", MAX_CONCURRENT_BUILDS_PER_TENANT):
            return JSONResponse(
                {"error": f"Tenant concurrent build quota exceeded. Maximum allowed: {MAX_CONCURRENT_BUILDS_PER_TENANT}"},
                status_code=429,
                headers={"Retry-After": "30"},
            )

        cpg_queue = services.get("cpg_queue")
        if not cpg_queue:
            return JSONResponse({"error": "CPG Queue not available"}, status_code=503)

        try:
            now = version_service._now() if hasattr(version_service, "_now") else ""
            if v.build_status in ("queued", "building"):
                return JSONResponse(format_version_response(v), status_code=200)

            cpg_queue.enqueue(v.id)
            if hasattr(version_service.db, "update_version_status"):
                version_service.db.update_version_status(v.id, "queued")
            v.build_status = "queued"
            actor, tenant = get_actor_info(request)
            audit_logger.log_event("version.build", resource_id=version_id, status_code=202, actor=actor, tenant_id=tenant)
            return JSONResponse(format_version_response(v), status_code=202)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    async def get_version_context(request: Request) -> JSONResponse:
        active_services = getattr(request.app.state, "services", services)
        context_service = active_services.get("context_service")
        if not context_service:
            return JSONResponse({"error": "Context service not configured"}, status_code=503)

        version_id = request.path_params.get("id")
        tenant_id, is_admin = get_tenant_context(request)
        version_service = active_services.get("version_service")
        if version_service and hasattr(version_service, "get_version"):
            v = version_service.get_version(version_id, owner_scope=None if is_admin else tenant_id)
            if not v:
                return JSONResponse({"error": "Version not found or unauthorized"}, status_code=404)

        query = request.query_params.get("query")
        if not query:
            return JSONResponse({"error": "Missing 'query' parameter"}, status_code=400)

        try:
            max_items = int(request.query_params.get("max_items", "10"))
        except ValueError:
            return JSONResponse({"error": "Invalid 'max_items'"}, status_code=400)

        try:
            max_bytes = int(request.query_params.get("max_bytes", "50000"))
        except ValueError:
            return JSONResponse({"error": "Invalid 'max_bytes'"}, status_code=400)

        try:
            target_owner = None if is_admin else tenant_id
            if target_owner and target_owner != "default":
                result = context_service.get_context(
                    version_id, query, owner_scope=target_owner, max_items=max_items, max_bytes=max_bytes
                )
            else:
                result = context_service.get_context(
                    version_id, query, max_items=max_items, max_bytes=max_bytes
                )
            actor, tenant = get_actor_info(request)
            audit_logger.log_event("version.context_read", resource_id=version_id, status_code=200, actor=actor, tenant_id=tenant)
            return JSONResponse(result)
        except ValueError as e:
            if "not found" in str(e) or "unauthorized" in str(e):
                return JSONResponse({"error": str(e)}, status_code=404)
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    routes = [
        ("/openapi.json", openapi_schema_endpoint, ["GET"]),
        ("/docs", docs_swagger_endpoint, ["GET"]),
        ("/auth/mcp-token", auth_mcp_token, ["POST"]),
        ("/auth/login", auth_login, ["POST"]),
        ("/auth/refresh", auth_refresh, ["POST"]),
        ("/projects", create_project, ["POST"]),
        ("/projects", list_projects, ["GET"]),
        ("/projects/{id}", get_project, ["GET"]),
        ("/projects/{id}", delete_project, ["DELETE"]),
        ("/projects/{id}/sync", sync_version, ["POST"]),
        ("/projects/{id}/versions", list_versions, ["GET"]),
        ("/projects/{id}/versions", create_version, ["POST"]),
        ("/projects/{id}/versions/archive", upload_archive, ["POST"]),
        ("/versions/{id}", get_version, ["GET"]),
        ("/versions/{id}/retry", retry_version, ["POST"]),
        ("/versions/{id}/cancel", cancel_version, ["POST"]),
        ("/versions/{id}/build", build_version, ["POST"]),
        ("/versions/{id}/context", get_version_context, ["GET"]),
    ]

    for path, endpoint, methods in routes:
        if hasattr(app, "custom_route"):
            app.custom_route(path, methods=methods)(endpoint)
        else:
            app.add_route(path, endpoint, methods=methods)
