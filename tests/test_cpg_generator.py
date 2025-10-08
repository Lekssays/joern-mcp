"""
Tests for CPG generator
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call
from src.services.cpg_generator import CPGGenerator
from src.models import CPGConfig, SessionStatus
from src.services.session_manager import SessionManager
from src.exceptions import CPGGenerationError


class TestCPGGenerator:
    """Test CPG generator functionality"""

    @pytest.fixture
    def cpg_config(self):
        """CPG configuration fixture"""
        return CPGConfig(
            generation_timeout=600,
            max_repo_size_mb=500,
            supported_languages=["java", "python", "c", "cpp"]
        )

    @pytest.fixture
    def mock_session_manager(self):
        """Mock session manager fixture"""
        return AsyncMock(spec=SessionManager)

    @pytest.fixture
    def cpg_generator(self, cpg_config, mock_session_manager):
        """CPG generator fixture"""
        generator = CPGGenerator(cpg_config, mock_session_manager)
        return generator

    @pytest.mark.asyncio
    async def test_initialize_success(self, cpg_generator):
        """Test successful Docker client initialization"""
        mock_docker_client = MagicMock()
        mock_docker_client.ping = MagicMock()

        with patch('docker.from_env', return_value=mock_docker_client):
            await cpg_generator.initialize()

            assert cpg_generator.docker_client == mock_docker_client

    @pytest.mark.asyncio
    async def test_initialize_failure(self, cpg_generator):
        """Test Docker client initialization failure"""
        with patch('docker.from_env', side_effect=Exception("Docker not available")):
            with pytest.raises(CPGGenerationError, match="Docker initialization failed"):
                await cpg_generator.initialize()

    @pytest.mark.asyncio
    async def test_create_session_container(self, cpg_generator):
        """Test creating Docker container for session"""
        mock_container = MagicMock()
        mock_container.id = "container-123"

        mock_docker_client = MagicMock()
        mock_docker_client.containers.run = MagicMock(return_value=mock_container)
        cpg_generator.docker_client = mock_docker_client

        container_id = await cpg_generator.create_session_container(
            session_id="session-123",
            workspace_path="/tmp/workspace"
        )

        assert container_id == "container-123"
        assert cpg_generator.session_containers["session-123"] == "container-123"

        # Verify container creation call
        mock_docker_client.containers.run.assert_called_once()
        call_kwargs = mock_docker_client.containers.run.call_args[1]

        assert call_kwargs["image"] == "joern:latest"
        assert call_kwargs["name"] == "joern-session-session-123"
        assert call_kwargs["detach"] is True
        assert "/tmp/workspace" in str(call_kwargs["volumes"])

    @pytest.mark.asyncio
    async def test_create_session_container_failure(self, cpg_generator):
        """Test container creation failure"""
        mock_docker_client = MagicMock()
        mock_docker_client.containers.run = MagicMock(side_effect=Exception("Container creation failed"))
        cpg_generator.docker_client = mock_docker_client

        with pytest.raises(CPGGenerationError, match="Container creation failed"):
            await cpg_generator.create_session_container(
                session_id="session-123",
                workspace_path="/tmp/workspace"
            )

    @pytest.mark.asyncio
    async def test_generate_cpg_java(self, cpg_generator, mock_session_manager):
        """Test CPG generation for Java project"""
        # Setup mocks
        mock_container = MagicMock()
        mock_container.exec_run = MagicMock(return_value=MagicMock(output=b"CPG generated successfully", exit_code=0))

        mock_docker_client = MagicMock()
        mock_docker_client.containers.get = MagicMock(return_value=mock_container)
        cpg_generator.docker_client = mock_docker_client
        cpg_generator.session_containers["session-123"] = "container-123"

        # Mock the helper methods
        with patch.object(cpg_generator, '_find_joern_executable', return_value="javasrc2cpg"), \
             patch.object(cpg_generator, '_exec_command_async', return_value=""), \
             patch.object(cpg_generator, '_validate_cpg_async', return_value=True):

            mock_session_manager.update_status = AsyncMock()
            mock_session_manager.update_session = AsyncMock()

            result = await cpg_generator.generate_cpg(
                session_id="session-123",
                source_path="/workspace/src",
                language="java"
            )

            assert result == "/playground/cpgs/session-123.cpg"
            mock_session_manager.update_status.assert_any_call("session-123", SessionStatus.GENERATING.value)
            mock_session_manager.update_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_cpg_python(self, cpg_generator, mock_session_manager):
        """Test CPG generation for Python project"""
        mock_container = MagicMock()
        mock_container.exec_run = MagicMock(return_value=MagicMock(output=b"CPG generated successfully", exit_code=0))

        mock_docker_client = MagicMock()
        mock_docker_client.containers.get = MagicMock(return_value=mock_container)
        cpg_generator.docker_client = mock_docker_client
        cpg_generator.session_containers["session-456"] = "container-456"

        with patch.object(cpg_generator, '_find_joern_executable', return_value="pysrc2cpg"), \
             patch.object(cpg_generator, '_exec_command_async', return_value=""), \
             patch.object(cpg_generator, '_validate_cpg_async', return_value=True):

            mock_session_manager.update_status = AsyncMock()
            mock_session_manager.update_session = AsyncMock()

            result = await cpg_generator.generate_cpg(
                session_id="session-456",
                source_path="/workspace/src",
                language="python"
            )

            assert result == "/playground/cpgs/session-456.cpg"

    @pytest.mark.asyncio
    async def test_generate_cpg_timeout(self, cpg_generator, mock_session_manager):
        """Test CPG generation timeout"""
        mock_container = MagicMock()
        mock_docker_client = MagicMock()
        mock_docker_client.containers.get = MagicMock(return_value=mock_container)
        cpg_generator.docker_client = mock_docker_client
        cpg_generator.session_containers["session-123"] = "container-123"

        with patch.object(cpg_generator, '_find_joern_executable', return_value="javasrc2cpg"), \
             patch.object(cpg_generator, '_exec_command_async', side_effect=asyncio.TimeoutError()):

            mock_session_manager.update_status = AsyncMock()

            with pytest.raises(CPGGenerationError, match="CPG generation timed out"):
                await cpg_generator.generate_cpg(
                    session_id="session-123",
                    source_path="/workspace/src",
                    language="java"
                )

    @pytest.mark.asyncio
    async def test_generate_cpg_validation_failure(self, cpg_generator, mock_session_manager):
        """Test CPG generation with validation failure"""
        mock_container = MagicMock()
        mock_docker_client = MagicMock()
        mock_docker_client.containers.get = MagicMock(return_value=mock_container)
        cpg_generator.docker_client = mock_docker_client
        cpg_generator.session_containers["session-123"] = "container-123"

        with patch.object(cpg_generator, '_find_joern_executable', return_value="javasrc2cpg"), \
             patch.object(cpg_generator, '_exec_command_async', return_value=""), \
             patch.object(cpg_generator, '_validate_cpg_async', return_value=False):

            mock_session_manager.update_status = AsyncMock()

            with pytest.raises(CPGGenerationError, match="CPG file was not created"):
                await cpg_generator.generate_cpg(
                    session_id="session-123",
                    source_path="/workspace/src",
                    language="java"
                )

    def test_language_commands_mapping(self, cpg_generator):
        """Test language to command mapping"""
        expected_commands = {
            "java": "javasrc2cpg",
            "c": "c2cpg",
            "cpp": "c2cpg",
            "javascript": "jssrc2cpg",
            "python": "pysrc2cpg",
            "go": "gosrc2cpg",
            "kotlin": "kotlin2cpg",
            "csharp": "csharpsrc2cpg",
            "ghidra": "ghidra2cpg",
            "jimple": "jimple2cpg",
            "php": "php2cpg",
            "ruby": "rubysrc2cpg",
            "swift": "swiftsrc2cpg",
        }

        assert cpg_generator.LANGUAGE_COMMANDS == expected_commands

    @pytest.mark.asyncio
    async def test_find_joern_executable_found(self, cpg_generator):
        """Test finding Joern executable successfully"""
        mock_container = MagicMock()
        # Mock successful test for javasrc2cpg at the first path
        mock_container.exec_run = MagicMock(side_effect=[
            MagicMock(exit_code=0),  # First path succeeds
        ])

        result = await cpg_generator._find_joern_executable(mock_container, "javasrc2cpg")

        assert result == "/opt/joern/joern-cli/javasrc2cpg"

    @pytest.mark.asyncio
    async def test_find_joern_executable_not_found(self, cpg_generator):
        """Test finding Joern executable when not found"""
        mock_container = MagicMock()
        # Mock failed tests for all paths
        mock_container.exec_run = MagicMock(return_value=MagicMock(exit_code=1))

        result = await cpg_generator._find_joern_executable(mock_container, "javasrc2cpg")

        assert result == "javasrc2cpg"  # Falls back to base command

    @pytest.mark.asyncio
    async def test_validate_cpg_success(self, cpg_generator):
        """Test successful CPG validation"""
        mock_container = MagicMock()
        mock_exec_result = MagicMock()
        mock_exec_result.output = b"-rw-r--r-- 1 user user 1024 Jan 1 12:00 /playground/cpgs/session-123.cpg"
        mock_container.exec_run = MagicMock(return_value=mock_exec_result)

        result = await cpg_generator._validate_cpg_async(mock_container, "/playground/cpgs/session-123.cpg")

        assert result is True

    @pytest.mark.asyncio
    async def test_validate_cpg_failure(self, cpg_generator):
        """Test CPG validation failure"""
        mock_container = MagicMock()
        mock_exec_result = MagicMock()
        mock_exec_result.output = b"ls: cannot access '/playground/cpgs/session-123.cpg': No such file or directory"
        mock_container.exec_run = MagicMock(return_value=mock_exec_result)

        result = await cpg_generator._validate_cpg_async(mock_container, "/playground/cpgs/session-123.cpg")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_container_id(self, cpg_generator):
        """Test getting container ID for session"""
        cpg_generator.session_containers["session-123"] = "container-456"

        result = await cpg_generator.get_container_id("session-123")

        assert result == "container-456"

    @pytest.mark.asyncio
    async def test_get_container_id_not_found(self, cpg_generator):
        """Test getting container ID for non-existent session"""
        result = await cpg_generator.get_container_id("nonexistent")

        assert result is None

    def test_register_session_container(self, cpg_generator):
        """Test registering externally created container"""
        cpg_generator.register_session_container("session-123", "container-456")

        assert cpg_generator.session_containers["session-123"] == "container-456"

    @pytest.mark.asyncio
    async def test_close_session(self, cpg_generator):
        """Test closing session container"""
        mock_container = MagicMock()
        mock_docker_client = MagicMock()
        mock_docker_client.containers.get = MagicMock(return_value=mock_container)
        cpg_generator.docker_client = mock_docker_client
        cpg_generator.session_containers["session-123"] = "container-456"

        await cpg_generator.close_session("session-123")

        mock_docker_client.containers.get.assert_called_once_with("container-456")
        mock_container.stop.assert_called_once()
        mock_container.remove.assert_called_once()
        assert "session-123" not in cpg_generator.session_containers

    @pytest.mark.asyncio
    async def test_close_session_error(self, cpg_generator):
        """Test closing session with container error"""
        mock_docker_client = MagicMock()
        mock_docker_client.containers.get = MagicMock(side_effect=Exception("Container not found"))
        cpg_generator.docker_client = mock_docker_client
        cpg_generator.session_containers["session-123"] = "container-456"

        # Should not raise exception
        await cpg_generator.close_session("session-123")

        assert "session-123" not in cpg_generator.session_containers

    @pytest.mark.asyncio
    async def test_cleanup(self, cpg_generator):
        """Test cleanup of all containers"""
        cpg_generator.session_containers = {
            "session1": "container1",
            "session2": "container2"
        }

        with patch.object(cpg_generator, 'close_session', new_callable=AsyncMock) as mock_close:
            await cpg_generator.cleanup()

            assert mock_close.call_count == 2
            mock_close.assert_any_call("session1")
            mock_close.assert_any_call("session2")

    @pytest.mark.asyncio
    async def test_stream_logs(self, cpg_generator):
        """Test streaming logs during CPG generation"""
        mock_container = MagicMock()
        mock_exec_result = MagicMock()
        mock_exec_result.output = [b"Starting CPG generation...\n", b"Processing files...\n", b"CPG created successfully\n"]
        mock_container.exec_run = MagicMock(return_value=mock_exec_result)

        mock_docker_client = MagicMock()
        mock_docker_client.containers.get = MagicMock(return_value=mock_container)
        cpg_generator.docker_client = mock_docker_client
        cpg_generator.session_containers["session-123"] = "container-123"

        with patch.object(cpg_generator, '_find_joern_executable', return_value="javasrc2cpg"):
            logs = []
            async for log in cpg_generator.stream_logs(
                session_id="session-123",
                source_path="/workspace/src",
                language="java",
                output_path="/output.cpg"
            ):
                logs.append(log)

            assert len(logs) == 3
            assert "Starting CPG generation..." in logs[0]

    @pytest.mark.asyncio
    async def test_stream_logs_no_container(self, cpg_generator):
        """Test streaming logs when no container exists"""
        logs = []
        async for log in cpg_generator.stream_logs(
            session_id="session-123",
            source_path="/workspace/src",
            language="java",
            output_path="/output.cpg"
        ):
            logs.append(log)

        assert len(logs) == 1
        assert "ERROR: No container found" in logs[0]

    @pytest.mark.asyncio
    async def test_stream_logs_unsupported_language(self, cpg_generator):
        """Test streaming logs with unsupported language"""
        cpg_generator.session_containers["session-123"] = "container-123"
        # Mock docker client to avoid NoneType error
        cpg_generator.docker_client = MagicMock()

        logs = []
        async for log in cpg_generator.stream_logs(
            session_id="session-123",
            source_path="/workspace/src",
            language="unsupported",
            output_path="/output.cpg"
        ):
            logs.append(log)

        assert len(logs) == 1
        assert "ERROR: Unsupported language: unsupported" in logs[0]