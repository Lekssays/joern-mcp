"""
CPG Generator for creating Code Property Graphs using Docker containers
"""
import asyncio
import logging
import os
import docker
from typing import AsyncIterator, Optional, Dict

from ..models import CPGConfig, SessionStatus
from ..exceptions import CPGGenerationError
from .session_manager import SessionManager

logger = logging.getLogger(__name__)


class CPGGenerator:
    """Generates CPG from source code using Docker containers"""

    # Language-specific Joern commands
    LANGUAGE_COMMANDS = {
        "java": "javasrc2cpg",
        "c": "c2cpg",
        "cpp": "c2cpg", 
        "javascript": "jssrc2cpg",
        "python": "pysrc2cpg",
        "go": "gosrc2cpg",
        "kotlin": "kotlin2cpg",
    }

    def __init__(
        self,
        config: CPGConfig,
        session_manager: Optional[SessionManager] = None
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
        self,
        session_id: str,
        workspace_path: str
    ) -> str:
        """Create a new Docker container for a session"""
        try:
            container_name = f"joern-session-{session_id}"
            
            # Container configuration for interactive Joern shell
            container_config = {
                "image": "joern:latest",
                "name": container_name,
                "detach": True,
                "volumes": {
                    workspace_path: {
                        "bind": "/workspace", 
                        "mode": "rw"
                    }
                },
                "working_dir": "/workspace",
                "environment": {
                    "JAVA_OPTS": "-Xmx4g"
                },
                "command": "tail -f /dev/null",  # Keep container running
                "network_mode": "bridge"
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
        self,
        session_id: str,
        source_path: str,
        language: str
    ) -> str:
        """Generate CPG from source code in container"""
        try:
            logger.info(f"Starting CPG generation for session {session_id}")
            
            if self.session_manager:
                await self.session_manager.update_status(
                    session_id,
                    SessionStatus.GENERATING.value
                )
            
            container_id = self.session_containers.get(session_id)
            if not container_id:
                raise CPGGenerationError(f"No container found for session {session_id}")
            
            container = self.docker_client.containers.get(container_id)
            
            # Generate CPG using Joern - store in playground/cpgs directory
            cpg_filename = f"{session_id}.cpg"
            cpg_output_path = f"/playground/cpgs/{cpg_filename}"
            base_cmd = self.LANGUAGE_COMMANDS[language]
            joern_cmd = await self._find_joern_executable(container, base_cmd)
            command = f"{joern_cmd} /workspace -o {cpg_output_path}"
            
            logger.info(f"Executing CPG generation command: {command}")
            
            # Execute with timeout
            try:
                result = await asyncio.wait_for(
                    self._exec_command_async(container, command),
                    timeout=self.config.generation_timeout
                )
                
                logger.info(f"CPG generation output:\n{result}")
                
                # Validate CPG was created
                if await self._validate_cpg_async(container, cpg_output_path):
                    if self.session_manager:
                        await self.session_manager.update_session(
                            session_id,
                            status=SessionStatus.READY.value,
                            cpg_path=cpg_output_path
                        )
                    logger.info(f"CPG generation completed for session {session_id}")
                    return cpg_output_path
                else:
                    error_msg = "CPG file was not created"
                    logger.error(error_msg)
                    if self.session_manager:
                        await self.session_manager.update_status(
                            session_id,
                            SessionStatus.ERROR.value,
                            error_msg
                        )
                    raise CPGGenerationError(error_msg)
                    
            except asyncio.TimeoutError:
                error_msg = f"CPG generation timed out after {self.config.generation_timeout}s"
                logger.error(error_msg)
                if self.session_manager:
                    await self.session_manager.update_status(
                        session_id,
                        SessionStatus.ERROR.value,
                        error_msg
                    )
                raise CPGGenerationError(error_msg)
                
        except CPGGenerationError:
            raise
        except Exception as e:
            error_msg = f"CPG generation failed: {str(e)}"
            logger.error(error_msg)
            if self.session_manager:
                await self.session_manager.update_status(
                    session_id,
                    SessionStatus.ERROR.value,
                    error_msg
                )
            raise CPGGenerationError(error_msg)

    async def _find_joern_executable(self, container, base_cmd: str) -> str:
        """Find the correct path for Joern executable in container"""
        try:
            possible_paths = [
                f"/opt/joern/joern-cli/{base_cmd}",  # Most likely location
                f"/opt/joern/joern-cli/{base_cmd}.sh",  # Shell script version
                f"/opt/joern/bin/{base_cmd}",  # Alternative location
                f"/usr/local/bin/{base_cmd}",  # System location
                base_cmd  # In PATH
            ]
            
            loop = asyncio.get_event_loop()
            
            for path in possible_paths:
                def _test_path():
                    result = container.exec_run(f"test -x {path}")
                    return result.exit_code
                
                exit_code = await loop.run_in_executor(None, _test_path)
                if exit_code == 0:
                    logger.info(f"Found Joern executable at: {path}")
                    return path
            
            # Fallback - list what's available in the joern-cli directory
            logger.warning("Joern executable not found in expected paths, listing available commands...")
            
            def _find_commands():
                result = container.exec_run("ls -la /opt/joern/joern-cli/ | grep -E '(c2cpg|javasrc2cpg|pysrc2cpg|jssrc2cpg)' || echo 'Joern CLI tools not found'")
                return result.output.decode('utf-8', errors='ignore')
            
            available = await loop.run_in_executor(None, _find_commands)
            logger.info(f"Available Joern CLI tools: {available}")
            
            # Since the tools should be in PATH with our updated Dockerfile, try the base command
            logger.info(f"Using base command in PATH: {base_cmd}")
            return base_cmd
            
        except Exception as e:
            logger.error(f"Error finding Joern executable: {e}")
            return base_cmd

    async def _exec_command_async(self, container, command: str) -> str:
        """Execute command in container asynchronously"""
        loop = asyncio.get_event_loop()
        
        def _exec_sync():
            result = container.exec_run(command, workdir="/workspace")
            return result.output.decode('utf-8', errors='ignore')
        
        return await loop.run_in_executor(None, _exec_sync)

    async def _validate_cpg_async(self, container, cpg_path: str) -> bool:
        """Validate that CPG file was created successfully"""
        try:
            loop = asyncio.get_event_loop()
            
            def _check_file():
                # Check if file exists and get size using a more compatible command
                result = container.exec_run(f"ls -la {cpg_path}")
                return result.output.decode('utf-8', errors='ignore').strip()
            
            ls_result = await loop.run_in_executor(None, _check_file)
            
            # If ls succeeded and doesn't show "No such file", the file exists
            if "No such file" not in ls_result and cpg_path in ls_result:
                logger.info(f"CPG file created: {ls_result}")
                return True
            else:
                logger.error(f"CPG file not found: {ls_result}")
                return False
            
        except Exception as e:
            logger.error(f"CPG validation failed: {e}")
            return False

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
        self,
        session_id: str,
        source_path: str,
        language: str,
        output_path: str
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
            command = f"{joern_cmd} {source_path} -o {output_path}"
            
            # Execute command and stream output
            exec_result = container.exec_run(command, stream=True, workdir="/workspace")
            
            for line in exec_result.output:
                yield line.decode('utf-8', errors='ignore')
                
        except Exception as e:
            logger.error(f"Failed to stream logs: {e}")
            yield f"ERROR: {str(e)}\n"
