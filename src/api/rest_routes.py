import json
import logging
from typing import Any, Dict

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from ..models import ProjectVersion

logger = logging.getLogger(__name__)


OPENAPI_PATH = "/openapi.json"
SWAGGER_UI_PATH = "/docs"


def _json_content(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Return the OpenAPI content declaration shared by JSON responses."""
    return {"application/json": {"schema": schema}}


def build_openapi_schema() -> Dict[str, Any]:
    """Build the public OpenAPI contract for the project-version REST API.

    The REST handlers deliberately use Starlette primitives instead of a model
    framework, so their request and response contract is declared here rather
    than inferred.  Keeping this schema next to the handlers makes Swagger a
    reviewed API contract instead of a best-effort reflection of implementation
    details.
    """
    ref = lambda name: {"$ref": f"#/components/schemas/{name}"}
    error = {"description": "The request is invalid or cannot be completed.", "content": _json_content(ref("Error"))}
    not_found = {"description": "No project or version exists for the supplied identifier.", "content": _json_content(ref("Error"))}
    project_id = {
        "name": "id",
        "in": "path",
        "required": True,
        "description": "Stable 16-character identifier of the registered project.",
        "schema": {"type": "string", "example": "f4d1e2a3b4c5d6e7"},
    }
    version_id = {
        "name": "id",
        "in": "path",
        "required": True,
        "description": "Stable identifier of the immutable project version/build.",
        "schema": {"type": "string", "example": "e7d6c5b4a3e2d1f4"},
    }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "CodeBadger Project Version API",
            "version": "0.6.2-beta",
            "description": (
                "REST API for registering Git projects, creating immutable source "
                "versions, and observing or controlling their durable CPG builds. "
                "A successful creation or upload queues a build asynchronously; poll "
                "the version endpoints for lifecycle status."
            ),
        },
        "tags": [
            {"name": "Projects", "description": "Register and manage repository sources."},
            {"name": "Versions", "description": "Create and manage immutable source snapshots and CPG builds."},
        ],
        "paths": {
            "/projects": {
                "post": {
                    "tags": ["Projects"], "operationId": "createProject", "summary": "Register a Git project",
                    "description": "Validates and canonicalizes the repository URL. Supplying a credential stores it encrypted; it is never returned by this API.",
                    "requestBody": {"required": True, "content": _json_content(ref("CreateProjectRequest"))},
                    "responses": {"201": {"description": "Project was created or already exists.", "content": _json_content(ref("Project"))}, "400": error},
                },
                "get": {
                    "tags": ["Projects"], "operationId": "listProjects", "summary": "List projects in an owner scope",
                    "parameters": [{"name": "owner_scope", "in": "query", "description": "Tenant/owner namespace used to isolate projects. Defaults to `default`.", "schema": {"type": "string", "default": "default"}}],
                    "responses": {"200": {"description": "Projects ordered by newest first.", "content": _json_content({"type": "array", "items": ref("Project")})}},
                },
            },
            "/projects/{id}": {
                "get": {"tags": ["Projects"], "operationId": "getProject", "summary": "Get one project", "parameters": [project_id], "responses": {"200": {"description": "Registered project.", "content": _json_content(ref("Project"))}, "404": not_found}},
                "delete": {"tags": ["Projects"], "operationId": "deleteProject", "summary": "Delete one project", "description": "Removes the project in the default owner scope.", "parameters": [project_id], "responses": {"200": {"description": "Project was deleted.", "content": _json_content(ref("DeletedResponse"))}, "404": not_found}},
            },
            "/projects/{id}/versions/update": {
                "post": {
                    "tags": ["Versions"], "operationId": "syncProjectVersion", "summary": "Sync a Git branch into an immutable version",
                    "description": "Fetches the requested branch (or the project's default branch), creates a snapshot for its resolved commit, and queues a CPG build only when the version is new.",
                    "parameters": [project_id], "requestBody": {"required": False, "content": _json_content(ref("SyncVersionRequest"))},
                    "responses": {"200": {"description": "Existing or newly created version and the sync result.", "content": _json_content(ref("SyncVersionResponse"))}, "400": error},
                },
            },
            "/projects/{id}/versions": {
                "post": {
                    "tags": ["Versions"], "operationId": "uploadProjectVersion", "summary": "Upload an archived source snapshot",
                    "description": "Accepts `.zip`, `.tar`, `.tar.gz`, or `.tgz`. Archives are checked for traversal, links, 10,000-file and 500 MB expanded-size limits before a CPG build is queued.",
                    "parameters": [project_id],
                    "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": ref("UploadVersionRequest")}}},
                    "responses": {"200": {"description": "Existing or newly created archive version and upload result.", "content": _json_content(ref("UploadVersionResponse"))}, "400": error},
                },
            },
            "/versions": {
                "get": {
                    "tags": ["Versions"], "operationId": "listVersions", "summary": "List versions for a project",
                    "parameters": [{"name": "project_id", "in": "query", "required": True, "description": "Identifier of the project whose immutable versions should be returned.", "schema": {"type": "string"}}],
                    "responses": {"200": {"description": "Versions ordered by newest first.", "content": _json_content({"type": "array", "items": ref("Version")})}, "400": error},
                },
            },
            "/versions/{id}": {
                "get": {"tags": ["Versions"], "operationId": "getVersion", "summary": "Get one version and build status", "parameters": [version_id], "responses": {"200": {"description": "Immutable version with durable build lifecycle fields.", "content": _json_content(ref("Version"))}, "404": not_found}},
            },
            "/versions/{id}/retry": {
                "post": {"tags": ["Versions"], "operationId": "retryVersionBuild", "summary": "Retry a failed or cancelled build", "description": "Idempotent for queued, building, or loading versions. Ready versions cannot be retried.", "parameters": [version_id], "responses": {"200": {"description": "Current version and retry result.", "content": _json_content(ref("RetryVersionResponse"))}, "400": error}},
            },
            "/versions/{id}/cancel": {
                "post": {"tags": ["Versions"], "operationId": "cancelVersionBuild", "summary": "Cancel an in-progress build", "description": "Cancels queued, building, or loading work. Ready and failed versions cannot be cancelled.", "parameters": [version_id], "responses": {"200": {"description": "Version after cancellation attempt.", "content": _json_content(ref("CancelVersionResponse"))}, "400": error}},
            },
        },
        "components": {"schemas": {
            "Error": {"type": "object", "required": ["error"], "properties": {"error": {"type": "string", "description": "Human-readable validation or operation error."}}},
            "Project": {"type": "object", "required": ["id", "provider", "remote_url", "default_branch", "owner_scope", "created_at", "updated_at"], "properties": {"id": {"type": "string", "description": "Deterministic project identifier."}, "provider": {"type": "string", "description": "Git hosting provider inferred from the remote URL."}, "remote_url": {"type": "string", "format": "uri", "description": "Canonical repository URL, with a trailing `.git` removed."}, "default_branch": {"type": "string", "description": "Branch used when sync does not specify one."}, "owner_scope": {"type": "string", "description": "Owner namespace for project isolation."}, "created_at": {"type": "string", "format": "date-time"}, "updated_at": {"type": "string", "format": "date-time"}}},
            "CreateProjectRequest": {"type": "object", "required": ["remote_url"], "properties": {"remote_url": {"type": "string", "format": "uri", "description": "HTTP(S) Git repository URL to register."}, "default_branch": {"type": "string", "default": "main", "description": "Valid Git branch name used for sync when `branch` is omitted."}, "owner_scope": {"type": "string", "default": "default", "description": "Tenant/owner namespace in which to create the project."}, "credential": {"type": "string", "writeOnly": True, "description": "Optional GitHub token for private-repository access. Stored encrypted and never returned."}}},
            "Version": {"type": "object", "required": ["id", "project_id", "commit_sha", "branch", "status", "phase", "queue_position", "elapsed_ms", "retry_count", "created_at", "updated_at"], "properties": {"id": {"type": "string", "description": "Deterministic immutable version identifier."}, "project_id": {"type": "string", "description": "Parent project identifier."}, "commit_sha": {"type": "string", "description": "Resolved Git commit SHA or archive-derived identifier."}, "branch": {"type": "string", "description": "Git branch, or `upload` for archive ingestion."}, "status": {"type": "string", "enum": ["queued", "building", "loading", "ready", "failed", "cancelled"], "description": "Current CPG build lifecycle state."}, "phase": {"type": "string", "description": "Backward-compatible alias of `status`."}, "queue_position": {"type": "integer", "minimum": 0, "description": "Current position in the build queue; zero means active or not queued."}, "elapsed_ms": {"type": "integer", "minimum": 0, "description": "Recorded build duration in milliseconds."}, "retry_count": {"type": "integer", "minimum": 0, "description": "Number of explicit or recovery retry attempts."}, "error": {"type": ["object", "null"], "description": "Sanitized build error when the status is `failed`."}, "created_at": {"type": "string", "format": "date-time"}, "updated_at": {"type": "string", "format": "date-time"}}},
            "SyncVersionRequest": {"type": "object", "properties": {"branch": {"type": "string", "description": "Optional valid Git branch. Defaults to the project's `default_branch`."}, "build_config": {"type": "object", "additionalProperties": True, "description": "Optional build configuration. It participates in immutable-version identity."}}},
            "UploadVersionRequest": {"type": "object", "required": ["file"], "properties": {"file": {"type": "string", "format": "binary", "description": "Source archive in ZIP, TAR, TAR.GZ, or TGZ format."}}},
            "SyncVersionResponse": {"type": "object", "required": ["version", "sync_status"], "properties": {"version": ref("Version"), "sync_status": {"type": "string", "enum": ["created", "unchanged"], "description": "Whether the sync created a new immutable version."}}},
            "UploadVersionResponse": {"type": "object", "required": ["version", "upload_status"], "properties": {"version": ref("Version"), "upload_status": {"type": "string", "enum": ["created", "unchanged"], "description": "Whether the archive produced a new immutable version."}}},
            "RetryVersionResponse": {"type": "object", "required": ["version", "retry_status"], "properties": {"version": ref("Version"), "retry_status": {"type": "string", "enum": ["queued", "already_active"], "description": "Whether work was queued or an active build was reused."}}},
            "CancelVersionResponse": {"type": "object", "required": ["version", "cancelled"], "properties": {"version": ref("Version"), "cancelled": {"type": "boolean", "description": "True when the state was changed to `cancelled`."}}},
            "DeletedResponse": {"type": "object", "required": ["status"], "properties": {"status": {"type": "string", "enum": ["deleted"], "description": "Deletion confirmation."}}},
        }},
    }


async def openapi_schema(_: Request) -> JSONResponse:
    """Serve the machine-readable OpenAPI contract used by Swagger UI."""
    return JSONResponse(build_openapi_schema())


async def swagger_ui(_: Request) -> HTMLResponse:
    """Serve a lightweight Swagger UI that reads the local OpenAPI contract."""
    return HTMLResponse(
        """<!doctype html><html><head><title>CodeBadger API Docs</title>
<link rel=\"stylesheet\" href=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui.css\"></head>
<body><div id=\"swagger-ui\"></div><script src=\"https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js\"></script>
<script>SwaggerUIBundle({url: '/openapi.json', dom_id: '#swagger-ui', persistAuthorization: true});</script>
</body></html>""",
    )


def format_version_response(version: ProjectVersion, queue_pos: int = 0) -> Dict[str, Any]:
    meta = version.build_metadata if isinstance(version.build_metadata, dict) else {}
    return {
        "id": version.id,
        "project_id": version.project_id,
        "commit_sha": version.commit_sha,
        "branch": version.branch,
        "status": version.build_status,
        "phase": version.build_status,
        "queue_position": meta.get("queue_position", queue_pos),
        "elapsed_ms": meta.get("elapsed_ms", 0),
        "retry_count": meta.get("retry_count", 0),
        "error": meta.get("error"),
        "created_at": version.created_at.isoformat() if hasattr(version.created_at, "isoformat") else str(version.created_at),
        "updated_at": version.updated_at.isoformat() if hasattr(version.updated_at, "isoformat") else str(version.updated_at),
    }



async def get_version_context(request: Request) -> JSONResponse:
    services = request.app.state.services
    context_service = services.get("context_service")
    if not context_service:
        return JSONResponse({"error": "Context service not configured"}, status_code=503)
        
    version_id = request.path_params.get("id")
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
        # Secure: raw CPGQL is not exposed, we only pass a generic string query 
        result = context_service.get_context(version_id, query, max_items=max_items, max_bytes=max_bytes)
        return JSONResponse(result)
    except ValueError as e:
        if "not found" in str(e) or "unauthorized" in str(e):
            return JSONResponse({"error": str(e)}, status_code=404)
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

def register_rest_routes(app: Any, services: Dict[str, Any]) -> None:
    """Register REST and documentation routes on Starlette or FastMCP.

    Tests use a plain Starlette instance.  Production passes the FastMCP server,
    whose ``custom_route`` API is the supported way to expose HTTP routes beside
    its MCP transport.
    """
    async def create_project(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        data = await request.json()
        try:
            p = version_service.register_project(
                remote_url=data.get("remote_url"),
                default_branch=data.get("default_branch", "main"),
                owner_scope=data.get("owner_scope", "default"),
                credential=data.get("credential"),
            )
            return JSONResponse(p.to_dict(), status_code=201)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def list_projects(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        owner_scope = request.query_params.get("owner_scope", "default")
        projects = version_service.list_projects(owner_scope=owner_scope)
        return JSONResponse([p.to_dict() for p in projects])

    async def get_project(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        project_id = request.path_params["id"]
        p = version_service.get_project(project_id)
        if not p:
            return JSONResponse({"error": "Project not found"}, status_code=404)
        return JSONResponse(p.to_dict())

    async def delete_project(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        project_id = request.path_params["id"]
        ok = version_service.delete_project(project_id)
        if not ok:
            return JSONResponse({"error": "Project not found"}, status_code=404)
        return JSONResponse({"status": "deleted"})

    async def sync_version(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        git_sync_service = services["git_sync_service"]
        project_id = request.path_params["id"]
        data = await request.json() if request.headers.get("content-type") == "application/json" else {}
        branch = data.get("branch")
        build_config = data.get("build_config")
        try:
            version_dict, status = await git_sync_service.sync_project_branch(
                project_id=project_id,
                branch=branch,
                build_config=build_config,
            )
            v = version_service.get_version(version_dict["id"])
            return JSONResponse({"version": format_version_response(v), "sync_status": status})
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def upload_version(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        archive_service = services["archive_service"]
        project_id = request.path_params["id"]
        form = await request.form()
        archive_file = form.get("file")
        filename = getattr(archive_file, "filename", "upload.zip")
        content = await archive_file.read()

        try:
            version_dict, status = archive_service.process_archive_upload(
                project_id=project_id,
                archive_bytes=content,
                filename=filename,
            )
            v = version_service.get_version(version_dict["id"])
            return JSONResponse({"version": format_version_response(v), "upload_status": status})
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def list_versions(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        project_id = request.query_params.get("project_id")
        if not project_id:
            return JSONResponse({"error": "project_id query param required"}, status_code=400)
        versions = version_service.list_versions(project_id)
        return JSONResponse([format_version_response(v) for v in versions])

    async def get_version(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        version_id = request.path_params["id"]
        v = version_service.get_version(version_id)
        if not v:
            return JSONResponse({"error": "Version not found"}, status_code=404)
        return JSONResponse(format_version_response(v))

    async def retry_version(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        cpg_queue = services.get("cpg_queue")
        version_id = request.path_params["id"]
        try:
            v, status = version_service.retry_version_build(version_id, queue=cpg_queue)
            return JSONResponse({"version": format_version_response(v), "retry_status": status})
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    async def cancel_version(request: Request) -> JSONResponse:
        version_service = services["version_service"]
        version_id = request.path_params["id"]
        try:
            v, ok = version_service.cancel_version_build(version_id)
            return JSONResponse({"version": format_version_response(v), "cancelled": ok})
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    routes = [
        Route("/projects", create_project, methods=["POST"]),
        Route("/projects", list_projects, methods=["GET"]),
        Route("/projects/{id}", get_project, methods=["GET"]),
        Route("/projects/{id}", delete_project, methods=["DELETE"]),
        Route("/projects/{id}/versions/update", sync_version, methods=["POST"]),
        Route("/projects/{id}/versions", upload_version, methods=["POST"]),
        Route("/versions", list_versions, methods=["GET"]),
        Route("/versions/{id}", get_version, methods=["GET"]),
        Route("/versions/{id}/retry", retry_version, methods=["POST"]),
        Route("/versions/{id}/cancel", cancel_version, methods=["POST"]),
        Route("/versions/{id}/context", get_version_context, methods=["GET"]),
        Route(OPENAPI_PATH, openapi_schema, methods=["GET"], include_in_schema=False),
        Route(SWAGGER_UI_PATH, swagger_ui, methods=["GET"], include_in_schema=False),
    ]

    # FastMCP's public custom_route API keeps these routes available on the
    # generated HTTP app. Do not reach into its private Starlette internals.
    if hasattr(app, "custom_route"):
        for route in routes:
            app.custom_route(route.path, methods=list(route.methods))(route.endpoint)
        return

    # Plain Starlette app used by integration tests and embedding applications.
    if hasattr(app, "routes"):
        app.routes.extend(routes)
    elif hasattr(app, "_app") and hasattr(app._app, "routes"):
        app._app.routes.extend(routes)
    else:
        raise TypeError("app must be a Starlette application or FastMCP server")
