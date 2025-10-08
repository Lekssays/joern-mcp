"""
MCP Tool Definitions for Joern MCP Server
"""
import asyncio
import logging
import os
import hashlib
import time
from datetime import datetime
from typing import Optional, Dict, Any

from ..models import SessionStatus
from ..exceptions import (
    SessionNotFoundError,
    SessionNotReadyError,
    ValidationError,
    ResourceLimitError,
    QueryExecutionError
)
from ..utils.validators import (
    validate_source_type,
    validate_language,
    validate_session_id,
    validate_github_url,
    validate_local_path,
    validate_cpgql_query
)

logger = logging.getLogger(__name__)


def get_cpg_cache_path(source_path: str, language: str, playground_path: str) -> str:
    """
    Generate a deterministic CPG cache path based on source path and language.
    Uses SHA256 hash of the source path to create unique but reproducible filename.
    """
    # Create a unique identifier from source path and language
    identifier = f"{source_path}:{language}"
    hash_digest = hashlib.sha256(identifier.encode()).hexdigest()[:16]
    
    # Create CPG filename
    cpg_filename = f"cpg_{hash_digest}_{language}.bin"
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
        branch: Optional[str] = None
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
            language: Programming language - one of: java, c, cpp, javascript, python, go, kotlin, csharp, ghidra, jimple, php, ruby, swift
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
            
            session_manager = services['session_manager']
            git_manager = services['git_manager']
            docker_orch = services['docker']
            cpg_generator = services['cpg_generator']
            storage_config = services['config'].storage
            
            # Create session
            session = await session_manager.create_session(
                source_type=source_type,
                source_path=source_path,
                language=language,
                options={
                    'github_token': github_token,
                    'branch': branch
                }
            )
            
            # Handle source preparation
            workspace_path = os.path.join(storage_config.workspace_root, "repos", session.id)
            
            # Get playground path (absolute)
            playground_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'playground'))
            
            if source_type == "github":
                validate_github_url(source_path)
                # Clone to playground/codebases instead
                target_path = os.path.join(playground_path, "codebases", session.id)
                os.makedirs(target_path, exist_ok=True)
                
                await git_manager.clone_repository(
                    repo_url=source_path,
                    target_path=target_path,
                    branch=branch,
                    token=github_token
                )
                # Path inside container
                container_source_path = f"/playground/codebases/{session.id}"
            else:
                # For local paths, check if it's relative to playground/codebases
                if source_path.startswith("playground/codebases/") or "/playground/codebases/" in source_path:
                    # Already in playground, use directly
                    if not os.path.isabs(source_path):
                        source_path = os.path.abspath(source_path)
                    
                    if not os.path.exists(source_path):
                        raise ValidationError(f"Path does not exist: {source_path}")
                    if not os.path.isdir(source_path):
                        raise ValidationError(f"Path is not a directory: {source_path}")
                    
                    # Get relative path from playground root
                    rel_path = os.path.relpath(source_path, playground_path)
                    container_source_path = f"/playground/{rel_path}"
                    
                    logger.info(f"Using local source from playground: {source_path} -> {container_source_path}")
                else:
                    # Copy to playground/codebases
                    import shutil
                    
                    # Validate the path exists on the host system
                    if not os.path.isabs(source_path):
                        raise ValidationError("Local path must be absolute or relative to playground/codebases")
                    
                    # Detect if we're running in a container
                    in_container = (
                        os.path.exists("/.dockerenv") or
                        os.path.exists("/run/.containerenv") or
                        os.path.exists("/host/home/")
                    )
                    
                    container_check_path = source_path
                    if in_container and source_path.startswith("/home/"):
                        container_check_path = source_path.replace("/home/", "/host/home/", 1)
                        logger.info(f"Running in container, translated path: {source_path} -> {container_check_path}")
                    
                    if not os.path.exists(container_check_path):
                        raise ValidationError(f"Path does not exist: {source_path}")
                    if not os.path.isdir(container_check_path):
                        raise ValidationError(f"Path is not a directory: {source_path}")
                    
                    # Copy to playground/codebases
                    target_path = os.path.join(playground_path, "codebases", session.id)
                    os.makedirs(target_path, exist_ok=True)
                    
                    logger.info(f"Copying local source from {container_check_path} to {target_path}")
                    
                    for item in os.listdir(container_check_path):
                        src_item = os.path.join(container_check_path, item)
                        dst_item = os.path.join(target_path, item)
                        
                        if os.path.isdir(src_item):
                            shutil.copytree(src_item, dst_item, dirs_exist_ok=True)
                        else:
                            shutil.copy2(src_item, dst_item)
                    
                    container_source_path = f"/playground/codebases/{session.id}"
            
            # Create workspace directory for CPG storage
            os.makedirs(workspace_path, exist_ok=True)
            
            # Ensure playground/cpgs directory exists
            cpgs_dir = os.path.join(playground_path, "cpgs")
            os.makedirs(cpgs_dir, exist_ok=True)
            
            # Check if CPG already exists in cache
            cpg_cache_path = get_cpg_cache_path(source_path, language, playground_path)
            cpg_exists = os.path.exists(cpg_cache_path)
            
            if cpg_exists:
                logger.info(f"Found existing CPG in cache: {cpg_cache_path}")
                # Copy cached CPG to workspace
                import shutil
                cpg_path = os.path.join(workspace_path, "cpg.bin")
                shutil.copy2(cpg_cache_path, cpg_path)
                
                # Start Docker container with playground mount
                container_id = await docker_orch.start_container(
                    session_id=session.id,
                    workspace_path=workspace_path,
                    playground_path=playground_path
                )
                
                # Register container with CPG generator
                cpg_generator.register_session_container(session.id, container_id)
                
                # Update session as ready immediately
                await session_manager.update_session(
                    session_id=session.id,
                    container_id=container_id,
                    status=SessionStatus.READY.value,
                    cpg_path=cpg_path
                )
                
                # Map container to session
                redis_client = services['redis']
                await redis_client.set_container_mapping(
                    container_id,
                    session.id,
                    services['config'].sessions.ttl
                )
                
                return {
                    "session_id": session.id,
                    "status": SessionStatus.READY.value,
                    "message": "Loaded existing CPG from cache",
                    "cached": True
                }
            else:
                logger.info(f"No cached CPG found, will generate new one")
                
                # Start Docker container with playground mount
                container_id = await docker_orch.start_container(
                    session_id=session.id,
                    workspace_path=workspace_path,
                    playground_path=playground_path
                )
                
                # Register container with CPG generator
                cpg_generator.register_session_container(session.id, container_id)
                
                # Update session with container ID
                await session_manager.update_session(
                    session_id=session.id,
                    container_id=container_id,
                    status=SessionStatus.GENERATING.value
                )
                
                # Map container to session
                redis_client = services['redis']
                await redis_client.set_container_mapping(
                    container_id,
                    session.id,
                    services['config'].sessions.ttl
                )
                
                # Start async CPG generation
                cpg_path = os.path.join(workspace_path, "cpg.bin")
                
                # Create a task that will also cache the CPG after generation
                async def generate_and_cache():
                    await cpg_generator.generate_cpg(
                        session_id=session.id,
                        source_path=container_source_path,
                        language=language
                    )
                    # Cache the CPG after successful generation
                    if os.path.exists(cpg_path):
                        import shutil
                        shutil.copy2(cpg_path, cpg_cache_path)
                        logger.info(f"Cached CPG to: {cpg_cache_path}")
                
                asyncio.create_task(generate_and_cache())
                
                return {
                    "session_id": session.id,
                    "status": SessionStatus.GENERATING.value,
                    "message": "CPG generation started",
                    "estimated_time": "2-5 minutes",
                    "cached": False
                }
            
        except ValidationError as e:
            logger.error(f"Validation error: {e}")
            return {
                "success": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": str(e)
                }
            }
        except ResourceLimitError as e:
            logger.error(f"Resource limit error: {e}")
            return {
                "success": False,
                "error": {
                    "code": "RESOURCE_LIMIT_EXCEEDED",
                    "message": str(e)
                }
            }
        except Exception as e:
            logger.error(f"Failed to create session: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Failed to create session",
                    "details": str(e)
                }
            }

    @mcp.tool()
    async def run_cpgql_query_async(
        session_id: str,
        query: str,
        timeout: int = 30,
        limit: Optional[int] = 150
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
            
            session_manager = services['session_manager']
            query_executor = services['query_executor']
            
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
                cpg_path=session.cpg_path,
                query=query,
                timeout=timeout,
                limit=limit
            )
            
            return {
                "success": True,
                "query_id": query_id,
                "status": "pending",
                "message": "Query started successfully"
            }
            
        except SessionNotFoundError as e:
            logger.error(f"Session not found: {e}")
            return {
                "success": False,
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "message": str(e)
                }
            }
        except SessionNotReadyError as e:
            logger.warning(f"Session not ready: {e}")
            return {
                "success": False,
                "error": {
                    "code": "SESSION_NOT_READY",
                    "message": str(e)
                }
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Failed to start query",
                    "details": str(e)
                }
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
            query_executor = services['query_executor']
            
            status_info = await query_executor.get_query_status(query_id)
            
            return {
                "success": True,
                **status_info
            }
            
        except QueryExecutionError as e:
            logger.error(f"Query status error: {e}")
            return {
                "success": False,
                "error": {
                    "code": "QUERY_NOT_FOUND",
                    "message": str(e)
                }
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
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
            query_executor = services['query_executor']
            
            result = await query_executor.get_query_result(query_id)
            
            return {
                "success": result.success,
                "data": result.data,
                "row_count": result.row_count,
                "execution_time": result.execution_time,
                "error": result.error
            }
            
        except QueryExecutionError as e:
            logger.error(f"Query result error: {e}")
            return {
                "success": False,
                "error": {
                    "code": "QUERY_ERROR",
                    "message": str(e)
                }
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    @mcp.tool()
    async def cleanup_queries(
        session_id: Optional[str] = None,
        max_age_hours: int = 1
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
            query_executor = services['query_executor']
            
            max_age_seconds = max_age_hours * 3600
            
            if session_id:
                # Get queries for specific session
                queries = await query_executor.list_queries(session_id)
                cleaned_count = 0
                
                for query_id, query_info in queries.items():
                    if query_info["status"] in ["completed", "failed"]:
                        age = time.time() - query_info.get("completed_at", query_info["created_at"])
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
                "message": f"Cleaned up {cleaned_count} old queries"
            }
            
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    @mcp.tool()
    async def run_cpgql_query(
        session_id: str,
        query: str,
        timeout: int = 30,
        limit: Optional[int] = 150
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
            
            session_manager = services['session_manager']
            query_executor = services['query_executor']
            
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
                limit=limit
            )
            
            return {
                "success": result.success,
                "data": result.data,
                "row_count": result.row_count,
                "execution_time": result.execution_time,
                "error": result.error
            }
            
        except SessionNotFoundError as e:
            logger.error(f"Session not found: {e}")
            return {
                "success": False,
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "message": str(e)
                }
            }
        except SessionNotReadyError as e:
            logger.warning(f"Session not ready: {e}")
            return {
                "success": False,
                "error": {
                    "code": "SESSION_NOT_READY",
                    "message": str(e)
                }
            }
        except QueryExecutionError as e:
            logger.error(f"Query execution error: {e}")
            return {
                "success": False,
                "error": {
                    "code": "QUERY_EXECUTION_ERROR",
                    "message": str(e)
                }
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Query execution failed",
                    "details": str(e)
                }
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
            
            session_manager = services['session_manager']
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
                "error_message": session.error_message
            }
            
        except SessionNotFoundError as e:
            logger.error(f"Session not found: {e}")
            return {
                "success": False,
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "message": str(e)
                }
            }
        except Exception as e:
            logger.error(f"Error getting session status: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    @mcp.tool()
    async def list_sessions(
        status: Optional[str] = None,
        source_type: Optional[str] = None
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
            session_manager = services['session_manager']
            
            filters = {}
            if status:
                filters['status'] = status
            if source_type:
                filters['source_type'] = source_type
            
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
                        "last_accessed": s.last_accessed.isoformat()
                    }
                    for s in sessions
                ],
                "total": len(sessions)
            }
            
        except Exception as e:
            logger.error(f"Error listing sessions: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
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
            
            session_manager = services['session_manager']
            docker_orch = services['docker']
            
            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")
            
            # Stop container
            if session.container_id:
                await docker_orch.stop_container(session.container_id)
            
            # Cleanup session
            await session_manager.cleanup_session(session_id)
            
            return {
                "success": True,
                "message": "Session closed successfully"
            }
            
        except SessionNotFoundError as e:
            logger.error(f"Session not found: {e}")
            return {
                "success": False,
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "message": str(e)
                }
            }
        except Exception as e:
            logger.error(f"Error closing session: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    @mcp.tool()
    async def cleanup_all_sessions(
        max_age_hours: Optional[int] = None,
        force: bool = False
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
            session_manager = services['session_manager']
            docker_orch = services['docker']
            
            # Get all sessions
            all_sessions = await session_manager.list_sessions({})
            
            sessions_to_cleanup = []
            
            for session in all_sessions:
                should_cleanup = False
                
                if force:
                    should_cleanup = True
                elif max_age_hours:
                    age = datetime.utcnow() - session.last_accessed
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
                "message": f"Cleaned up {len(cleaned_session_ids)} sessions"
            }
            
            if errors:
                result["errors"] = errors
                result["message"] += f" ({len(errors)} errors)"
            
            return result
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    @mcp.tool()
    async def list_files(
        session_id: str,
        pattern: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List all source files in the analyzed codebase.
        
        This tool helps discover the structure of the codebase by listing all files
        that were analyzed. Useful for understanding project layout and finding
        specific files of interest.
        
        Args:
            session_id: The session ID from create_cpg_session
            pattern: Optional regex pattern to filter file paths (e.g., ".*\\.java$" for Java files)
        
        Returns:
            {
                "success": true,
                "files": [
                    {"name": "main.c", "path": "/path/to/main.c"},
                    {"name": "utils.c", "path": "/path/to/utils.c"}
                ],
                "total": 2
            }
        """
        try:
            validate_session_id(session_id)
            
            session_manager = services['session_manager']
            query_executor = services['query_executor']
            
            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")
            
            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")
            
            await session_manager.touch_session(session_id)
            
            # Query for all files
            query = "cpg.file.map(f => (f.name, f.name))"
            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=500  # Reasonable limit for file listing
            )
            
            if not result.success:
                return {
                    "success": False,
                    "error": {
                        "code": "QUERY_ERROR",
                        "message": result.error
                    }
                }
            
            files = []
            for item in result.data:
                if isinstance(item, dict) and "_1" in item:
                    file_path = item["_1"]
                    file_name = file_path.split("/")[-1] if "/" in file_path else file_path
                    
                    # Apply pattern filter if provided
                    if pattern:
                        import re
                        if not re.search(pattern, file_path):
                            continue
                    
                    files.append({
                        "name": file_name,
                        "path": file_path
                    })
            
            return {
                "success": True,
                "files": files,
                "total": len(files)
            }
            
        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error listing files: {e}")
            return {
                "success": False,
                "error": {
                    "code": type(e).__name__.upper(),
                    "message": str(e)
                }
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    @mcp.tool()
    async def list_methods(
        session_id: str,
        name_pattern: Optional[str] = None,
        file_pattern: Optional[str] = None,
        include_external: bool = False,
        limit: int = 100
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
            include_external: Include external/library methods (default: false)
            limit: Maximum number of results (default: 100)
        
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
            
            session_manager = services['session_manager']
            query_executor = services['query_executor']
            
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
                query_parts.append(f'.filename("{file_pattern}")')
            
            query_parts.append(".map(m => (m.name, m.fullName, m.signature, m.filename, m.lineNumber.getOrElse(-1), m.isExternal))")
            
            query = "".join(query_parts) + f".take({limit})"
            
            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=limit  # Use the limit parameter
            )
            
            if not result.success:
                return {
                    "success": False,
                    "error": {
                        "code": "QUERY_ERROR",
                        "message": result.error
                    }
                }
            
            methods = []
            for item in result.data:
                if isinstance(item, dict):
                    methods.append({
                        "name": item.get("_1", ""),
                        "fullName": item.get("_2", ""),
                        "signature": item.get("_3", ""),
                        "filename": item.get("_4", ""),
                        "lineNumber": item.get("_5", -1),
                        "isExternal": item.get("_6", False)
                    })
            
            return {
                "success": True,
                "methods": methods,
                "total": len(methods)
            }
            
        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error listing methods: {e}")
            return {
                "success": False,
                "error": {
                    "code": type(e).__name__.upper(),
                    "message": str(e)
                }
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    @mcp.tool()
    async def get_method_source(
        session_id: str,
        method_name: str,
        filename: Optional[str] = None
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
                        "code": "int main() { ... }"
                    }
                ],
                "total": 1
            }
        """
        try:
            validate_session_id(session_id)
            
            session_manager = services['session_manager']
            query_executor = services['query_executor']
            
            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")
            
            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")
            
            await session_manager.touch_session(session_id)
            
            # Build query
            query_parts = [f'cpg.method.name("{method_name}")']
            
            if filename:
                query_parts.append(f'.filename(".*{filename}.*")')
            
            query_parts.append(".map(m => (m.name, m.filename, m.lineNumber.getOrElse(-1), m.code))")
            query = "".join(query_parts) + ".toJsonPretty"
            
            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=10
            )
            
            if not result.success:
                return {
                    "success": False,
                    "error": {
                        "code": "QUERY_ERROR",
                        "message": result.error
                    }
                }
            
            methods = []
            for item in result.data:
                if isinstance(item, dict):
                    methods.append({
                        "name": item.get("_1", ""),
                        "filename": item.get("_2", ""),
                        "lineNumber": item.get("_3", -1),
                        "code": item.get("_4", "")
                    })
            
            return {
                "success": True,
                "methods": methods,
                "total": len(methods)
            }
            
        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error getting method source: {e}")
            return {
                "success": False,
                "error": {
                    "code": type(e).__name__.upper(),
                    "message": str(e)
                }
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    @mcp.tool()
    async def list_calls(
        session_id: str,
        caller_pattern: Optional[str] = None,
        callee_pattern: Optional[str] = None,
        limit: int = 100
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
            
            session_manager = services['session_manager']
            query_executor = services['query_executor']
            
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
            
            query_parts.append(".map(c => (c.method.name, c.name, c.code, c.filename, c.lineNumber.getOrElse(-1)))")
            
            query = "".join(query_parts) + f".take({limit})"
            
            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=limit  # Use the limit parameter
            )
            
            if not result.success:
                return {
                    "success": False,
                    "error": {
                        "code": "QUERY_ERROR",
                        "message": result.error
                    }
                }
            
            calls = []
            for item in result.data:
                if isinstance(item, dict):
                    caller = item.get("_1", "")
                    
                    # Apply caller filter if provided
                    if caller_pattern:
                        import re
                        if not re.search(caller_pattern, caller):
                            continue
                    
                    calls.append({
                        "caller": caller,
                        "callee": item.get("_2", ""),
                        "code": item.get("_3", ""),
                        "filename": item.get("_4", ""),
                        "lineNumber": item.get("_5", -1)
                    })
            
            return {
                "success": True,
                "calls": calls,
                "total": len(calls)
            }
            
        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error listing calls: {e}")
            return {
                "success": False,
                "error": {
                    "code": type(e).__name__.upper(),
                    "message": str(e)
                }
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    @mcp.tool()
    async def get_call_graph(
        session_id: str,
        method_name: str,
        depth: int = 2,
        direction: str = "outgoing"
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
            
            session_manager = services['session_manager']
            query_executor = services['query_executor']
            
            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")
            
            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")
            
            await session_manager.touch_session(session_id)
            
            # Build query based on direction
            if direction == "outgoing":
                # Methods that the target method calls
                if depth == 1:
                    query = f'cpg.method.name("{method_name}").call.map(c => (c.method.name, c.name, 1)).toJsonPretty'
                elif depth == 2:
                    query = f'''cpg.method.name("{method_name}").call.flatMap(c1 => 
                        List((c1.method.name, c1.name, 1)) ++ 
                        c1.callee.flatMap(m => m.call.map(c2 => (c1.name, c2.name, 2)))
                    ).toJsonPretty'''
                else:  # depth == 3
                    query = f'''cpg.method.name("{method_name}").call.flatMap(c1 =>
                        List((c1.method.name, c1.name, 1)) ++
                        c1.callee.flatMap(m1 => m1.call.flatMap(c2 =>
                            List((c1.name, c2.name, 2)) ++
                            c2.callee.flatMap(m2 => m2.call.map(c3 => (c2.name, c3.name, 3)))
                        ))
                    ).toJsonPretty'''
            else:  # incoming
                # Methods that call the target method
                query = f'cpg.method.name("{method_name}").caller.map(m => ("CALLER", m.name, 1)).toJsonPretty'
            
            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=60,
                limit=200
            )
            
            if not result.success:
                return {
                    "success": False,
                    "error": {
                        "code": "QUERY_ERROR",
                        "message": result.error
                    }
                }
            
            calls = []
            for item in result.data:
                if isinstance(item, dict):
                    calls.append({
                        "from": item.get("_1", ""),
                        "to": item.get("_2", ""),
                        "depth": item.get("_3", 1)
                    })
            
            return {
                "success": True,
                "root_method": method_name,
                "direction": direction,
                "calls": calls,
                "total": len(calls)
            }
            
        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error getting call graph: {e}")
            return {
                "success": False,
                "error": {
                    "code": type(e).__name__.upper(),
                    "message": str(e)
                }
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    @mcp.tool()
    async def list_parameters(
        session_id: str,
        method_name: str
    ) -> Dict[str, Any]:
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
            
            session_manager = services['session_manager']
            query_executor = services['query_executor']
            
            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")
            
            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")
            
            await session_manager.touch_session(session_id)
            
            query = f'cpg.method.name("{method_name}").map(m => (m.name, m.parameter.map(p => (p.name, p.typeFullName, p.index)).l)).toJsonPretty'
            
            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=10
            )
            
            if not result.success:
                return {
                    "success": False,
                    "error": {
                        "code": "QUERY_ERROR",
                        "message": result.error
                    }
                }
            
            methods = []
            for item in result.data:
                if isinstance(item, dict) and "_1" in item and "_2" in item:
                    params = []
                    param_list = item.get("_2", [])
                    
                    for param_data in param_list:
                        if isinstance(param_data, dict):
                            params.append({
                                "name": param_data.get("_1", ""),
                                "type": param_data.get("_2", ""),
                                "index": param_data.get("_3", -1)
                            })
                    
                    methods.append({
                        "method": item.get("_1", ""),
                        "parameters": params
                    })
            
            return {
                "success": True,
                "methods": methods,
                "total": len(methods)
            }
            
        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error listing parameters: {e}")
            return {
                "success": False,
                "error": {
                    "code": type(e).__name__.upper(),
                    "message": str(e)
                }
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    @mcp.tool()
    async def find_literals(
        session_id: str,
        pattern: Optional[str] = None,
        literal_type: Optional[str] = None,
        limit: int = 50
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
            
            session_manager = services['session_manager']
            query_executor = services['query_executor']
            
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
            
            query_parts.append(".map(lit => (lit.code, lit.typeFullName, lit.filename, lit.lineNumber.getOrElse(-1), lit.method.name))")
            query = "".join(query_parts) + f".take({limit})"
            
            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=limit  # Use the limit parameter
            )
            
            if not result.success:
                return {
                    "success": False,
                    "error": {
                        "code": "QUERY_ERROR",
                        "message": result.error
                    }
                }
            
            literals = []
            for item in result.data:
                if isinstance(item, dict):
                    literals.append({
                        "value": item.get("_1", ""),
                        "type": item.get("_2", ""),
                        "filename": item.get("_3", ""),
                        "lineNumber": item.get("_4", -1),
                        "method": item.get("_5", "")
                    })
            
            return {
                "success": True,
                "literals": literals,
                "total": len(literals)
            }
            
        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error finding literals: {e}")
            return {
                "success": False,
                "error": {
                    "code": type(e).__name__.upper(),
                    "message": str(e)
                }
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

    @mcp.tool()
    async def get_codebase_summary(
        session_id: str
    ) -> Dict[str, Any]:
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
            
            session_manager = services['session_manager']
            query_executor = services['query_executor']
            
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
                limit=1
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
                limit=1
            )
            
            summary = {
                "language": language,
                "total_files": 0,
                "total_methods": 0,
                "user_defined_methods": 0,
                "total_calls": 0,
                "total_literals": 0
            }
            
            if stats_result.success and stats_result.data:
                item = stats_result.data[0]
                if isinstance(item, dict):
                    summary["total_files"] = item.get("_1", 0)
                    summary["total_methods"] = item.get("_2", 0)
                    summary["user_defined_methods"] = item.get("_3", 0)
                    summary["total_calls"] = item.get("_4", 0)
                    summary["total_literals"] = item.get("_5", 0)
                    summary["external_methods"] = summary["total_methods"] - summary["user_defined_methods"]
            
            return {
                "success": True,
                "summary": summary
            }
            
        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error getting codebase summary: {e}")
            return {
                "success": False,
                "error": {
                    "code": type(e).__name__.upper(),
                    "message": str(e)
                }
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(e)
                }
            }

