"""
Docker orchestration for Joern MCP Server
"""

import logging
import os
from typing import Optional

import docker

logger = logging.getLogger(__name__)


class DockerOrchestrator:
    """Manages Docker containers for Joern CPG generation and analysis"""

    def __init__(self):
        self.client: Optional[docker.DockerClient] = None

    async def initialize(self):
        """Initialize Docker client"""
        try:
            self.client = docker.from_env()
            self.client.ping()
            logger.info("Docker client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            raise

    async def start_container(
        self, session_id: str, workspace_path: str, playground_path: str
    ) -> str:
        """Start a Docker container for the session"""
        try:
            if not self.client:
                raise RuntimeError("Docker client not initialized")

            # Ensure directories exist
            os.makedirs(workspace_path, exist_ok=True)
            os.makedirs(playground_path, exist_ok=True)

            # Container configuration
            container_name = f"joern-session-{session_id}"

            # Mount both workspace and playground
            volumes = {
                workspace_path: {"bind": "/workspace", "mode": "rw"},
                playground_path: {"bind": "/playground", "mode": "rw"},
            }

            # Start container with Joern image
            container = self.client.containers.run(
                image="joern:latest",
                name=container_name,
                volumes=volumes,
                detach=True,
                remove=False,  # Keep container for debugging
                working_dir="/workspace",
                command="sleep infinity",  # Keep container running
            )

            logger.info(f"Started container {container.id} for session {session_id}")
            return container.id

        except Exception as e:
            logger.error(f"Failed to start container for session {session_id}: {e}")
            raise

    async def stop_container(self, container_id: str):
        """Stop and remove a Docker container"""
        try:
            if not self.client:
                logger.warning("Docker client not initialized, cannot stop container")
                return

            container = self.client.containers.get(container_id)
            container.stop(timeout=10)
            container.remove()

            logger.info(f"Stopped and removed container {container_id}")

        except docker.errors.NotFound:
            logger.warning(
                f"Container {container_id} not found, may already be removed"
            )
        except Exception as e:
            logger.error(f"Failed to stop container {container_id}: {e}")

    async def cleanup(self):
        """Cleanup all running containers"""
        try:
            if not self.client:
                return

            # Find all containers with joern-session prefix
            containers = self.client.containers.list(
                filters={"name": "joern-session-*"}
            )

            for container in containers:
                try:
                    container.stop(timeout=5)
                    container.remove()
                    logger.info(f"Cleaned up container {container.id}")
                except Exception as e:
                    logger.error(f"Failed to cleanup container {container.id}: {e}")

        except Exception as e:
            logger.error(f"Error during Docker cleanup: {e}")
