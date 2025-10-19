"""
Interactive query executor for running CPGQL queries with persistent
Joern shell in Docker containers
"""

import asyncio
import json
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, Optional

import docker

from ..exceptions import QueryExecutionError
from ..models import JoernConfig, QueryConfig, QueryResult
from ..utils.redis_client import RedisClient
from ..utils.validators import hash_query, validate_cpgql_query

logger = logging.getLogger(__name__)


class QueryStatus(str, Enum):
    """Query execution status"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class QueryExecutor:
    """Executes CPGQL queries using persistent Joern shells in Docker containers"""

    def __init__(
        self,
        config: QueryConfig,
        joern_config: JoernConfig,
        redis_client: Optional[RedisClient] = None,
        cpg_generator=None,
    ):
        self.config = config
        self.joern_config = joern_config
        self.redis = redis_client
        self.cpg_generator = cpg_generator
        self.docker_client: Optional[docker.DockerClient] = None
        self.session_containers: Dict[str, str] = {}  # session_id -> container_id
        self.session_cpgs: Dict[str, str] = {}
        self.query_status: Dict[str, Dict[str, Any]] = {}  # query_id -> status info

    async def initialize(self):
        """Initialize Docker client"""
        try:
            self.docker_client = docker.from_env()
            logger.info("QueryExecutor initialized with Docker client")
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            raise QueryExecutionError(f"Docker initialization failed: {str(e)}")

    def _get_joern_command(self) -> str:
        """Get the correct joern command path"""
        # With our updated Dockerfile, joern should be in PATH
        # But we can also specify the full path as fallback
        return "joern"

    def set_cpg_generator(self, cpg_generator):
        """Set reference to CPG generator"""
        self.cpg_generator = cpg_generator

    async def execute_query_async(
        self,
        session_id: str,
        query: str,
        timeout: Optional[int] = None,
        limit: Optional[int] = 150,
        offset: Optional[int] = None,
    ) -> str:
        """Execute a CPGQL query asynchronously and return query UUID"""
        try:
            # Generate unique query ID
            query_id = str(uuid.uuid4())

            # Validate query
            validate_cpgql_query(query)

            # Normalize query to ensure JSON output and pipe to file
            query_normalized = self._normalize_query_for_json(
                query.strip(), limit, offset
            )
            output_file = f"/tmp/query_{query_id}.json"
            query_with_pipe = f'{query_normalized} #> "{output_file}"'

            # Initialize query status
            self.query_status[query_id] = {
                "status": QueryStatus.PENDING.value,
                "session_id": session_id,
                "query": query,
                "output_file": output_file,
                "created_at": time.time(),
                "error": None,
            }

            # Start async execution
            asyncio.create_task(
                self._execute_query_background(
                    query_id, session_id, query_with_pipe, timeout
                )
            )

            logger.info(f"Started async query {query_id} for session {session_id}")
            return query_id

        except Exception as e:
            logger.error(f"Failed to start async query: {e}")
            raise QueryExecutionError(f"Query initialization failed: {str(e)}")

    async def _execute_query_background(
        self,
        query_id: str,
        session_id: str,
        query_with_pipe: str,
        timeout: Optional[int],
    ):
        """Execute query in background"""
        try:
            # Update status to running
            self.query_status[query_id]["status"] = QueryStatus.RUNNING.value
            self.query_status[query_id]["started_at"] = time.time()

            # Extract the normalized query (remove the pipe part)
            query_normalized = query_with_pipe.split(" #>")[0]

            # Check cache if enabled
            if self.config.cache_enabled and self.redis:
                query_hash_val = hash_query(query_normalized)
                cached = await self.redis.get_cached_query(session_id, query_hash_val)
                if cached:
                    logger.info(f"Query cache hit for session {session_id}")
                    # Update status to completed with cached result
                    self.query_status[query_id]["status"] = QueryStatus.COMPLETED.value
                    self.query_status[query_id]["completed_at"] = time.time()
                    self.query_status[query_id]["result"] = cached
                    return

            # Execute query using the same approach as sync queries
            result = await self._execute_query_in_shell(
                session_id, query_normalized, timeout or self.config.timeout
            )

            if result.success:
                # Update status to completed
                self.query_status[query_id]["status"] = QueryStatus.COMPLETED.value
                self.query_status[query_id]["completed_at"] = time.time()
                self.query_status[query_id]["result"] = result.to_dict()

                # Cache result if enabled
                if self.config.cache_enabled and self.redis:
                    query_hash_val = hash_query(query_normalized)
                    await self.redis.cache_query_result(
                        session_id,
                        query_hash_val,
                        result.to_dict(),
                        self.config.cache_ttl,
                    )

                logger.info(f"Query {query_id} completed successfully")
            else:
                # Update status to failed
                self.query_status[query_id]["status"] = QueryStatus.FAILED.value
                self.query_status[query_id]["error"] = result.error
                self.query_status[query_id]["completed_at"] = time.time()
                logger.error(f"Query {query_id} failed: {result.error}")

        except Exception as e:
            # Update status to failed
            self.query_status[query_id]["status"] = QueryStatus.FAILED.value
            self.query_status[query_id]["error"] = str(e)
            self.query_status[query_id]["completed_at"] = time.time()

            logger.error(f"Query {query_id} failed: {e}")

    async def get_query_status(self, query_id: str) -> Dict[str, Any]:
        """Get status of a query"""
        if query_id not in self.query_status:
            raise QueryExecutionError(f"Query {query_id} not found")

        status_info = self.query_status[query_id].copy()

        # Add execution time if completed
        if "completed_at" in status_info and "started_at" in status_info:
            status_info["execution_time"] = (
                status_info["completed_at"] - status_info["started_at"]
            )

        return status_info

    async def get_query_result(self, query_id: str) -> QueryResult:
        """Get result of a completed query"""
        if query_id not in self.query_status:
            raise QueryExecutionError(f"Query {query_id} not found")

        status_info = self.query_status[query_id]

        if status_info["status"] == QueryStatus.FAILED.value:
            return QueryResult(
                success=False,
                error=status_info.get("error", "Query failed"),
                execution_time=status_info.get("execution_time", 0),
            )

        if status_info["status"] != QueryStatus.COMPLETED.value:
            raise QueryExecutionError(
                f"Query {query_id} is not completed yet "
                f"(status: {status_info['status']})"
            )

        # Return the stored result
        if "result" in status_info:
            return QueryResult(**status_info["result"])
        else:
            # Fallback for compatibility
            execution_time = status_info.get("execution_time", 0)
            return QueryResult(
                success=True, data=[], row_count=0, execution_time=execution_time
            )

    async def _get_container_id(self, session_id: str) -> Optional[str]:
        """Get container ID for session"""
        if self.cpg_generator:
            container_id = await self.cpg_generator.get_container_id(session_id)
            logger.debug(
                f"Got container ID from CPG generator for session {session_id}: "
                f"{container_id}"
            )
            return container_id
        container_id = self.session_containers.get(session_id)
        logger.debug(
            f"Got container ID from local cache for session {session_id}: "
            f"{container_id}"
        )
        return container_id

    async def _read_file_from_container(self, session_id: str, file_path: str) -> str:
        """Read file content from Docker container"""
        container_id = await self._get_container_id(session_id)
        if not container_id:
            raise QueryExecutionError(f"No container found for session {session_id}")

        try:
            container = self.docker_client.containers.get(container_id)
            result = container.exec_run(f"cat {file_path}")

            if result.exit_code == 0:
                return result.output.decode("utf-8", errors="ignore")
            else:
                raise QueryExecutionError(
                    f"Failed to read file {file_path}: exit code {result.exit_code}"
                )

        except Exception as e:
            raise QueryExecutionError(f"Failed to read file {file_path}: {str(e)}")

    async def execute_query(
        self,
        session_id: str,
        cpg_path: str,
        query: str,
        timeout: Optional[int] = None,
        limit: Optional[int] = 150,
        offset: Optional[int] = None,
    ) -> QueryResult:
        """Execute a CPGQL query synchronously (for backwards compatibility)"""
        start_time = time.time()

        try:
            # Validate query
            validate_cpgql_query(query)

            # Normalize query to ensure JSON output
            query_normalized = self._normalize_query_for_json(
                query.strip(), limit, offset
            )

            # Check cache if enabled
            if self.config.cache_enabled and self.redis:
                query_hash_val = hash_query(query_normalized)
                cached = await self.redis.get_cached_query(session_id, query_hash_val)
                if cached:
                    logger.info(f"Query cache hit for session {session_id}")
                    cached["execution_time"] = time.time() - start_time
                    return QueryResult(**cached)

            # Use container CPG path consistently
            container_cpg_path = "/workspace/cpg.bin"

            # Ensure CPG is loaded in session
            await self._ensure_cpg_loaded(session_id, container_cpg_path)

            # Execute query
            timeout_val = timeout or self.config.timeout
            result = await self._execute_query_in_shell(
                session_id, query_normalized, timeout_val
            )
            result.execution_time = time.time() - start_time

            # Cache result if enabled
            if self.config.cache_enabled and self.redis and result.success:
                query_hash_val = hash_query(query_normalized)
                await self.redis.cache_query_result(
                    session_id, query_hash_val, result.to_dict(), self.config.cache_ttl
                )

            logger.info(
                f"Query executed for session {session_id}: "
                f"{result.row_count} rows in {result.execution_time:.2f}s"
            )

            return result

        except QueryExecutionError as e:
            logger.error(f"Query execution error: {e}")
            return QueryResult(
                success=False, error=str(e), execution_time=time.time() - start_time
            )
        except Exception as e:
            logger.error(f"Unexpected error executing query: {e}")
            logger.exception(e)
            return QueryResult(
                success=False,
                error=f"Query execution failed: {str(e)}",
                execution_time=time.time() - start_time,
            )

    async def list_queries(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """List all queries or queries for a specific session"""
        if session_id:
            return {
                query_id: status_info
                for query_id, status_info in self.query_status.items()
                if status_info["session_id"] == session_id
            }
        else:
            return self.query_status.copy()

    async def cleanup_query(self, query_id: str):
        """Clean up query resources"""
        if query_id in self.query_status:
            status_info = self.query_status[query_id]

            # Clean up output file if it exists
            if "output_file" in status_info:
                try:
                    session_id = status_info["session_id"]
                    output_file = status_info["output_file"]

                    # Execute rm command in container to clean up file
                    container_id = await self._get_container_id(session_id)
                    if container_id:
                        container = self.docker_client.containers.get(container_id)
                        container.exec_run(f"rm -f {output_file}")
                except Exception as e:
                    logger.warning(
                        f"Failed to cleanup output file for query {query_id}: {e}"
                    )

            # Remove from tracking
            del self.query_status[query_id]
            logger.info(f"Cleaned up query {query_id}")

    async def cleanup_old_queries(self, max_age_seconds: int = 3600):
        """Clean up old completed queries"""
        current_time = time.time()
        to_cleanup = []

        for query_id, status_info in self.query_status.items():
            if status_info["status"] in [
                QueryStatus.COMPLETED.value,
                QueryStatus.FAILED.value,
            ]:
                age = current_time - status_info.get(
                    "completed_at", status_info["created_at"]
                )
                if age > max_age_seconds:
                    to_cleanup.append(query_id)

        for query_id in to_cleanup:
            await self.cleanup_query(query_id)

        if to_cleanup:
            logger.info(f"Cleaned up {len(to_cleanup)} old queries")

    def _normalize_query_for_json(
        self,
        query: str,
        limit: Optional[int] = None,
        offset: Optional[int] = None
    ) -> str:
        """Normalize query to ensure JSON output"""
        import re

        # Remove any existing output modifiers
        query = query.strip()

        # Check if query already ends with .toJsonPretty (multi-line queries add
        # it manually)
        if query.endswith(".toJsonPretty"):
            return query

        # Check if this is a multi-line query (contains newlines or val statements)
        # Multi-line queries already handle their own JSON output
        if "\n" in query or query.startswith("val ") or "if (" in query:
            # Multi-line queries should have .toJsonPretty at the end already
            # If not, something is wrong, but don't modify them
            return query

        # For single-line queries, normalize to JSON output
        if query.endswith(".l"):
            query = query[:-2]
        elif query.endswith(".toList"):
            query = query[:-7]
        elif query.endswith(".toJson"):
            query = query[:-7]
        elif query.endswith(".toJsonPretty"):
            query = query[:-13]

        # Remove existing .take() and .drop() modifiers using regex
        query = re.sub(r"\.take\(\d+\)", "", query)
        query = re.sub(r"\.drop\(\d+\)", "", query)

        # Add offset if specified
        if offset is not None and offset > 0:
            query = f"{query}.drop({offset})"

        # Add limit if specified
        if limit is not None and limit > 0:
            query = f"{query}.take({limit})"

        # Add .toJsonPretty for proper JSON output
        return query + ".toJsonPretty"

    async def _ensure_cpg_loaded(self, session_id: str, cpg_path: str):
        """Ensure CPG is loaded in the Joern session"""
        # Load CPG if not already loaded or if different CPG
        current_cpg = self.session_cpgs.get(session_id)
        if current_cpg != cpg_path:
            await self._load_cpg_in_container(session_id, cpg_path)
            self.session_cpgs[session_id] = cpg_path

    async def _load_cpg_in_container(self, session_id: str, cpg_path: str):
        """Load CPG in the container using direct joern command"""
        logger.info(f"Loading CPG for session {session_id}: {cpg_path}")

        container_id = await self._get_container_id(session_id)
        if not container_id:
            logger.error(f"No container found for session {session_id}")
            raise QueryExecutionError(
                f"No container found for session {session_id}"
            )

        logger.info(
            f"Loading CPG {cpg_path} in container {
                container_id} for session {session_id}"
        )

        try:
            # Start Joern shell and load CPG in one command
            container = self.docker_client.containers.get(container_id)
            joern_cmd = self._get_joern_command()

            # Create a simple script to load CPG
            script_content = f"""#!/bin/bash
echo 'importCpg("{cpg_path}")' | {joern_cmd}
"""

            # Write script to container using a simpler approach
            script_result = container.exec_run(
                [
                    "sh",
                    "-c",
                    f"cat > /tmp/load_cpg.sh << 'EOF'\n{
                        script_content}EOF\nchmod +x /tmp/load_cpg.sh",
                ]
            )

            if script_result.exit_code != 0:
                error_output = (
                    script_result.output.decode("utf-8", errors="ignore")
                    if script_result.output
                    else "No output"
                )
                logger.error(f"Failed to create CPG loading script: {error_output}")
                raise QueryExecutionError(
                    f"Failed to create CPG loading script: {error_output}"
                )

            # Execute the script
            load_result = container.exec_run(["/bin/bash", "/tmp/load_cpg.sh"])

            if load_result.exit_code != 0:
                error_msg = (
                    load_result.output.decode("utf-8", errors="ignore")
                    if load_result.output
                    else "No output"
                )
                logger.error(f"Failed to load CPG: {error_msg}")
                raise QueryExecutionError(f"Failed to load CPG: {error_msg}")

            logger.info(f"CPG loaded successfully for session {session_id}")

        except Exception as e:
            logger.error(f"Failed to load CPG in container: {e}")
            raise QueryExecutionError(f"Failed to load CPG: {str(e)}")

    async def _execute_query_in_shell(
        self, session_id: str, query: str, timeout: int
    ) -> QueryResult:
        """Execute query in the container"""
        logger.debug(f"Executing query in session {session_id}: {query[:100]}...")

        container_id = await self._get_container_id(session_id)
        if not container_id:
            raise QueryExecutionError(f"No container found for session {session_id}")

        try:
            container = self.docker_client.containers.get(container_id)

            # Use the CPG file from workspace
            cpg_path = "/workspace/cpg.bin"

            # Create unique output file for this query
            output_file = f"/tmp/query_result_{session_id}_{int(time.time())}.json"

            # Create query with pipe to JSON file
            query_with_pipe = f'{query} #> "{output_file}"'

            # Create a simple script that loads CPG and executes query
            script_content = f"""#!/bin/bash
set -e

# Check if CPG file exists
if [ ! -f "{cpg_path}" ]; then
    echo "ERROR: CPG file not found at {cpg_path}" >&2
    exit 1
fi

# Execute joern with the query
echo '{query_with_pipe}' | timeout {timeout} joern {cpg_path}
"""

            # Write script to container
            script_result = container.exec_run(
                [
                    "sh",
                    "-c",
                    f"cat > /tmp/query.sh << 'SCRIPT_EOF'\n{
                        script_content}SCRIPT_EOF\nchmod +x /tmp/query.sh",
                ]
            )

            if script_result.exit_code != 0:
                error_output = (
                    script_result.output.decode("utf-8", errors="ignore")
                    if script_result.output
                    else "No output"
                )
                logger.error(f"Failed to create query script: {error_output}")
                raise QueryExecutionError(
                    f"Failed to create query script: {error_output}"
                )

            # Execute the script
            loop = asyncio.get_event_loop()

            def _exec_sync():
                result = container.exec_run(
                    ["/bin/bash", "/tmp/query.sh"], workdir="/workspace"
                )
                return result

            exec_result = await loop.run_in_executor(None, _exec_sync)

            logger.debug(f"Query execution exit code: {exec_result.exit_code}")

            if exec_result.exit_code != 0:
                output = (
                    exec_result.output.decode("utf-8", errors="ignore")
                    if exec_result.output
                    else ""
                )
                logger.error(
                    f"Query execution failed with exit code {
                        exec_result.exit_code}: {output}"
                )
                return QueryResult(
                    success=False, error=f"Query execution failed: {output}"
                )

            # Read the JSON result file
            try:

                def _read_file():
                    result = container.exec_run(f"cat {output_file}")
                    return result

                file_result = await loop.run_in_executor(None, _read_file)

                if file_result.exit_code != 0:
                    logger.error(
                        "Output file not generated, query failed due to "
                        "syntax error or not found attribute"
                    )
                    return QueryResult(
                        success=False,
                        error="Query failed: syntax error or attribute not found",
                    )

                json_content = file_result.output.decode("utf-8", errors="ignore")

                # Clean up the output file
                container.exec_run(f"rm -f {output_file}")

                if not json_content.strip():
                    return QueryResult(success=True, data=[], row_count=0)

                # Parse JSON content
                try:
                    data = json.loads(json_content)

                    # Normalize data to list
                    if isinstance(data, dict):
                        data = [data]
                    elif not isinstance(data, list):
                        data = [{"value": str(data)}]

                    logger.info(f"Successfully parsed {len(data)} results from query")

                    return QueryResult(success=True, data=data, row_count=len(data))

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON output: {e}")
                    logger.debug(f"Raw JSON content: {json_content[:500]}...")

                    # Return as string value if JSON parsing fails
                    return QueryResult(
                        success=True,
                        data=[{"value": json_content.strip()}],
                        row_count=1,
                    )

            except Exception as e:
                logger.error(f"Failed to read query result file: {e}")
                return QueryResult(
                    success=False, error=f"Failed to read result: {str(e)}"
                )

        except Exception as e:
            logger.error(f"Error executing query in container: {e}")
            return QueryResult(success=False, error=f"Query execution error: {str(e)}")

    async def close_session(self, session_id: str):
        """Close query executor session resources"""
        if session_id in self.session_cpgs:
            del self.session_cpgs[session_id]

        # Remove from container mapping if present
        if session_id in self.session_containers:
            del self.session_containers[session_id]

        logger.info(f"Closed query executor resources for session {session_id}")

    async def cleanup(self):
        """Cleanup all sessions and queries"""
        # Cleanup all queries
        query_ids = list(self.query_status.keys())
        for query_id in query_ids:
            await self.cleanup_query(query_id)

        # Cleanup session resources
        sessions = list(self.session_cpgs.keys())
        for session_id in sessions:
            await self.close_session(session_id)
