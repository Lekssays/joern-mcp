"""
Tests for main module
"""

import main
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import main module

lifespan = main.lifespan


class TestLifespan:
    """Test FastMCP lifespan management"""

    @pytest.mark.asyncio
    async def test_lifespan_success(self):
        """Test successful lifespan startup and shutdown"""
        mock_mcp = AsyncMock()

        # Mock all the services and dependencies
        with patch("main.load_config") as mock_load_config, patch(
            "main.RedisClient"
        ) as mock_redis_client_class, patch(
            "main.SessionManager"
        ) as mock_session_manager_class, patch(
            "main.GitManager"
        ) as mock_git_manager_class, patch(
            "main.CPGGenerator"
        ) as mock_cpg_generator_class, patch(
            "main.DockerOrchestrator"
        ) as mock_docker_orch_class, patch(
            "main.QueryExecutor"
        ) as mock_query_executor_class, patch(
            "main.setup_logging"
        ) as mock_setup_logging, patch(
            "main.logger"
        ) as mock_logger, patch(
            "os.makedirs"
        ) as mock_makedirs:

            # Setup mocks
            mock_config = AsyncMock()
            mock_config.server.log_level = "INFO"
            mock_config.storage.workspace_root = "/tmp/workspace"
            mock_config.redis = AsyncMock()
            mock_config.sessions = AsyncMock()
            mock_config.cpg = AsyncMock()
            mock_config.query = AsyncMock()
            mock_config.joern = AsyncMock()

            mock_load_config.return_value = mock_config

            mock_redis_client = AsyncMock()
            mock_redis_client_class.return_value = mock_redis_client

            mock_session_manager = AsyncMock()
            mock_session_manager.set_docker_cleanup_callback = (
                MagicMock()
            )  # Override to be sync
            mock_session_manager_class.return_value = mock_session_manager

            mock_git_manager = AsyncMock()
            mock_git_manager_class.return_value = mock_git_manager

            mock_cpg_generator = AsyncMock()
            mock_cpg_generator_class.return_value = mock_cpg_generator

            mock_docker_orch = AsyncMock()
            mock_docker_orch_class.return_value = mock_docker_orch

            mock_query_executor = AsyncMock()
            mock_query_executor_class.return_value = mock_query_executor

            # Test lifespan context manager
            async with lifespan(mock_mcp):
                # Verify initialization calls
                mock_load_config.assert_called_with("config.yaml")
                mock_setup_logging.assert_called_with("INFO")
                mock_makedirs.assert_called()
                mock_redis_client.connect.assert_called_once()
                mock_session_manager.set_docker_cleanup_callback.assert_called_once()
                mock_cpg_generator.initialize.assert_called_once()
                mock_query_executor.initialize.assert_called_once()

            # Verify shutdown calls
            mock_query_executor.cleanup.assert_called_once()
            mock_docker_orch.cleanup.assert_called_once()
            mock_redis_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_initialization_failure(self):
        """Test lifespan with initialization failure"""
        mock_mcp = AsyncMock()

        with patch(
            "main.load_config", side_effect=Exception("Config load failed")
        ), patch("main.logger") as mock_logger:

            with pytest.raises(Exception, match="Config load failed"):
                async with lifespan(mock_mcp):
                    pass

    @pytest.mark.asyncio
    async def test_lifespan_redis_connection_failure(self):
        """Test lifespan with Redis connection failure"""
        mock_mcp = AsyncMock()

        with patch("main.load_config") as mock_load_config, patch(
            "main.RedisClient"
        ) as mock_redis_client_class, patch("main.setup_logging"), patch(
            "os.makedirs"
        ), patch(
            "main.logger"
        ) as mock_logger:

            mock_config = AsyncMock()
            mock_config.server.log_level = "INFO"
            mock_config.storage.workspace_root = "/tmp/workspace"
            mock_load_config.return_value = mock_config

            mock_redis_client = AsyncMock()
            mock_redis_client.connect = AsyncMock(
                side_effect=Exception("Redis connection failed")
            )
            mock_redis_client_class.return_value = mock_redis_client

            with pytest.raises(Exception, match="Redis connection failed"):
                async with lifespan(mock_mcp):
                    pass
