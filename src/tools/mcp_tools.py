"""
MCP Tool Definitions for Joern MCP Server
"""

import asyncio
import logging
import os
import re
import shutil
import time
from datetime import datetime, UTC
from typing import Optional, Dict, Any

from ..models import SessionStatus
from ..exceptions import (
    SessionNotFoundError,
    SessionNotReadyError,
    ValidationError,
    ResourceLimitError,
    QueryExecutionError,
)
from ..utils.validators import (
    validate_source_type,
    validate_language,
    validate_session_id,
    validate_github_url,
    validate_local_path,
    validate_cpgql_query,
)

logger = logging.getLogger(__name__)


def get_cpg_cache_key(source_type: str, source_path: str, language: str) -> str:
    """
    Generate a deterministic CPG cache key based on source type, path, and language.
    This is separate from session IDs - used only for CPG caching.
    """
    import hashlib

    if source_type == "github":
        # Extract owner/repo from GitHub URL
        # Handle URLs like: https://github.com/owner/repo or https://github.com/owner/repo.git
        if "github.com/" in source_path:
            parts = source_path.split("github.com/")[-1].split("/")
            if len(parts) >= 2:
                owner = parts[0]
                repo = parts[1].replace(".git", "")  # Remove .git suffix if present
                identifier = f"github:{owner}/{repo}"
            else:
                # Fallback to full path if parsing fails
                identifier = f"github:{source_path}"
        else:
            identifier = f"github:{source_path}"
    else:
        # For local paths, convert to absolute path for consistency
        source_path = os.path.abspath(source_path)
        identifier = f"local:{source_path}"

    hash_digest = hashlib.sha256(identifier.encode()).hexdigest()[:16]

    return hash_digest


def get_cpg_cache_path(cache_key: str, playground_path: str) -> str:
    """
    Generate a deterministic CPG cache path based on cache key.
    """
    # Create CPG filename using cache key only (no language)
    cpg_filename = f"cpg_{cache_key}.bin"
    cpg_cache_path = os.path.join(playground_path, "cpgs", cpg_filename)

    return cpg_cache_path


def register_tools(mcp, services: dict):
    """Register all MCP tools with the FastMCP server"""

    @mcp.tool()
    async def create_cpg_session(
        source_type: str,
        source_path: str,
        language: str,
        github_token: Optional[str] = None,
        branch: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Creates a new CPG analysis session.

        This tool initiates CPG generation for a codebase. For GitHub repositories,
        it clones the repo first. For local paths, it uses the existing directory.
        The CPG generation happens asynchronously in a Docker container.

        Args:
            source_type: Either "local" or "github"
            source_path: For local: absolute path to source directory
                        For github: full GitHub URL (e.g., https://github.com/user/repo)
            language: Programming language - one of: java, c, cpp, javascript, python, go,
                        kotlin, csharp, ghidra, jimple, php, ruby, swift
            github_token: GitHub Personal Access Token for private repositories (optional)
            branch: Specific git branch to checkout (optional, defaults to default branch)

        Returns:
            {
                "session_id": "unique-session-id",
                "status": "initializing" | "generating",
                "message": "CPG generation started",
                "estimated_time": "2-5 minutes"
            }

        Examples:
            # GitHub repository
            create_cpg_session(
                source_type="github",
                source_path="https://github.com/joernio/sample-repo",
                language="java"
            )

            # Local directory
            create_cpg_session(
                source_type="local",
                source_path="/home/user/projects/myapp",
                language="python"
            )
        """
        try:
            # Validate inputs
            validate_source_type(source_type)
            validate_language(language)

            session_manager = services["session_manager"]
            git_manager = services["git_manager"]
            docker_orch = services["docker"]
            cpg_generator = services["cpg_generator"]
            storage_config = services["config"].storage

            # Generate CPG cache key for checking existing CPGs
            cpg_cache_key = get_cpg_cache_key(source_type, source_path, language)

            # Get playground path (absolute)
            playground_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "playground")
            )

            # Check if CPG already exists in cache BEFORE creating session
            cpg_cache_path = get_cpg_cache_path(cpg_cache_key, playground_path)
            cpg_exists = os.path.exists(cpg_cache_path)

            if cpg_exists:
                logger.info(f"Found existing CPG in cache: {cpg_cache_path}")

                # Create session with random UUID (not deterministic)
                session = await session_manager.create_session(
                    source_type=source_type,
                    source_path=source_path,
                    language=language,
                    options={"github_token": github_token, "branch": branch},
                )

                # Handle source preparation (still need to copy/clone for the session)
                workspace_path = os.path.join(
                    storage_config.workspace_root, "repos", session.id
                )

                # Use cache key for codebase directory
                target_path = os.path.join(playground_path, "codebases", cpg_cache_key)

                if source_type == "github":
                    validate_github_url(source_path)
                    # Clone to playground/codebases with cache key
                    if not os.path.exists(target_path):
                        os.makedirs(target_path, exist_ok=True)

                        await git_manager.clone_repository(
                            repo_url=source_path,
                            target_path=target_path,
                            branch=branch,
                            token=github_token,
                        )
                    # Path inside container
                    container_source_path = f"/playground/codebases/{cpg_cache_key}"
                else:
                    # Copy to playground/codebases with cache key if not exists
                    validate_local_path(source_path)

                    # Validate the path exists on the host system
                    if not os.path.isabs(source_path):
                        raise ValidationError("Local path must be absolute")

                    # Detect if we're running in a container
                    in_container = (
                        os.path.exists("/.dockerenv")
                        or os.path.exists("/run/.containerenv")
                        or os.path.exists("/host/home/")
                    )

                    container_check_path = source_path
                    if in_container and source_path.startswith("/home/"):
                        container_check_path = source_path.replace(
                            "/home/", "/host/home/", 1
                        )
                        logger.info(
                            f"Running in container, translated path: {source_path} -> {container_check_path}"
                        )

                    if not os.path.exists(container_check_path):
                        raise ValidationError(f"Path does not exist: {source_path}")
                    if not os.path.isdir(container_check_path):
                        raise ValidationError(f"Path is not a directory: {source_path}")

                    # Copy to playground/codebases with cache key if not exists
                    if not os.path.exists(target_path):
                        os.makedirs(target_path, exist_ok=True)

                        logger.info(
                            f"Copying local source from {container_check_path} to {target_path}"
                        )

                        for item in os.listdir(container_check_path):
                            src_item = os.path.join(container_check_path, item)
                            dst_item = os.path.join(target_path, item)

                            if os.path.isdir(src_item):
                                shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                            else:
                                shutil.copy2(src_item, dst_item)

                    container_source_path = f"/playground/codebases/{cpg_cache_key}"

                # Create workspace directory for CPG storage
                os.makedirs(workspace_path, exist_ok=True)

                # Copy cached CPG to workspace
                cpg_path = os.path.join(workspace_path, "cpg.bin")
                shutil.copy2(cpg_cache_path, cpg_path)

                # Start Docker container with playground mount
                container_id = await docker_orch.start_container(
                    session_id=session.id,
                    workspace_path=workspace_path,
                    playground_path=playground_path,
                )

                # Register container with CPG generator
                cpg_generator.register_session_container(session.id, container_id)

                # Update session as ready immediately
                await session_manager.update_session(
                    session_id=session.id,
                    container_id=container_id,
                    status=SessionStatus.READY.value,
                    cpg_path=cpg_path,
                )

                # Map container to session
                redis_client = services["redis"]
                await redis_client.set_container_mapping(
                    container_id, session.id, services["config"].sessions.ttl
                )

                return {
                    "session_id": session.id,
                    "status": SessionStatus.READY.value,
                    "message": "Loaded existing CPG from cache",
                    "cached": True,
                }
            else:
                logger.info("No cached CPG found, will generate new one")

                # Create session with random UUID
                session = await session_manager.create_session(
                    source_type=source_type,
                    source_path=source_path,
                    language=language,
                    options={"github_token": github_token, "branch": branch},
                )

                # Handle source preparation
                workspace_path = os.path.join(
                    storage_config.workspace_root, "repos", session.id
                )

                if source_type == "github":
                    validate_github_url(source_path)
                    # Clone to playground/codebases with cache key
                    target_path = os.path.join(
                        playground_path, "codebases", cpg_cache_key
                    )
                    if not os.path.exists(target_path):
                        os.makedirs(target_path, exist_ok=True)

                        await git_manager.clone_repository(
                            repo_url=source_path,
                            target_path=target_path,
                            branch=branch,
                            token=github_token,
                        )
                    # Path inside container
                    container_source_path = f"/playground/codebases/{cpg_cache_key}"
                else:
                    # For local paths, check if it's relative to playground/codebases
                    if (
                        source_path.startswith("playground/codebases/")
                        or "/playground/codebases/" in source_path
                    ):
                        # Already in playground, use directly
                        if not os.path.isabs(source_path):
                            source_path = os.path.abspath(source_path)

                        if not os.path.exists(source_path):
                            raise ValidationError(f"Path does not exist: {source_path}")
                        if not os.path.isdir(source_path):
                            raise ValidationError(
                                f"Path is not a directory: {source_path}"
                            )

                        # Get relative path from playground root
                        rel_path = os.path.relpath(source_path, playground_path)
                        container_source_path = f"/playground/{rel_path}"

                        logger.info(
                            f"Using local source from playground: {source_path} -> {container_source_path}"
                        )
                    else:
                        # Copy to playground/codebases with cache key if not exists

                        # Validate the path exists on the host system
                        if not os.path.isabs(source_path):
                            raise ValidationError(
                                "Local path must be absolute or relative to playground/codebases"
                            )

                        # Detect if we're running in a container
                        in_container = (
                            os.path.exists("/.dockerenv")
                            or os.path.exists("/run/.containerenv")
                            or os.path.exists("/host/home/")
                        )

                        container_check_path = source_path
                        if in_container and source_path.startswith("/home/"):
                            container_check_path = source_path.replace(
                                "/home/", "/host/home/", 1
                            )
                            logger.info(
                                f"Running in container, translated path: {source_path} -> {container_check_path}"
                            )

                        if not os.path.exists(container_check_path):
                            raise ValidationError(f"Path does not exist: {source_path}")
                        if not os.path.isdir(container_check_path):
                            raise ValidationError(
                                f"Path is not a directory: {source_path}"
                            )

                        # Copy to playground/codebases with cache key if not exists
                        target_path = os.path.join(
                            playground_path, "codebases", cpg_cache_key
                        )
                        if not os.path.exists(target_path):
                            os.makedirs(target_path, exist_ok=True)

                            logger.info(
                                f"Copying local source from {container_check_path} to {target_path}"
                            )

                            for item in os.listdir(container_check_path):
                                src_item = os.path.join(container_check_path, item)
                                dst_item = os.path.join(target_path, item)

                                if os.path.isdir(src_item):
                                    shutil.copytree(
                                        src_item, dst_item, dirs_exist_ok=True
                                    )
                                else:
                                    shutil.copy2(src_item, dst_item)

                        container_source_path = f"/playground/codebases/{cpg_cache_key}"

                # Create workspace directory for CPG storage
                os.makedirs(workspace_path, exist_ok=True)

                # Ensure playground/cpgs directory exists
                cpgs_dir = os.path.join(playground_path, "cpgs")
                os.makedirs(cpgs_dir, exist_ok=True)

                # Start Docker container with playground mount
                container_id = await docker_orch.start_container(
                    session_id=session.id,
                    workspace_path=workspace_path,
                    playground_path=playground_path,
                )

                # Register container with CPG generator
                cpg_generator.register_session_container(session.id, container_id)

                # Update session with container ID
                await session_manager.update_session(
                    session_id=session.id,
                    container_id=container_id,
                    status=SessionStatus.GENERATING.value,
                )

                # Map container to session
                redis_client = services["redis"]
                await redis_client.set_container_mapping(
                    container_id, session.id, services["config"].sessions.ttl
                )

                # Start async CPG generation
                cpg_path = os.path.join(workspace_path, "cpg.bin")

                # Create a task that will also cache the CPG after generation
                async def generate_and_cache():
                    await cpg_generator.generate_cpg(
                        session_id=session.id,
                        source_path=container_source_path,
                        language=language,
                    )
                    # Cache the CPG after successful generation
                    if os.path.exists(cpg_path):
                        shutil.copy2(cpg_path, cpg_cache_path)
                        logger.info(f"Cached CPG to: {cpg_cache_path}")

                asyncio.create_task(generate_and_cache())

                return {
                    "session_id": session.id,
                    "status": SessionStatus.GENERATING.value,
                    "message": "CPG generation started",
                    "estimated_time": "2-5 minutes",
                    "cached": False,
                }

        except ValidationError as e:
            logger.error(f"Validation error: {e}")
            return {
                "success": False,
                "error": {"code": "VALIDATION_ERROR", "message": str(e)},
            }
        except ResourceLimitError as e:
            logger.error(f"Resource limit error: {e}")
            return {
                "success": False,
                "error": {"code": "RESOURCE_LIMIT_EXCEEDED", "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Failed to create session: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Failed to create session",
                    "details": str(e),
                },
            }

    @mcp.tool()
    async def run_cpgql_query_async(
        session_id: str, query: str, timeout: int = 30, limit: Optional[int] = 150, offset: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes a CPGQL query asynchronously and returns a query ID for status tracking.

        This tool starts a CPGQL query execution and returns immediately with a query ID.
        Use get_query_status to check progress and get_query_result to retrieve results.
        Results are automatically saved to JSON files in the container.

        Args:
            session_id: The session ID returned from create_cpg_session
            query: CPGQL query string (automatically converted to JSON output)
            timeout: Maximum execution time in seconds (default: 30)
            limit: Maximum number of results to return (default: 150)
            offset: Number of results to skip before returning (default: None, meaning start from beginning)

        Returns:
            {
                "success": true,
                "query_id": "query-uuid-123",
                "status": "pending",
                "message": "Query started successfully"
            }
        """
        try:
            # Validate inputs
            validate_session_id(session_id)
            validate_cpgql_query(query)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            # Get and validate session
            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(
                    f"Session is in '{session.status}' status. "
                    f"Wait for CPG generation to complete."
                )

            # Update last accessed time
            await session_manager.touch_session(session_id)

            # Start async query execution
            query_id = await query_executor.execute_query_async(
                session_id=session_id,
                query=query,
                timeout=timeout,
                limit=limit,
                offset=offset,
            )

            return {
                "success": True,
                "query_id": query_id,
                "status": "pending",
                "message": "Query started successfully",
            }

        except SessionNotFoundError as e:
            logger.error(f"Session not found: {e}")
            return {
                "success": False,
                "error": {"code": "SESSION_NOT_FOUND", "message": str(e)},
            }
        except SessionNotReadyError as e:
            logger.warning(f"Session not ready: {e}")
            return {
                "success": False,
                "error": {"code": "SESSION_NOT_READY", "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Failed to start query",
                    "details": str(e),
                },
            }

    @mcp.tool()
    async def get_query_status(query_id: str) -> Dict[str, Any]:
        """
        Get the status of an asynchronously running query.

        Check if a query started with run_cpgql_query_async is still running,
        completed, or failed. Provides execution time and error information.

        Args:
            query_id: The query ID returned from run_cpgql_query_async

        Returns:
            {
                "query_id": "query-uuid-123",
                "status": "running" | "completed" | "failed" | "pending",
                "session_id": "session-123",
                "query": "cpg.method.name.toJson",
                "created_at": 1697524800.0,
                "execution_time": 1.23,
                "error": null
            }
        """
        try:
            query_executor = services["query_executor"]

            status_info = await query_executor.get_query_status(query_id)

            return {"success": True, **status_info}

        except QueryExecutionError as e:
            logger.error(f"Query status error: {e}")
            return {
                "success": False,
                "error": {"code": "QUERY_NOT_FOUND", "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def get_query_result(query_id: str) -> Dict[str, Any]:
        """
        Get the result of a completed query.

        Retrieve the JSON results from a query that has completed execution.
        The query must be in "completed" status to retrieve results.

        Args:
            query_id: The query ID returned from run_cpgql_query_async

        Returns:
            {
                "success": true,
                "data": [
                    {"property1": "value1", "property2": "value2"},
                    ...
                ],
                "row_count": 10,
                "execution_time": 1.23
            }
        """
        try:
            query_executor = services["query_executor"]

            result = await query_executor.get_query_result(query_id)

            return {
                "success": result.success,
                "data": result.data,
                "row_count": result.row_count,
                "execution_time": result.execution_time,
                "error": result.error,
            }

        except QueryExecutionError as e:
            logger.error(f"Query result error: {e}")
            return {
                "success": False,
                "error": {"code": "QUERY_ERROR", "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def cleanup_queries(
        session_id: Optional[str] = None, max_age_hours: int = 1
    ) -> Dict[str, Any]:
        """
        Clean up old completed queries to free resources.

        Remove old query results and temporary files from completed or failed queries.
        Helps maintain system performance by cleaning up accumulated query data.

        Args:
            session_id: Only cleanup queries for specific session (optional)
            max_age_hours: Remove queries older than this many hours (default: 1)

        Returns:
            {
                "success": true,
                "cleaned_up": 3,
                "message": "Cleaned up 3 old queries"
            }
        """
        try:
            query_executor = services["query_executor"]

            max_age_seconds = max_age_hours * 3600

            if session_id:
                # Get queries for specific session
                queries = await query_executor.list_queries(session_id)
                cleaned_count = 0

                for query_id, query_info in queries.items():
                    if query_info["status"] in ["completed", "failed"]:
                        age = time.time() - query_info.get(
                            "completed_at", query_info["created_at"]
                        )
                        if age > max_age_seconds:
                            await query_executor.cleanup_query(query_id)
                            cleaned_count += 1
            else:
                # Cleanup all old queries
                await query_executor.cleanup_old_queries(max_age_seconds)
                # We don't have an exact count for this method
                cleaned_count = "multiple"

            return {
                "success": True,
                "cleaned_up": cleaned_count,
                "message": f"Cleaned up {cleaned_count} old queries",
            }

        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def run_cpgql_query(
        session_id: str, query: str, timeout: int = 30, limit: Optional[int] = 150, offset: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes a CPGQL query synchronously on a loaded CPG.

        This tool runs CPGQL queries against the Code Property Graph and waits
        for completion before returning results. For long-running queries,
        consider using run_cpgql_query_async instead.

        Args:
            session_id: The session ID returned from create_cpg_session
            query: CPGQL query string (automatically converted to JSON output)
            timeout: Maximum execution time in seconds (default: 30)
            limit: Maximum number of results to return (default: 150)
            offset: Number of results to skip before returning (default: None, meaning start from beginning)

        Returns:
            {
                "success": true,
                "data": [
                    {"property1": "value1", "property2": "value2"},
                    ...
                ],
                "row_count": 10,
                "execution_time": 1.23
            }
        """
        try:
            # Validate inputs
            validate_session_id(session_id)
            validate_cpgql_query(query)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            # Get and validate session
            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(
                    f"Session is in '{session.status}' status. "
                    f"Wait for CPG generation to complete."
                )

            # Update last accessed time
            await session_manager.touch_session(session_id)

            # Execute query synchronously
            # Use container path for CPG instead of host path
            container_cpg_path = "/workspace/cpg.bin"
            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path=container_cpg_path,
                query=query,
                timeout=timeout,
                limit=limit,
                offset=offset,
            )

            return {
                "success": result.success,
                "data": result.data,
                "row_count": result.row_count,
                "execution_time": result.execution_time,
                "error": result.error,
            }

        except SessionNotFoundError as e:
            logger.error(f"Session not found: {e}")
            return {
                "success": False,
                "error": {"code": "SESSION_NOT_FOUND", "message": str(e)},
            }
        except SessionNotReadyError as e:
            logger.warning(f"Session not ready: {e}")
            return {
                "success": False,
                "error": {"code": "SESSION_NOT_READY", "message": str(e)},
            }
        except QueryExecutionError as e:
            logger.error(f"Query execution error: {e}")
            return {
                "success": False,
                "error": {"code": "QUERY_EXECUTION_ERROR", "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Query execution failed",
                    "details": str(e),
                },
            }

    @mcp.tool()
    async def get_session_status(session_id: str) -> Dict[str, Any]:
        """
        Gets the current status of a CPG session.

        Use this tool to check if CPG generation is complete and the session
        is ready for queries. Also provides metadata about the session.

        Args:
            session_id: The session ID to query

        Returns:
            {
                "session_id": "abc-123",
                "status": "ready" | "generating" | "error" | "initializing",
                "source_type": "github" | "local",
                "source_path": "https://github.com/user/repo",
                "language": "java",
                "created_at": "2025-10-07T10:00:00Z",
                "last_accessed": "2025-10-07T10:05:00Z",
                "cpg_size": "125MB",
                "error_message": null
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            session = await session_manager.get_session(session_id)

            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            # Get CPG file size if available
            cpg_size = None
            if session.cpg_path and os.path.exists(session.cpg_path):
                size_bytes = os.path.getsize(session.cpg_path)
                cpg_size = f"{size_bytes / (1024*1024):.2f}MB"

            return {
                "session_id": session.id,
                "status": session.status,
                "source_type": session.source_type,
                "source_path": session.source_path,
                "language": session.language,
                "created_at": session.created_at.isoformat(),
                "last_accessed": session.last_accessed.isoformat(),
                "cpg_size": cpg_size,
                "error_message": session.error_message,
            }

        except SessionNotFoundError as e:
            logger.error(f"Session not found: {e}")
            return {
                "success": False,
                "error": {"code": "SESSION_NOT_FOUND", "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Error getting session status: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def list_sessions(
        status: Optional[str] = None, source_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Lists all active CPG sessions with optional filtering.

        Args:
            status: Filter by status (optional): "ready", "generating", "error", "initializing"
            source_type: Filter by source type (optional): "local", "github"

        Returns:
            {
                "sessions": [
                    {
                        "session_id": "abc-123",
                        "status": "ready",
                        "source_path": "https://github.com/user/repo",
                        "language": "java",
                        "created_at": "2025-10-07T10:00:00Z"
                    },
                    ...
                ],
                "total": 5
            }
        """
        try:
            session_manager = services["session_manager"]

            filters = {}
            if status:
                filters["status"] = status
            if source_type:
                filters["source_type"] = source_type

            sessions = await session_manager.list_sessions(filters)

            return {
                "sessions": [
                    {
                        "session_id": s.id,
                        "status": s.status,
                        "source_type": s.source_type,
                        "source_path": s.source_path,
                        "language": s.language,
                        "created_at": s.created_at.isoformat(),
                        "last_accessed": s.last_accessed.isoformat(),
                    }
                    for s in sessions
                ],
                "total": len(sessions),
            }

        except Exception as e:
            logger.error(f"Error listing sessions: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def close_session(session_id: str) -> Dict[str, Any]:
        """
        Closes a CPG session and cleans up resources.

        This stops the Docker container, removes temporary files, and frees
        up resources. Sessions are also automatically cleaned up after being
        idle for 30 minutes.

        Args:
            session_id: The session ID to close

        Returns:
            {
                "success": true,
                "message": "Session closed successfully"
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            docker_orch = services["docker"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            # Stop container
            if session.container_id:
                await docker_orch.stop_container(session.container_id)

            # Cleanup session
            await session_manager.cleanup_session(session_id)

            return {"success": True, "message": "Session closed successfully"}

        except SessionNotFoundError as e:
            logger.error(f"Session not found: {e}")
            return {
                "success": False,
                "error": {"code": "SESSION_NOT_FOUND", "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Error closing session: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def cleanup_all_sessions(
        max_age_hours: Optional[int] = None, force: bool = False
    ) -> Dict[str, Any]:
        """
        Cleanup multiple sessions and their containers.

        This tool helps maintain the system by cleaning up old or inactive sessions.
        Use with caution as it will stop containers and remove session data.

        Args:
            max_age_hours: Only cleanup sessions older than this many hours (optional)
            force: If true, cleanup all sessions regardless of age (default: False)

        Returns:
            {
                "success": true,
                "cleaned_up": 5,
                "session_ids": ["id1", "id2", ...],
                "message": "Cleaned up 5 sessions"
            }
        """
        try:
            session_manager = services["session_manager"]
            docker_orch = services["docker"]

            # Get all sessions
            all_sessions = await session_manager.list_sessions({})

            sessions_to_cleanup = []

            for session in all_sessions:
                should_cleanup = False

                if force:
                    should_cleanup = True
                elif max_age_hours:
                    age = datetime.now(UTC) - session.last_accessed
                    if age.total_seconds() / 3600 > max_age_hours:
                        should_cleanup = True

                if should_cleanup:
                    sessions_to_cleanup.append(session)

            cleaned_session_ids = []
            errors = []

            for session in sessions_to_cleanup:
                try:
                    # Stop container
                    if session.container_id:
                        await docker_orch.stop_container(session.container_id)

                    # Cleanup session
                    await session_manager.cleanup_session(session.id)
                    cleaned_session_ids.append(session.id)
                    logger.info(f"Cleaned up session: {session.id}")

                except Exception as e:
                    error_msg = f"Failed to cleanup session {session.id}: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)

            result = {
                "success": True,
                "cleaned_up": len(cleaned_session_ids),
                "session_ids": cleaned_session_ids,
                "message": f"Cleaned up {len(cleaned_session_ids)} sessions",
            }

            if errors:
                result["errors"] = errors
                result["message"] += f" ({len(errors)} errors)"

            return result

        except Exception as e:
            logger.error(f"Error during cleanup: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def list_files(
        session_id: str, pattern: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List all source files in the analyzed codebase as a file tree.

        This tool helps discover the structure of the codebase by listing all files
        that were analyzed. Useful for understanding project layout and finding
        specific files of interest. Directories with more than 20 files will be truncated.

        Args:
            session_id: The session ID from create_cpg_session
            pattern: Optional regex pattern to filter file paths (e.g., ".*\\.java$" for Java files)

        Returns:
            {
                "success": true,
                "tree": {
                    "src": {
                        "main.py": None,
                        "api": { ... }
                    }
                },
                "total": 15
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Query for all file paths
            query = "cpg.file.name.l"
            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=10000,  # High limit for file listing
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            file_paths = result.data

            # Apply pattern filter if provided
            if pattern:
                file_paths = [p for p in file_paths if re.search(pattern, p)]

            # Build the file tree
            tree = {}
            for path in file_paths:
                parts = path.split("/")
                # Filter out empty parts that can result from leading slashes
                parts = [part for part in parts if part]

                current_level = tree
                for i, part in enumerate(parts):
                    if i == len(parts) - 1:
                        # It's a file
                        current_level[part] = None
                    else:
                        # It's a directory
                        if part not in current_level:
                            current_level[part] = {}
                        current_level = current_level[part]

            # Function to truncate large directories (only truncate subfolders, not base level)
            def truncate_tree(node, is_base_level=True):
                if isinstance(node, dict):
                    if not is_base_level and len(node) > 20:
                        # Only truncate if we're not at the base level
                        keys = sorted(node.keys())
                        truncated_node = {
                            key: truncate_tree(node[key], False) for key in keys[:20]
                        }
                        truncated_node[f"... ({len(node) - 20} more files)"] = None
                        return truncated_node
                    else:
                        # For base level or smaller directories, show all entries
                        return {
                            key: truncate_tree(value, False)
                            for key, value in node.items()
                        }
                return node

            truncated_tree_structure = truncate_tree(tree, True)

            return {
                "success": True,
                "tree": truncated_tree_structure,
                "total": len(file_paths),
            }

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error listing files: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def list_methods(
        session_id: str,
        name_pattern: Optional[str] = None,
        file_pattern: Optional[str] = None,
        callee_pattern: Optional[str] = None,
        include_external: bool = False,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        List methods/functions in the codebase.

        Discover all methods and functions defined in the analyzed code. This is
        essential for understanding the codebase structure and finding specific
        functions to analyze.

        Args:
            session_id: The session ID from create_cpg_session
            name_pattern: Optional regex to filter method names (e.g., ".*authenticate.*")
            file_pattern: Optional regex to filter by file path
            callee_pattern: Optional regex to filter for methods that call a specific function
                (e.g., "memcpy|free|malloc")
            include_external: Include external/library methods (default: false)
            limit: Maximum number of results to return. This can be overridden. Default is 100.

        Returns:
            {
                "success": true,
                "methods": [
                    {
                        "name": "main",
                        "fullName": "main",
                        "signature": "int main(int, char**)",
                        "filename": "main.c",
                        "lineNumber": 10,
                        "isExternal": false
                    }
                ],
                "total": 1
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Build query with filters
            query_parts = ["cpg.method"]

            if not include_external:
                query_parts.append(".isExternal(false)")

            if name_pattern:
                query_parts.append(f'.name("{name_pattern}")')

            if file_pattern:
                query_parts.append(f'.where(_.file.name("{file_pattern}"))')

            if callee_pattern:
                query_parts.append(f'.where(_.callOut.name("{callee_pattern}"))')

            query_parts.append(
                ".map(m => (m.name, m.fullName, m.signature, m.filename, m.lineNumber.getOrElse(-1), m.isExternal))"
            )

            query = "".join(query_parts) + f".dedup.take({limit}).l"

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=limit,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            methods = []
            for item in result.data:
                if isinstance(item, dict):
                    methods.append(
                        {
                            "name": item.get("_1", ""),
                            "fullName": item.get("_2", ""),
                            "signature": item.get("_3", ""),
                            "filename": item.get("_4", ""),
                            "lineNumber": item.get("_5", -1),
                            "isExternal": item.get("_6", False),
                        }
                    )

            return {"success": True, "methods": methods, "total": len(methods)}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error listing methods: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def get_method_source(
        session_id: str, method_name: str, filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get the source code of a specific method.

        Retrieve the actual source code for a method to understand its implementation.
        Useful when you need to examine the details of a specific function.

        Args:
            session_id: The session ID from create_cpg_session
            method_name: Name of the method (can be regex pattern)
            filename: Optional filename to disambiguate methods with same name

        Returns:
            {
                "success": true,
                "methods": [
                    {
                        "name": "main",
                        "filename": "main.c",
                        "lineNumber": 10,
                        "lineNumberEnd": 20,
                        "code": "int main() {\n    printf(\"Hello\");\n    return 0;\n}"
                    }
                ],
                "total": 1
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Build query to get method metadata
            query_parts = [f'cpg.method.name("{method_name}")']

            if filename:
                query_parts.append(f'.filename(".*{filename}.*")')

            query_parts.append(
                ".map(m => (m.name, m.filename, m.lineNumber.getOrElse(-1), m.lineNumberEnd.getOrElse(-1)))"
            )
            query = "".join(query_parts) + ".toJsonPretty"

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=10,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            methods = []
            method_name_result = ""
            method_filename = ""
            line_number = -1
            line_number_end = -1
            
            for item in result.data:
                if isinstance(item, dict):
                    method_name_result = item.get("_1", "")
                    method_filename = item.get("_2", "")
                    line_number = item.get("_3", -1)
                    line_number_end = item.get("_4", -1)

            # Get the full source code using file reading logic
            if method_filename and line_number > 0 and line_number_end > 0:
                try:
                    # Get playground path
                    playground_path = os.path.abspath(
                        os.path.join(os.path.dirname(__file__), "..", "..", "playground")
                    )

                    # Get source directory from session
                    if session.source_type == "github":
                        # For GitHub repos, use the cached directory
                        cpg_cache_key = get_cpg_cache_key(
                            session.source_type, session.source_path, session.language
                        )
                        source_dir = os.path.join(playground_path, "codebases", cpg_cache_key)
                    else:
                        # For local paths, use the session source path directly
                        source_path = session.source_path
                        if not os.path.isabs(source_path):
                            source_path = os.path.abspath(source_path)
                        source_dir = source_path

                    # Construct full file path
                    file_path = os.path.join(source_dir, method_filename)

                    # Check if file exists and read it
                    if os.path.exists(file_path) and os.path.isfile(file_path):
                        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                            lines = f.readlines()

                        # Validate line numbers
                        total_lines = len(lines)
                        if line_number <= total_lines and line_number_end >= line_number:
                            # Extract the code snippet (lines are 0-indexed in the list)
                            actual_end_line = min(line_number_end, total_lines)
                            code_lines = lines[line_number - 1 : actual_end_line]
                            full_code = "".join(code_lines)
                        else:
                            full_code = f"// Invalid line range: {line_number}-{line_number_end}, file has {total_lines} lines"
                    else:
                        full_code = f"// Source file not found: {method_filename}"
                except Exception as e:
                    full_code = f"// Error reading source file: {str(e)}"
            else:
                full_code = "// Unable to determine line range for method"

            methods.append(
                {
                    "name": method_name_result,
                    "filename": method_filename,
                    "lineNumber": line_number,
                    "lineNumberEnd": line_number_end,
                    "code": full_code,
                }
            )

            return {"success": True, "methods": methods, "total": len(methods)}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error getting method source: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def list_calls(
        session_id: str,
        caller_pattern: Optional[str] = None,
        callee_pattern: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        List function/method calls in the codebase.

        Discover call relationships between functions. Essential for understanding
        control flow and dependencies in the code.

        Args:
            session_id: The session ID from create_cpg_session
            caller_pattern: Optional regex to filter caller method names
            callee_pattern: Optional regex to filter callee method names
            limit: Maximum number of results (default: 100)

        Returns:
            {
                "success": true,
                "calls": [
                    {
                        "caller": "main",
                        "callee": "helper",
                        "code": "helper(x)",
                        "filename": "main.c",
                        "lineNumber": 15
                    }
                ],
                "total": 1
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Build query
            query_parts = ["cpg.call"]

            if callee_pattern:
                query_parts.append(f'.name("{callee_pattern}")')

            if caller_pattern:
                query_parts.append(f'.where(_.method.name("{caller_pattern}"))')

            query_parts.append(
                ".map(c => (c.method.name, c.name, c.code, c.method.filename, c.lineNumber.getOrElse(-1)))"
            )

            query = "".join(query_parts) + f".dedup.take({limit}).toJsonPretty"

            logger.info(f"list_calls query: {query}")

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=limit,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            calls = []
            for item in result.data:
                if isinstance(item, dict):
                    calls.append(
                        {
                            "caller": item.get("_1", ""),
                            "callee": item.get("_2", ""),
                            "code": item.get("_3", ""),
                            "filename": item.get("_4", ""),
                            "lineNumber": item.get("_5", -1),
                        }
                    )

            return {"success": True, "calls": calls, "total": len(calls)}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error listing calls: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def get_call_graph(
        session_id: str, method_name: str, depth: int = 2, direction: str = "outgoing"
    ) -> Dict[str, Any]:
        """
        Get the call graph for a specific method.

        Understand what functions a method calls (outgoing) or what functions
        call it (incoming). Essential for impact analysis and understanding
        code dependencies.

        Args:
            session_id: The session ID from create_cpg_session
            method_name: Name of the method to analyze (can be regex)
            depth: How many levels deep to traverse (1-3, default: 2)
            direction: "outgoing" (callees) or "incoming" (callers)

        Returns:
            {
                "success": true,
                "root_method": "authenticate",
                "direction": "outgoing",
                "calls": [
                    {"from": "authenticate", "to": "validate_password", "depth": 1},
                    {"from": "validate_password", "to": "hash_password", "depth": 2}
                ],
                "total": 2
            }
        """
        try:
            validate_session_id(session_id)

            if depth < 1 or depth > 3:
                raise ValidationError("Depth must be between 1 and 3")

            if direction not in ["outgoing", "incoming"]:
                raise ValidationError("Direction must be 'outgoing' or 'incoming'")

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Build query based on direction
            method_escaped = re.escape(method_name)
            
            if direction == "outgoing":
                # Use depth-independent BFS traversal for call graph expansion
                # Traverse caller -> calls -> callee for arbitrary depth
                query = (
                    f'val rootMethod = cpg.method.name("{method_escaped}").l\n'
                    f'if (rootMethod.nonEmpty) {{\n'
                    f'  val rootName = rootMethod.head.name\n'
                    f'  var allCalls = scala.collection.mutable.ListBuffer[(String, String, Int)]()\n'
                    f'  var toVisit = scala.collection.mutable.Queue[(io.shiftleft.codepropertygraph.generated.nodes.Method, Int)]()\n'
                    f'  var visited = Set[String]()\n'
                    f'  \n'
                    f'  toVisit.enqueue((rootMethod.head, 0))\n'
                    f'  \n'
                    f'  while (toVisit.nonEmpty) {{\n'
                    f'    val (current, currentDepth) = toVisit.dequeue()\n'
                    f'    val currentName = current.name\n'
                    f'    \n'
                    f'    if (!visited.contains(currentName) && currentDepth < {depth}) {{\n'
                    f'      visited = visited + currentName\n'
                    f'      val callees = current.call.callee.l\n'
                    f'      \n'
                    f'      for (callee <- callees) {{\n'
                    f'        val calleeName = callee.name\n'
                    f'        if (!calleeName.startsWith("<operator>")) {{\n'
                    f'          allCalls += ((currentName, calleeName, currentDepth + 1))\n'
                    f'          if (!visited.contains(calleeName)) {{\n'
                    f'            toVisit.enqueue((callee, currentDepth + 1))\n'
                    f'          }}\n'
                    f'        }}\n'
                    f'      }}\n'
                    f'    }}\n'
                    f'  }}\n'
                    f'  \n'
                    f'  allCalls.toList.map(t => (t._1, t._2, t._3)).toJsonPretty\n'
                    f'}} else List[(String, String, Int)]().toJsonPretty'
                )
            else:  # incoming
                # For incoming calls, find all methods that call the target using BFS
                # This finds methods that call the target at any depth
                query = (
                    f'val targetMethod = cpg.method.name("{method_escaped}").l\n'
                    f'if (targetMethod.nonEmpty) {{\n'
                    f'  val targetName = targetMethod.head.name\n'
                    f'  var allCallers = scala.collection.mutable.ListBuffer[(String, String, Int)]()\n'
                    f'  var toVisit = scala.collection.mutable.Queue[(io.shiftleft.codepropertygraph.generated.nodes.Method, Int)]()\n'
                    f'  var visited = Set[String]()\n'
                    f'  \n'
                    f'  // Start with direct callers\n'
                    f'  val directCallers = targetMethod.head.caller.l\n'
                    f'  for (caller <- directCallers) {{\n'
                    f'    allCallers += ((caller.name, targetName, 1))\n'
                    f'    toVisit.enqueue((caller, 1))\n'
                    f'  }}\n'
                    f'  \n'
                    f'  // BFS to find indirect callers\n'
                    f'  while (toVisit.nonEmpty) {{\n'
                    f'    val (current, currentDepth) = toVisit.dequeue()\n'
                    f'    val currentName = current.name\n'
                    f'    \n'
                    f'    if (!visited.contains(currentName) && currentDepth < {depth}) {{\n'
                    f'      visited = visited + currentName\n'
                    f'      val incomingCallers = current.caller.l\n'
                    f'      \n'
                    f'      for (caller <- incomingCallers) {{\n'
                    f'        val callerName = caller.name\n'
                    f'        if (!callerName.startsWith("<operator>")) {{\n'
                    f'          allCallers += ((callerName, targetName, currentDepth + 1))\n'
                    f'          if (!visited.contains(callerName)) {{\n'
                    f'            toVisit.enqueue((caller, currentDepth + 1))\n'
                    f'          }}\n'
                    f'        }}\n'
                    f'      }}\n'
                    f'    }}\n'
                    f'  }}\n'
                    f'  \n'
                    f'  allCallers.toList.map(t => (t._1, t._2, t._3)).toJsonPretty\n'
                    f'}} else List[(String, String, Int)]().toJsonPretty'
                )

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=60,
                limit=200,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            calls = []
            for item in result.data:
                if isinstance(item, dict):
                    calls.append(
                        {
                            "from": item.get("_1", ""),
                            "to": item.get("_2", ""),
                            "depth": item.get("_3", 1),
                        }
                    )

            return {
                "success": True,
                "root_method": method_name,
                "direction": direction,
                "calls": calls,
                "total": len(calls),
            }

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error getting call graph: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def list_parameters(session_id: str, method_name: str) -> Dict[str, Any]:
        """
        List parameters of a specific method.

        Get detailed information about method parameters including their names,
        types, and order. Useful for understanding function signatures.

        Args:
            session_id: The session ID from create_cpg_session
            method_name: Name of the method (can be regex pattern)

        Returns:
            {
                "success": true,
                "methods": [
                    {
                        "method": "authenticate",
                        "parameters": [
                            {"name": "username", "type": "string", "index": 1},
                            {"name": "password", "type": "string", "index": 2}
                        ]
                    }
                ],
                "total": 1
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            query = f'cpg.method.name("{method_name}").map(m => (m.name, m.parameter.map(p => ' \
                f'(p.name, p.typeFullName, p.index)).l)).toJsonPretty'

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=10,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            methods = []
            for item in result.data:
                if isinstance(item, dict) and "_1" in item and "_2" in item:
                    params = []
                    param_list = item.get("_2", [])

                    for param_data in param_list:
                        if isinstance(param_data, dict):
                            params.append(
                                {
                                    "name": param_data.get("_1", ""),
                                    "type": param_data.get("_2", ""),
                                    "index": param_data.get("_3", -1),
                                }
                            )

                    methods.append({"method": item.get("_1", ""), "parameters": params})

            return {"success": True, "methods": methods, "total": len(methods)}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error listing parameters: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def find_literals(
        session_id: str,
        pattern: Optional[str] = None,
        literal_type: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Find literal values in the code (strings, numbers, etc).

        Search for hardcoded values like strings, numbers, or constants.
        Useful for finding configuration values, API keys, URLs, or
        magic numbers in the code.

        Args:
            session_id: The session ID from create_cpg_session
            pattern: Optional regex to filter literal values (e.g., ".*password.*")
            literal_type: Optional type filter (e.g., "string", "int")
            limit: Maximum number of results (default: 50)

        Returns:
            {
                "success": true,
                "literals": [
                    {
                        "value": "admin_password",
                        "type": "string",
                        "filename": "config.c",
                        "lineNumber": 42,
                        "method": "init_config"
                    }
                ],
                "total": 1
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Build query
            query_parts = ["cpg.literal"]

            if pattern:
                query_parts.append(f'.code("{pattern}")')

            if literal_type:
                query_parts.append(f'.typeFullName(".*{literal_type}.*")')

            query_parts.append(
                ".map(lit => (lit.code, lit.typeFullName, lit.filename, lit.lineNumber.getOrElse(-1), lit.method.name))"
            )
            query = "".join(query_parts) + f".take({limit})"

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=limit,  # Use the limit parameter
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            literals = []
            for item in result.data:
                if isinstance(item, dict):
                    literals.append(
                        {
                            "value": item.get("_1", ""),
                            "type": item.get("_2", ""),
                            "filename": item.get("_3", ""),
                            "lineNumber": item.get("_4", -1),
                            "method": item.get("_5", ""),
                        }
                    )

            return {"success": True, "literals": literals, "total": len(literals)}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error finding literals: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def find_taint_sources(
        session_id: str, language: Optional[str] = None, source_patterns: Optional[list] = None, limit: int = 200
    ) -> Dict[str, Any]:
        """
        Locate likely external input points (taint sources).

        Search for function calls that could be entry points for untrusted data,
        such as user input, environment variables, or network data. Useful for
        identifying where external data enters the program.

        Args:
            session_id: The session ID from create_cpg_session
            language: Programming language to use for default patterns (e.g., "c", "java")
                If not provided, uses the session's language
            source_patterns: Optional list of regex patterns to match source function names
                (e.g., ["getenv", "fgets", "scanf"]). If not provided, uses default patterns
            limit: Maximum number of results to return (default: 200)

        Returns:
            {
                "success": true,
                "sources": [
                    {
                        "node_id": "12345",
                        "name": "getenv",
                        "code": "getenv(\"PATH\")",
                        "filename": "main.c",
                        "lineNumber": 42,
                        "method": "main"
                    }
                ],
                "total": 1
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Determine language and patterns
            lang = language or session.language or "c"
            cfg = services["config"]
            taint_cfg = getattr(cfg.cpg, "taint_sources", {}) if hasattr(cfg.cpg, "taint_sources") else {}

            patterns = source_patterns or taint_cfg.get(lang, [])
            if not patterns:
                # Fallback to common C patterns
                patterns = ["getenv", "fgets", "scanf", "read", "recv", "accept", "fopen"]

            # Build Joern query searching for call names matching any pattern
            # Remove trailing parens from patterns for proper regex matching
            cleaned_patterns = [p.rstrip("(") for p in patterns]
            joined = "|".join([re.escape(p) for p in cleaned_patterns])
            # Use cpg.call where name matches regex
            query = f'cpg.call.name("{joined}").map(c => (c.id, c.name, c.code, c.file.name.headOption.getOrElse("unknown"), c.lineNumber.getOrElse(-1), c.method.fullName)).take({limit})'

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=limit,
            )

            if not result.success:
                return {"success": False, "error": {"code": "QUERY_ERROR", "message": result.error}}

            sources = []
            for item in result.data:
                if isinstance(item, dict):
                    sources.append({
                        "node_id": item.get("_1"),
                        "name": item.get("_2"),
                        "code": item.get("_3"),
                        "filename": item.get("_4"),
                        "lineNumber": item.get("_5"),
                        "method": item.get("_6"),
                    })

            return {"success": True, "sources": sources, "total": len(sources)}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error finding taint sources: {e}")
            return {"success": False, "error": {"code": type(e).__name__.upper(), "message": str(e)}}
        except Exception as e:
            logger.error(f"Unexpected error finding taint sources: {e}", exc_info=True)
            return {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(e)}}

    @mcp.tool()
    async def find_taint_sinks(
        session_id: str, language: Optional[str] = None, sink_patterns: Optional[list] = None, limit: int = 200
    ) -> Dict[str, Any]:
        """
        Locate dangerous sinks where tainted data could cause vulnerabilities.

        Search for function calls that could be security-sensitive destinations
        for data, such as system execution, file operations, or format strings.
        Useful for identifying where untrusted data could cause harm.

        Args:
            session_id: The session ID from create_cpg_session
            language: Programming language to use for default patterns (e.g., "c", "java")
                If not provided, uses the session's language
            sink_patterns: Optional list of regex patterns to match sink function names
                (e.g., ["system", "popen", "sprintf"]). If not provided, uses default patterns
            limit: Maximum number of results to return (default: 200)

        Returns:
            {
                "success": true,
                "sinks": [
                    {
                        "node_id": "67890",
                        "name": "system",
                        "code": "system(cmd)",
                        "filename": "main.c",
                        "lineNumber": 100,
                        "method": "execute_command"
                    }
                ],
                "total": 1
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            lang = language or session.language or "c"
            cfg = services["config"]
            taint_cfg = getattr(cfg.cpg, "taint_sinks", {}) if hasattr(cfg.cpg, "taint_sinks") else {}

            patterns = sink_patterns or taint_cfg.get(lang, [])
            if not patterns:
                patterns = ["system", "popen", "execl", "execv", "sprintf", "fprintf"]

            # Remove trailing parens from patterns for proper regex matching
            cleaned_patterns = [p.rstrip("(") for p in patterns]
            joined = "|".join([re.escape(p) for p in cleaned_patterns])
            query = f'cpg.call.name("{joined}").map(c => (c.id, c.name, c.code, c.file.name.headOption.getOrElse("unknown"), c.lineNumber.getOrElse(-1), c.method.fullName)).take({limit})'

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=limit,
            )

            if not result.success:
                return {"success": False, "error": {"code": "QUERY_ERROR", "message": result.error}}

            sinks = []
            for item in result.data:
                if isinstance(item, dict):
                    sinks.append({
                        "node_id": item.get("_1"),
                        "name": item.get("_2"),
                        "code": item.get("_3"),
                        "filename": item.get("_4"),
                        "lineNumber": item.get("_5"),
                        "method": item.get("_6"),
                    })

            return {"success": True, "sinks": sinks, "total": len(sinks)}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error finding taint sinks: {e}")
            return {"success": False, "error": {"code": type(e).__name__.upper(), "message": str(e)}}
        except Exception as e:
            logger.error(f"Unexpected error finding taint sinks: {e}", exc_info=True)
            return {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(e)}}

    @mcp.tool()
    async def find_taint_flows(
        session_id: str,
        source_node_id: Optional[str] = None,
        sink_node_id: Optional[str] = None,
        source_location: Optional[str] = None,
        sink_location: Optional[str] = None,
        max_path_length: int = 20,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """
        Find dataflow paths from a specific source to a specific sink using Joern dataflow primitives.

        Analyze data flow from a taint source (external input point or function call) to a taint sink
        (security-sensitive operation) to identify potential vulnerabilities. Provides detailed path
        information showing how data flows through the call graph and data dependencies.

        This is a focused taint analysis task that works with specific source and sink identifiers,
        making it practical for vulnerability investigation and security code review.

        **Important**: Since function names like "malloc", "read", or "system" can appear many times
        in a codebase, you MUST specify which specific call instance to analyze. Use node IDs (obtained
        from find_taint_sources/find_taint_sinks) or specify exact locations.

        Args:
            session_id: The session ID from create_cpg_session
            source_node_id: Node ID of the source call/method (recommended method - get from find_taint_sources)
                Example: "12345" - the exact CPG node ID for a specific getenv() call
            sink_node_id: Node ID of the sink call/method (recommended method - get from find_taint_sinks)
                Example: "67890" - the exact CPG node ID for a specific system() call
            source_location: Alternative to node_id: specify as "filename:line_number" or "filename:line_number:method_name"
                Example: "main.c:42" or "main.c:42:main"
            sink_location: Alternative to node_id: specify as "filename:line_number" or "filename:line_number:method_name"
                Example: "main.c:100" or "main.c:100:execute_command"
            max_path_length: Maximum length of dataflow paths to consider in elements (default: 20)
                Paths with more elements will be filtered out to avoid extremely long chains
            timeout: Maximum execution time in seconds (default: 60)

        Returns:
            {
                "success": true,
                "source": {
                    "node_id": "12345",
                    "code": "getenv(\"PATH\")",
                    "filename": "main.c",
                    "lineNumber": 42,
                    "method": "main"
                },
                "sink": {
                    "node_id": "67890",
                    "code": "system(cmd)",
                    "filename": "main.c",
                    "lineNumber": 100,
                    "method": "execute_command"
                },
                "flows": [
                    {
                        "path_id": 0,
                        "path_length": 5,
                        "nodes": [
                            {
                                "step": 0,
                                "code": "getenv(\"PATH\")",
                                "filename": "main.c",
                                "lineNumber": 42,
                                "nodeType": "CALL"
                            },
                            {
                                "step": 1,
                                "code": "path_var",
                                "filename": "main.c",
                                "lineNumber": 45,
                                "nodeType": "IDENTIFIER"
                            },
                            ...
                        ]
                    }
                ],
                "total_flows": 1
            }
        """
        try:
            validate_session_id(session_id)

            # Validate that we have proper source and sink specifications
            if not source_node_id and not source_location:
                raise ValidationError("Either source_node_id or source_location must be provided")
            if not sink_node_id and not sink_location:
                raise ValidationError("Either sink_node_id or sink_location must be provided")

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Resolve source to actual node
            source_info = None
            if source_node_id:
                # Direct node ID lookup
                query = f'cpg.id({source_node_id}).map(n => (n.id, n.code, n.file.name.headOption.getOrElse("unknown"), n.lineNumber.getOrElse(-1), Try(n.method.fullName).getOrElse("unknown"))).headOption'
            else:
                # Parse location: "filename:line_number" or "filename:line_number:method_name"
                parts = source_location.split(":")
                if len(parts) < 2:
                    raise ValidationError("source_location must be in format 'filename:line' or 'filename:line:method'")
                
                filename = parts[0]
                line_num = parts[1]
                method_name = parts[2] if len(parts) > 2 else None
                
                if method_name:
                    query = f'cpg.file.name("{filename}").call.lineNumber({line_num}).where(_.method.fullName.contains("{method_name}")).map(c => (c.id, c.code, c.file.name.headOption.getOrElse("unknown"), c.lineNumber.getOrElse(-1), c.method.fullName)).headOption'
                else:
                    query = f'cpg.file.name("{filename}").call.lineNumber({line_num}).map(c => (c.id, c.code, c.file.name.headOption.getOrElse("unknown"), c.lineNumber.getOrElse(-1), c.method.fullName)).headOption'
            
            result_src = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=10,
                limit=1,
            )

            if result_src.success and result_src.data and len(result_src.data) > 0:
                item = result_src.data[0]
                if isinstance(item, dict) and item.get("_1"):
                    source_info = {
                        "node_id": item.get("_1"),
                        "code": item.get("_2"),
                        "filename": item.get("_3"),
                        "lineNumber": item.get("_4"),
                        "method": item.get("_5"),
                    }

            # Resolve sink to actual node
            sink_info = None
            if sink_node_id:
                # Direct node ID lookup
                query = f'cpg.id({sink_node_id}).map(n => (n.id, n.code, n.file.name.headOption.getOrElse("unknown"), n.lineNumber.getOrElse(-1), Try(n.method.fullName).getOrElse("unknown"))).headOption'
            else:
                # Parse location: "filename:line_number" or "filename:line_number:method_name"
                parts = sink_location.split(":")
                if len(parts) < 2:
                    raise ValidationError("sink_location must be in format 'filename:line' or 'filename:line:method'")
                
                filename = parts[0]
                line_num = parts[1]
                method_name = parts[2] if len(parts) > 2 else None
                
                if method_name:
                    query = f'cpg.file.name("{filename}").call.lineNumber({line_num}).where(_.method.fullName.contains("{method_name}")).map(c => (c.id, c.code, c.file.name.headOption.getOrElse("unknown"), c.lineNumber.getOrElse(-1), c.method.fullName)).headOption'
                else:
                    query = f'cpg.file.name("{filename}").call.lineNumber({line_num}).map(c => (c.id, c.code, c.file.name.headOption.getOrElse("unknown"), c.lineNumber.getOrElse(-1), c.method.fullName)).headOption'
            
            result_snk = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=10,
                limit=1,
            )

            if result_snk.success and result_snk.data and len(result_snk.data) > 0:
                item = result_snk.data[0]
                if isinstance(item, dict) and item.get("_1"):
                    sink_info = {
                        "node_id": item.get("_1"),
                        "code": item.get("_2"),
                        "filename": item.get("_3"),
                        "lineNumber": item.get("_4"),
                        "method": item.get("_5"),
                    }

            # If either source or sink not found, return early
            if not source_info or not sink_info:
                return {
                    "success": True,
                    "source": source_info,
                    "sink": sink_info,
                    "flows": [],
                    "total_flows": 0,
                    "message": f"Could not resolve source or sink from provided identifiers"
                }

            # Build dataflow query using reachableByFlows
            # This finds all dataflow paths from source to sink
            source_id = source_info["node_id"]
            sink_id = sink_info["node_id"]
            
            query = (
                f'val source = cpg.id({source_id}).l\n'
                f'val sink = cpg.id({sink_id}).l\n'
                f'if (source.nonEmpty && sink.nonEmpty) {{\n'
                f'  val flows = sink.reachableByFlows(source).filter(f => f.elements.size <= {max_path_length}).toList\n'
                f'  flows.zipWithIndex.map {{ case (flow, flowIdx) =>\n'
                f'    (flowIdx, flow.elements.size, flow.elements.map(e => (e.code, e.file.name.headOption.getOrElse("unknown"), e.lineNumber.getOrElse(-1), e.label)).l)\n'
                f'  }}\n'
                f'}} else List[(Int, Int, List[(String, String, Int, String)])]()'
            )

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=timeout,
                limit=1000,  # Allow many results to capture all paths
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            # Parse flows from result
            flows = []
            for item in result.data:
                if isinstance(item, dict):
                    flow_idx = item.get("_1")
                    path_length = item.get("_2")
                    nodes_data = item.get("_3", [])
                    
                    # Build node list for this path
                    nodes = []
                    for step, node_data in enumerate(nodes_data):
                        if isinstance(node_data, dict):
                            nodes.append({
                                "step": step,
                                "code": node_data.get("_1", ""),
                                "filename": node_data.get("_2", ""),
                                "lineNumber": node_data.get("_3", -1),
                                "nodeType": node_data.get("_4", ""),
                            })
                    
                    flows.append({
                        "path_id": flow_idx,
                        "path_length": path_length,
                        "nodes": nodes,
                    })

            return {
                "success": True,
                "source": source_info,
                "sink": sink_info,
                "flows": flows,
                "total_flows": len(flows),
            }

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error finding taint flows: {e}")
            return {"success": False, "error": {"code": type(e).__name__.upper(), "message": str(e)}}
        except Exception as e:
            logger.error(f"Unexpected error finding taint flows: {e}", exc_info=True)
            return {"success": False, "error": {"code": "INTERNAL_ERROR", "message": str(e)}}

    @mcp.tool()
    async def check_method_reachability(
        session_id: str, source_method: str, target_method: str
    ) -> Dict[str, Any]:
        """
        Check if one method can reach another through the call graph.

        Determines whether the target method is reachable from the source method
        by following function calls. Useful for understanding code dependencies
        and potential execution paths.

        Args:
            session_id: The session ID from create_cpg_session
            source_method: Name of the source method (can be regex pattern)
            target_method: Name of the target method (can be regex pattern)

        Returns:
            {
                "success": true,
                "reachable": true,
                "source_method": "main",
                "target_method": "helper",
                "message": "Method 'helper' is reachable from 'main'"
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Escape patterns for regex
            source_escaped = re.escape(source_method)
            target_escaped = re.escape(target_method)

            # Query to check reachability using depth-independent BFS traversal.
            # Instead of manually checking levels 1-5, we use a recursive function
            # to traverse the entire call graph regardless of depth.
            query = (
                f'val source = cpg.method.name("{source_escaped}").l\n'
                f'val target = cpg.method.name("{target_escaped}").l\n'
                f'val reachable = if (source.nonEmpty && target.nonEmpty) {{\n'
                f'  val targetName = target.head.name\n'
                f'  // BFS traversal of call graph using recursive method traversal\n'
                f'  var visited = Set[String]()\n'
                f'  var toVisit = scala.collection.mutable.Queue[io.shiftleft.codepropertygraph.generated.nodes.Method]()\n'
                f'  toVisit.enqueue(source.head)\n'
                f'  var found = false\n'
                f'  \n'
                f'  while (toVisit.nonEmpty && !found) {{\n'
                f'    val current = toVisit.dequeue()\n'
                f'    val currentName = current.name\n'
                f'    if (!visited.contains(currentName)) {{\n'
                f'      visited = visited + currentName\n'
                f'      val callees = current.call.callee.l\n'
                f'      for (callee <- callees) {{\n'
                f'        val calleeName = callee.name\n'
                f'        if (calleeName == targetName) {{\n'
                f'          found = true\n'
                f'        }} else if (!visited.contains(calleeName) && !calleeName.startsWith("<operator>")) {{\n'
                f'          toVisit.enqueue(callee)\n'
                f'        }}\n'
                f'      }}\n'
                f'    }}\n'
                f'  }}\n'
                f'  found\n'
                f'}} else false\n'
                f'List(reachable).toJsonPretty'
            )

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=60,
                limit=1,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            reachable = False
            if result.data and len(result.data) > 0:
                # The query returns a boolean result
                reachable = bool(result.data[0])

            message = f"Method '{target_method}' is {'reachable' if reachable else 'not reachable'} " \
                      f"from '{source_method}'"

            return {
                "success": True,
                "reachable": reachable,
                "source_method": source_method,
                "target_method": target_method,
                "message": message,
            }

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error checking method reachability: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def get_program_slice(
        session_id: str,
        node_id: Optional[str] = None,
        location: Optional[str] = None,
        include_dataflow: bool = True,
        include_control_flow: bool = True,
        max_depth: int = 5,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """
        Build a program slice from a specific call node.

        Creates a backward program slice showing all code that could affect the
        execution at a specific point. This includes:
        - The call itself and its arguments
        - Dataflow: all assignments and operations affecting argument variables
        - Control flow: conditions that determine whether the call executes
        - Call graph: functions called and their data dependencies

        **Important**: Use node IDs (from list_calls) or specify exact locations to
        avoid ambiguity, especially when multiple calls appear on the same line.

        Args:
            session_id: The session ID from create_cpg_session
            node_id: Preferred: Direct CPG node ID of the target call
                (Get from list_calls or other query results)
                Example: "12345"
            location: Alternative: "filename:line_number" or "filename:line_number:call_name"
                Example: "main.c:42" or "main.c:42:memcpy"
            include_dataflow: Include dataflow (variable assignments) in slice (default: true)
            include_control_flow: Include control dependencies (if/while conditions) (default: true)
            max_depth: Maximum depth for dataflow tracking (default: 5)
            timeout: Maximum execution time in seconds (default: 60)

        Returns:
            {
                "success": true,
                "slice": {
                    "target_call": {
                        "node_id": "12345",
                        "name": "memcpy",
                        "code": "memcpy(buf, src, size)",
                        "filename": "main.c",
                        "lineNumber": 42,
                        "method": "process_data",
                        "arguments": ["buf", "src", "size"]
                    },
                    "dataflow": [
                        {
                            "variable": "buf",
                            "code": "char buf[256]",
                            "filename": "main.c",
                            "lineNumber": 10,
                            "method": "process_data"
                        }
                    ],
                    "control_dependencies": [
                        {
                            "code": "if (user_input != NULL)",
                            "filename": "main.c",
                            "lineNumber": 35,
                            "method": "process_data"
                        }
                    ]
                },
                "total_nodes": 15
            }
        """
        try:
            validate_session_id(session_id)

            # Validate that we have proper node identification
            if not node_id and not location:
                raise ValidationError("Either node_id or location must be provided")

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Step 1: Resolve target call node
            target_call = None
            
            if node_id:
                # Direct node ID lookup - most efficient and unambiguous
                query = (
                    f'cpg.id({node_id}).map(c => (c.id, c.name, c.code, c.file.name.headOption.getOrElse("unknown"), '
                    f'c.lineNumber.getOrElse(-1), c.method.name, c.argument.code.l)).headOption'
                )
            else:
                # Parse location string to find call
                parts = location.split(":")
                if len(parts) < 2:
                    raise ValidationError("location must be in format 'filename:line' or 'filename:line:callname'")
                
                filename = parts[0]
                line_num = parts[1]
                call_name = parts[2] if len(parts) > 2 else None
                
                # Build query to find call at location
                if call_name:
                    query = (
                        f'cpg.file.name(".*{re.escape(filename)}.*").call.name("{call_name}").lineNumber({line_num})'
                        f'.map(c => (c.id, c.name, c.code, c.file.name.headOption.getOrElse("unknown"), '
                        f'c.lineNumber.getOrElse(-1), c.method.name, c.argument.code.l)).headOption'
                    )
                else:
                    query = (
                        f'cpg.file.name(".*{re.escape(filename)}.*").call.lineNumber({line_num})'
                        f'.map(c => (c.id, c.name, c.code, c.file.name.headOption.getOrElse("unknown"), '
                        f'c.lineNumber.getOrElse(-1), c.method.name, c.argument.code.l)).headOption'
                    )
            
            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=10,
                limit=1,
            )

            if not result.success or not result.data or not result.data[0].get("_1"):
                return {
                    "success": False,
                    "error": {
                        "code": "NOT_FOUND",
                        "message": f"Call not found: node_id={node_id}, location={location}"
                    },
                }

            item = result.data[0]
            target_call = {
                "node_id": item.get("_1"),
                "name": item.get("_2", ""),
                "code": item.get("_3", ""),
                "filename": item.get("_4", ""),
                "lineNumber": item.get("_5", -1),
                "method": item.get("_6", ""),
                "arguments": item.get("_7", []),
            }

            slice_result = {
                "target_call": target_call,
                "dataflow": [],
                "control_dependencies": [],
            }

            # Step 2: Get dataflow for arguments
            if include_dataflow and target_call["arguments"]:
                for arg in target_call["arguments"]:
                    # Clean up argument
                    clean_arg = arg.strip().replace("\"", "")
                    if not clean_arg or clean_arg.isdigit() or clean_arg.startswith("(") or clean_arg.startswith("0x"):
                        continue

                    # Find identifiers with this name and their definitions
                    dataflow_query = (
                        f'cpg.identifier.name("{re.escape(clean_arg)}").l.take(10).map(id => '
                        f'(id.code, id.file.name.headOption.getOrElse("unknown"), '
                        f'id.lineNumber.getOrElse(-1), id.method.name))'
                    )

                    dataflow_result = await query_executor.execute_query(
                        session_id=session_id,
                        cpg_path="/workspace/cpg.bin",
                        query=dataflow_query,
                        timeout=15,
                        limit=20,
                    )

                    if dataflow_result.success and dataflow_result.data:
                        for dflow_item in dataflow_result.data[:5]:  # Limit to 5 per argument
                            if isinstance(dflow_item, dict):
                                slice_result["dataflow"].append({
                                    "variable": clean_arg,
                                    "code": dflow_item.get("_1", ""),
                                    "filename": dflow_item.get("_2", ""),
                                    "lineNumber": dflow_item.get("_3", -1),
                                    "method": dflow_item.get("_4", ""),
                                })

            # Step 3: Get control dependencies
            if include_control_flow:
                # Query using node ID for precise control dependency lookup
                control_query = (
                    f'cpg.id({target_call["node_id"]}).controlledBy.map(ctrl => '
                    f'(ctrl.code, ctrl.file.name.headOption.getOrElse("unknown"), '
                    f'ctrl.lineNumber.getOrElse(-1), ctrl.method.name)).dedup.take(20)'
                )

                control_result = await query_executor.execute_query(
                    session_id=session_id,
                    cpg_path="/workspace/cpg.bin",
                    query=control_query,
                    timeout=15,
                    limit=20,
                )

                if control_result.success and control_result.data:
                    for ctrl_item in control_result.data:
                        if isinstance(ctrl_item, dict):
                            slice_result["control_dependencies"].append({
                                "code": ctrl_item.get("_1", ""),
                                "filename": ctrl_item.get("_2", ""),
                                "lineNumber": ctrl_item.get("_3", -1),
                                "method": ctrl_item.get("_4", ""),
                            })

            total_nodes = (
                1 +  # target call
                len(slice_result["dataflow"]) +
                len(slice_result["control_dependencies"])
            )

            return {
                "success": True,
                "slice": slice_result,
                "total_nodes": total_nodes,
            }

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error getting program slice: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error getting program slice: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def get_codebase_summary(session_id: str) -> Dict[str, Any]:
        """
        Get a high-level summary of the codebase structure.

        Provides an overview including file count, method count, language,
        and other metadata. Useful as a first step when exploring a new codebase.

        Args:
            session_id: The session ID from create_cpg_session

        Returns:
            {
                "success": true,
                "summary": {
                    "language": "C",
                    "total_files": 15,
                    "total_methods": 127,
                    "total_calls": 456,
                    "external_methods": 89,
                    "lines_of_code": 5432
                }
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Get metadata
            meta_query = "cpg.metaData.map(m => (m.language, m.version)).toJsonPretty"
            meta_result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=meta_query,
                timeout=10,
                limit=1,
            )

            language = "unknown"
            if meta_result.success and meta_result.data:
                item = meta_result.data[0]
                if isinstance(item, dict):
                    language = item.get("_1", "unknown")

            # Get counts
            stats_query = """
            cpg.metaData.map(_ => (
                cpg.file.size,
                cpg.method.size,
                cpg.method.isExternal(false).size,
                cpg.call.size,
                cpg.literal.size
            )).toJsonPretty
            """

            stats_result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=stats_query,
                timeout=30,
                limit=1,
            )

            summary = {
                "language": language,
                "total_files": 0,
                "total_methods": 0,
                "user_defined_methods": 0,
                "total_calls": 0,
                "total_literals": 0,
            }

            if stats_result.success and stats_result.data:
                item = stats_result.data[0]
                if isinstance(item, dict):
                    summary["total_files"] = item.get("_1", 0)
                    summary["total_methods"] = item.get("_2", 0)
                    summary["user_defined_methods"] = item.get("_3", 0)
                    summary["total_calls"] = item.get("_4", 0)
                    summary["total_literals"] = item.get("_5", 0)
                    summary["external_methods"] = (
                        summary["total_methods"] - summary["user_defined_methods"]
                    )

            return {"success": True, "summary": summary}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error getting codebase summary: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def get_code_snippet(
        session_id: str, filename: str, start_line: int, end_line: int
    ) -> Dict[str, Any]:
        """
        Retrieve a code snippet from a specific file with line range.

        Get the source code from a file between specified start and end line numbers.
        Useful for examining specific parts of the codebase.

        Args:
            session_id: The session ID from create_cpg_session
            filename: Name of the file to retrieve code from (relative to source root)
            start_line: Starting line number (1-indexed)
            end_line: Ending line number (1-indexed, inclusive)

        Returns:
            {
                "success": true,
                "filename": "main.c",
                "start_line": 10,
                "end_line": 20,
                "code": "int main() {\n    printf(\"Hello\");\n    return 0;\n}"
            }
        """
        try:
            validate_session_id(session_id)

            if start_line < 1 or end_line < start_line:
                raise ValidationError(
                    "Invalid line range: start_line must be >= 1 and end_line >= start_line"
                )

            session_manager = services["session_manager"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Get playground path
            playground_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "playground")
            )

            # Get source directory from session
            if session.source_type == "github":
                # For GitHub repos, use the cached directory
                cpg_cache_key = get_cpg_cache_key(
                    session.source_type, session.source_path, session.language
                )
                source_dir = os.path.join(playground_path, "codebases", cpg_cache_key)
            else:
                # For local paths, use the session source path directly
                source_path = session.source_path
                if not os.path.isabs(source_path):
                    source_path = os.path.abspath(source_path)
                source_dir = source_path

            # Construct full file path
            file_path = os.path.join(source_dir, filename)

            # Check if file exists
            if not os.path.exists(file_path):
                raise ValidationError(
                    f"File '{filename}' not found in source directory"
                )

            if not os.path.isfile(file_path):
                raise ValidationError(f"'{filename}' is not a file")

            # Read the file
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            # Validate line numbers
            total_lines = len(lines)
            if start_line > total_lines:
                raise ValidationError(
                    f"start_line {start_line} exceeds file length {total_lines}"
                )

            if end_line > total_lines:
                end_line = total_lines

            # Extract the code snippet (lines are 0-indexed in the list)
            code_lines = lines[start_line - 1 : end_line]
            code = "".join(code_lines)

            return {
                "success": True,
                "filename": filename,
                "start_line": start_line,
                "end_line": end_line,
                "code": code,
            }

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error getting code snippet: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }
