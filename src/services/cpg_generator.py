"""
CPG Generator for creating Code Property Graphs using Docker containers
"""

import asyncio
import logging
from typing import AsyncIterator, Dict, Optional

import docker

from ..exceptions import CPGGenerationError
from ..models import CPGConfig, SessionStatus, Config
from .session_manager import SessionManager

logger = logging.getLogger(__name__)


class CPGGenerator:
    """Generates CPG from source code using Docker containers"""

    # Language-specific Joern commands
    LANGUAGE_COMMANDS = {
        "java": "javasrc2cpg",
        "c": "c2cpg.sh",
        "cpp": "c2cpg.sh",
        "javascript": "jssrc2cpg.sh",
        "python": "pysrc2cpg",
        "go": "gosrc2cpg",
        "kotlin": "kotlin2cpg",
        "csharp": "csharpsrc2cpg",
        "ghidra": "ghidra2cpg",
        "jimple": "jimple2cpg",
        "php": "php2cpg",
        "ruby": "rubysrc2cpg",
        "swift": "swiftsrc2cpg.sh",
    }

    def __init__(
        self, config: Config, session_manager: Optional[SessionManager] = None
    ):
        self.config = config
        self.session_manager = session_manager
        self.docker_client: Optional[docker.DockerClient] = None
        self.session_containers: Dict[str, str] = {}  # session_id -> container_id

    async def initialize(self):
        """Initialize Docker client"""
        try:
            self.docker_client = docker.from_env()
            self.docker_client.ping()
            logger.info("CPG Generator Docker client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            raise CPGGenerationError(f"Docker initialization failed: {str(e)}")

    async def create_session_container(
        self, session_id: str, workspace_path: str
    ) -> str:
        """Create a new Docker container for a session"""
        try:
            container_name = f"joern-session-{session_id}"

            # Container configuration for interactive Joern shell
            container_config = {
                "image": "joern:latest",
                "name": container_name,
                "detach": True,
                "volumes": {workspace_path: {"bind": "/workspace", "mode": "rw"}},
                "working_dir": "/workspace",
                "environment": {"JAVA_OPTS": self.config.joern.java_opts},
                "command": "tail -f /dev/null",  # Keep container running
                "network_mode": "bridge",
            }

            container = self.docker_client.containers.run(**container_config)
            container_id = container.id

            self.session_containers[session_id] = container_id
            logger.info(f"Created container {container_id} for session {session_id}")

            return container_id

        except Exception as e:
            logger.error(f"Failed to create container for session {session_id}: {e}")
            raise CPGGenerationError(f"Container creation failed: {str(e)}")

    async def generate_cpg(
        self, session_id: str, source_path: str, language: str
    ) -> str:
        """Generate CPG from source code in container"""
        try:
            logger.info(f"Starting CPG generation for session {session_id}")

            if self.session_manager:
                await self.session_manager.update_status(
                    session_id, SessionStatus.GENERATING.value
                )

            container_id = self.session_containers.get(session_id)
            if not container_id:
                raise CPGGenerationError(f"No container found for session {session_id}")

            container = self.docker_client.containers.get(container_id)

            # Generate CPG using Joern - store in workspace directory
            cpg_output_path = "/workspace/cpg.bin"
            base_cmd = self.LANGUAGE_COMMANDS[language]
            joern_cmd = await self._find_joern_executable(container, base_cmd)
            
            # Compute Java options to pass to Joern. Prefer an explicit
            # configuration value, but if the container has a memory limit set
            # use that to tune -Xmx to avoid Java OOMs inside constrained
            # containers. Joern script accepts Java opts prefixed with -J.
            java_opts = self.config.joern.java_opts

            try:
                # Inspect container to find memory limit (in bytes). A value of
                # 0 usually means no limit.
                container_inspect = container.attrs
                mem_limit = 0
                host_config = container_inspect.get("HostConfig", {})
                if host_config:
                    mem_limit = host_config.get("Memory", 0) or 0

                # If mem_limit is set and reasonable, compute -Xmx as 75% of it
                if mem_limit and mem_limit > 0:
                    # Convert bytes to megabytes
                    mem_mb = int(mem_limit / (1024 * 1024))
                    xmx_mb = max(256, int(mem_mb * 0.75))
                    # Build Java opts using Xmx and a conservative Xms (half of Xmx)
                    xms_mb = max(128, int(xmx_mb / 2))
                    java_opts = f"-Xmx{int(xmx_mb)}M -Xms{int(xms_mb)}M -XX:+UseG1GC -Dfile.encoding=UTF-8"
                    logger.info(
                        f"Computed java opts from container memory {mem_mb}MB: {java_opts}"
                    )
                else:
                    # If no container memory limit, fall back to configured opts
                    java_opts = java_opts or self.config.joern.java_opts
            except Exception:
                # If anything goes wrong while inspecting the container,
                # fall back to configured java opts
                java_opts = java_opts or self.config.joern.java_opts

            if java_opts:
                java_flags = " ".join(f"-J{opt}" for opt in java_opts.split())
                joern_cmd = f"{joern_cmd} {java_flags}"

            # Build command with exclusions for various languages to focus on core
            # functionality
            command_parts = [f"{joern_cmd} {source_path} -o {cpg_output_path}"]

            # Apply exclusions for languages that support them
            if (
                language in self.config.cpg.languages_with_exclusions
                and self.config.cpg.exclusion_patterns
            ):
                # Use exclusion patterns from configuration
                combined_regex = "|".join(
                    f"({pattern})" for pattern in self.config.cpg.exclusion_patterns
                )
                command_parts.append(f'--exclude-regex "{combined_regex}"')

            command = " ".join(command_parts)

            logger.info(f"Executing CPG generation command: {command}")

            # Execute with timeout
            try:
                result = await asyncio.wait_for(
                    self._exec_command_async(container, command),
                    timeout=self.config.cpg.generation_timeout,
                )

                logger.info(f"CPG generation output:\n{result[:2000]}")

                # Known non-fatal warning tokens from Joern
                non_fatal_tokens = [
                    "FieldAccessLinkerPass",
                    "ReachingDefPass",
                    "The graph has been modified",
                    "WARN",
                    "Skipping.",
                ]

                # If the command produced a non-zero exit, the container.exec_run
                # wrapper returns the output string; rely on file validation to
                # determine real success. However, if the output contains fatal
                # error indicators (like 'ERROR' or 'Exception'), fail fast.
                if any("ERROR" in result or "Exception" in result for _ in [1]):
                    # Check whether the 'ERROR' lines look fatal (not just Joern WARN)
                    if "ERROR:" in result or "Exception" in result:
                        logger.error(f"CPG generation reported fatal errors:\n{result[:2000]}")
                        error_msg = "Joern reported fatal errors during CPG generation"
                        if self.session_manager:
                            await self.session_manager.update_status(
                                session_id, SessionStatus.ERROR.value, error_msg
                            )
                        raise CPGGenerationError(error_msg)

                # Validate CPG was created on disk; this is the real success check
                if await self._validate_cpg_async(container, cpg_output_path):
                    if self.session_manager:
                        await self.session_manager.update_session(
                            session_id,
                            status=SessionStatus.READY.value,
                            cpg_path=cpg_output_path,
                        )
                    logger.info(f"CPG generation completed for session {session_id}")
                    return cpg_output_path
                else:
                    # If file is missing, provide output context but don't choke on
                    # known warning-only logs
                    error_msg = "CPG file was not created"
                    logger.error(f"{error_msg}: {result[:2000]}")
                    if self.session_manager:
                        await self.session_manager.update_status(
                            session_id, SessionStatus.ERROR.value, error_msg
                        )
                    raise CPGGenerationError(error_msg)

            except asyncio.TimeoutError:
                error_msg = (
                    f"CPG generation timed out after {self.config.cpg.generation_timeout}s"
                )
                logger.error(error_msg)
                if self.session_manager:
                    await self.session_manager.update_status(
                        session_id, SessionStatus.ERROR.value, error_msg
                    )
                raise CPGGenerationError(error_msg)

        except CPGGenerationError:
            raise
        except Exception as e:
            error_msg = f"CPG generation failed: {str(e)}"
            logger.error(error_msg)
            if self.session_manager:
                await self.session_manager.update_status(
                    session_id, SessionStatus.ERROR.value, error_msg
                )
            raise CPGGenerationError(error_msg)

    async def _exec_command_async(self, container, command: str) -> str:
        """Execute command in container asynchronously"""
        loop = asyncio.get_event_loop()

        def _exec_sync():
            result = container.exec_run(command, workdir="/workspace")
            return result.output.decode("utf-8", errors="ignore")

        return await loop.run_in_executor(None, _exec_sync)

    async def _find_joern_executable(self, container, base_command: str) -> str:
        """Find the full path to a Joern executable in the container"""
        return f"/opt/joern/joern-cli/{base_command}"

    async def _validate_cpg_async(self, container, cpg_path: str) -> bool:
        """Validate that CPG file was created successfully and is not empty"""
        try:
            loop = asyncio.get_event_loop()

            def _check_file():
                # Check if file exists and get size using stat command
                result = container.exec_run(f"stat {cpg_path}")
                return result.output.decode("utf-8", errors="ignore").strip()

            stat_result = await loop.run_in_executor(None, _check_file)

            # Check if stat was successful (file exists)
            if "No such file" in stat_result or "cannot stat" in stat_result:
                logger.error(f"CPG file not found: {stat_result}")
                return False

            # Extract file size from stat output
            # stat output format contains "Size: <bytes>" line
            file_size = await self._extract_file_size_async(container, cpg_path)

            if file_size is None:
                logger.error("Could not determine CPG file size")
                return False

            # Check if file is too small (empty or nearly empty)
            # Joern CPGs typically have a minimum size; even small projects generate
            # CPGs > 1KB
            min_cpg_size = 1024  # 1KB minimum

            if file_size < min_cpg_size:
                logger.error(
                    f"CPG file is too small ({
                        file_size} bytes), likely empty or corrupted. "
                    f"Minimum expected size: {min_cpg_size} bytes"
                )
                return False

            logger.info(
                f"CPG file created successfully: {cpg_path} (size: {file_size} bytes)"
            )
            return True

        except Exception as e:
            logger.error(f"CPG validation failed: {e}")
            return False

    async def _extract_file_size_async(self, container, cpg_path: str) -> Optional[int]:
        """Extract file size from a file in the container"""
        try:
            loop = asyncio.get_event_loop()

            def _get_size():
                # Use a more reliable method to get file size
                result = container.exec_run(f"stat -c%s {cpg_path}")
                return result.output.decode("utf-8", errors="ignore").strip()

            size_str = await loop.run_in_executor(None, _get_size)

            # Try to parse the size
            try:
                return int(size_str)
            except ValueError:
                # Fallback: try alternative command if stat -c doesn't work
                logger.debug(
                    f"stat -c command returned: {size_str}, trying alternative method"
                )

                def _get_size_wc():
                    result = container.exec_run(f"wc -c < {cpg_path}")
                    return result.output.decode("utf-8", errors="ignore").strip()

                size_str = await loop.run_in_executor(None, _get_size_wc)
                return int(size_str)

        except Exception as e:
            logger.error(f"Failed to extract file size: {e}")
            return None

    async def get_container_id(self, session_id: str) -> Optional[str]:
        """Get container ID for session"""
        return self.session_containers.get(session_id)

    def register_session_container(self, session_id: str, container_id: str):
        """Register an externally created container with a session"""
        self.session_containers[session_id] = container_id
        logger.info(f"Registered container {container_id} for session {session_id}")

    async def close_session(self, session_id: str):
        """Close session container"""
        container_id = self.session_containers.get(session_id)
        if container_id:
            try:
                container = self.docker_client.containers.get(container_id)
                container.stop()
                container.remove()
                logger.info(f"Closed container {container_id} for session {session_id}")
            except Exception as e:
                logger.warning(f"Error closing container for session {session_id}: {e}")
            finally:
                del self.session_containers[session_id]

    async def cleanup(self):
        """Cleanup all session containers"""
        sessions = list(self.session_containers.keys())
        for session_id in sessions:
            await self.close_session(session_id)

    async def stream_logs(
        self, session_id: str, source_path: str, language: str, output_path: str
    ) -> AsyncIterator[str]:
        """Generate CPG and stream logs"""
        try:
            container_id = self.session_containers.get(session_id)
            if not container_id:
                yield f"ERROR: No container found for session {session_id}\n"
                return

            container = self.docker_client.containers.get(container_id)

            # Get the Joern command for the language
            if language not in self.LANGUAGE_COMMANDS:
                yield f"ERROR: Unsupported language: {language}\n"
                return

            base_cmd = self.LANGUAGE_COMMANDS[language]
            joern_cmd = await self._find_joern_executable(container, base_cmd)
            command_parts = [f"{joern_cmd} {source_path} -o {output_path}"]

            # Apply exclusions for languages that support them
            if (
                language in self.config.cpg.languages_with_exclusions
                and self.config.cpg.exclusion_patterns
            ):
                # Use exclusion patterns from configuration
                combined_regex = "|".join(
                    f"({pattern})" for pattern in self.config.cpg.exclusion_patterns
                )
                command_parts.append(f'--exclude-regex "{combined_regex}"')

            command = " ".join(command_parts)

            # Execute command and stream output
            exec_result = container.exec_run(command, stream=True, workdir="/workspace")

            for line in exec_result.output:
                yield line.decode("utf-8", errors="ignore")

        except Exception as e:
            logger.error(f"Failed to stream logs: {e}")
            yield f"ERROR: {str(e)}\n"
