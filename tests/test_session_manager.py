"""
Tests for session manager
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, ANY
from src.services.session_manager import SessionManager
from src.models import Session, SessionStatus, SessionConfig
from src.utils.redis_client import RedisClient
from src.exceptions import SessionNotFoundError, ResourceLimitError


class TestSessionManager:
    """Test session manager functionality"""

    @pytest.fixture
    def session_config(self):
        """Session configuration fixture"""
        return SessionConfig(
            ttl=3600,
            idle_timeout=1800,
            max_concurrent=10
        )

    @pytest.fixture
    def mock_redis_client(self):
        """Mock Redis client fixture"""
        mock_client = AsyncMock(spec=RedisClient)
        return mock_client

    @pytest.fixture
    def session_manager(self, mock_redis_client, session_config):
        """Session manager fixture"""
        manager = SessionManager(mock_redis_client, session_config)
        return manager

    @pytest.mark.asyncio
    async def test_create_session_success(self, session_manager, mock_redis_client):
        """Test successful session creation"""
        mock_redis_client.list_sessions = AsyncMock(return_value=[])
        mock_redis_client.get_session = AsyncMock(return_value=None)  # Mock to return None for new session
        mock_redis_client.save_session = AsyncMock()

        session = await session_manager.create_session(
            source_type="github",
            source_path="https://github.com/user/repo",
            language="python",
            options={"branch": "main"}
        )

        assert isinstance(session, Session)
        assert session.source_type == "github"
        assert session.source_path == "https://github.com/user/repo"
        assert session.language == "python"
        assert session.status == SessionStatus.INITIALIZING.value
        assert session.metadata == {"branch": "main"}

        # Verify Redis calls
        mock_redis_client.list_sessions.assert_called_once()
        mock_redis_client.get_session.assert_called_once()  # Should check if session exists
        mock_redis_client.save_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_session_concurrent_limit_reached(self, session_manager, mock_redis_client):
        """Test session creation when concurrent limit is reached"""
        # Mock existing sessions at limit
        existing_sessions = [f"session-{i}" for i in range(10)]
        mock_redis_client.list_sessions = AsyncMock(return_value=existing_sessions)
        mock_redis_client.get_session = AsyncMock(side_effect=lambda sid: AsyncMock() if sid in existing_sessions else None)
        mock_redis_client.save_session = AsyncMock()

        # Mock cleanup of oldest sessions
        with patch.object(session_manager, '_cleanup_oldest_sessions', new_callable=AsyncMock) as mock_cleanup:
            session = await session_manager.create_session(
                source_type="local",
                source_path="/path/to/code",
                language="java",
                options={}
            )

            # Verify cleanup was called
            mock_cleanup.assert_called_once_with(10)

    @pytest.mark.asyncio
    async def test_create_session_exception_handling(self, session_manager, mock_redis_client):
        """Test session creation with exception handling"""
        mock_redis_client.list_sessions = AsyncMock(side_effect=Exception("Redis error"))

        with pytest.raises(Exception, match="Redis error"):
            await session_manager.create_session(
                source_type="github",
                source_path="https://github.com/user/repo",
                language="python",
                options={}
            )

    @pytest.mark.asyncio
    async def test_get_session_found(self, session_manager, mock_redis_client):
        """Test retrieving existing session"""
        mock_session = Session(
            id="test-session",
            source_type="github",
            source_path="https://github.com/user/repo",
            language="python"
        )
        mock_redis_client.get_session = AsyncMock(return_value=mock_session)

        result = await session_manager.get_session("test-session")

        assert result == mock_session
        mock_redis_client.get_session.assert_called_once_with("test-session")

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, session_manager, mock_redis_client):
        """Test retrieving non-existent session"""
        mock_redis_client.get_session = AsyncMock(return_value=None)

        result = await session_manager.get_session("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_update_session(self, session_manager, mock_redis_client):
        """Test updating session fields"""
        mock_redis_client.update_session = AsyncMock()

        await session_manager.update_session("test-session", status="ready", language="java")

        mock_redis_client.update_session.assert_called_once_with(
            "test-session",
            {"status": "ready", "language": "java", "last_accessed": ANY},
            3600
        )

    @pytest.mark.asyncio
    async def test_update_status(self, session_manager, mock_redis_client):
        """Test updating session status"""
        mock_redis_client.update_session = AsyncMock()

        await session_manager.update_status("test-session", "ready", "Operation completed")

        expected_updates = {
            "status": "ready",
            "error_message": "Operation completed",
            "last_accessed": ANY
        }

        mock_redis_client.update_session.assert_called_once_with(
            "test-session",
            expected_updates,
            3600
        )

    @pytest.mark.asyncio
    async def test_list_sessions_no_filters(self, session_manager, mock_redis_client):
        """Test listing all sessions without filters"""
        mock_sessions = [
            Session(id="session1", source_type="github", language="python"),
            Session(id="session2", source_type="local", language="java")
        ]

        mock_redis_client.list_sessions = AsyncMock(return_value=["session1", "session2"])
        mock_redis_client.get_session = AsyncMock(side_effect=mock_sessions)

        result = await session_manager.list_sessions()

        assert len(result) == 2
        assert result[0].id == "session1"
        assert result[1].id == "session2"

    @pytest.mark.asyncio
    async def test_list_sessions_with_filters(self, session_manager, mock_redis_client):
        """Test listing sessions with filters"""
        mock_sessions = [
            Session(id="session1", source_type="github", language="python", status="ready"),
            Session(id="session2", source_type="local", language="java", status="generating")
        ]

        mock_redis_client.list_sessions = AsyncMock(return_value=["session1", "session2"])
        mock_redis_client.get_session = AsyncMock(side_effect=mock_sessions)

        # Filter by status
        result = await session_manager.list_sessions({"status": "ready"})

        assert len(result) == 1
        assert result[0].id == "session1"

    @pytest.mark.asyncio
    async def test_touch_session(self, session_manager, mock_redis_client):
        """Test refreshing session TTL"""
        mock_redis_client.touch_session = AsyncMock()
        mock_redis_client.update_session = AsyncMock()

        await session_manager.touch_session("test-session")

        mock_redis_client.touch_session.assert_called_once_with("test-session", 3600)
        mock_redis_client.update_session.assert_called_once_with(
            "test-session",
            {"last_accessed": ANY},
            3600
        )

    @pytest.mark.asyncio
    async def test_cleanup_session_success(self, session_manager, mock_redis_client):
        """Test successful session cleanup"""
        mock_session = Session(
            id="test-session",
            container_id="container-123",
            source_type="github",
            source_path="https://github.com/user/repo",
            language="python"
        )

        mock_redis_client.get_session = AsyncMock(return_value=mock_session)
        mock_redis_client.delete_container_mapping = AsyncMock()
        mock_redis_client.delete_session = AsyncMock()

        await session_manager.cleanup_session("test-session")

        mock_redis_client.delete_container_mapping.assert_called_once_with("container-123")
        mock_redis_client.delete_session.assert_called_once_with("test-session")

    @pytest.mark.asyncio
    async def test_cleanup_session_not_found(self, session_manager, mock_redis_client):
        """Test cleanup of non-existent session"""
        mock_redis_client.get_session = AsyncMock(return_value=None)

        with pytest.raises(SessionNotFoundError):
            await session_manager.cleanup_session("nonexistent")

    @pytest.mark.asyncio
    async def test_cleanup_idle_sessions(self, session_manager, mock_redis_client):
        """Test cleanup of idle sessions"""
        # Create sessions with different last_accessed times
        now = datetime.utcnow()
        active_session = Session(
            id="active",
            last_accessed=now - timedelta(minutes=25)  # Clearly not idle (25 min < 30 min)
        )
        idle_session = Session(
            id="idle",
            last_accessed=now - timedelta(hours=1)  # Idle
        )

        mock_redis_client.list_sessions = AsyncMock(return_value=["active", "idle"])
        mock_redis_client.get_session = AsyncMock(side_effect=[active_session, idle_session])

        with patch.object(session_manager, 'cleanup_session', new_callable=AsyncMock) as mock_cleanup:
            await session_manager.cleanup_idle_sessions()

            # Only idle session should be cleaned up
            mock_cleanup.assert_called_once_with("idle")

    @pytest.mark.asyncio
    async def test_cleanup_oldest_sessions(self, session_manager, mock_redis_client):
        """Test cleanup of oldest sessions"""
        # Create sessions with different creation times
        base_time = datetime.utcnow()
        sessions = [
            Session(id="oldest", created_at=base_time - timedelta(hours=3)),
            Session(id="middle", created_at=base_time - timedelta(hours=2)),
            Session(id="newest", created_at=base_time - timedelta(hours=1))
        ]

        mock_redis_client.list_sessions = AsyncMock(return_value=["oldest", "middle", "newest"])
        mock_redis_client.get_session = AsyncMock(side_effect=sessions)

        # Mock docker cleanup
        session_manager.docker_cleanup_callback = AsyncMock()

        with patch.object(session_manager, 'cleanup_session', new_callable=AsyncMock) as mock_cleanup:
            await session_manager._cleanup_oldest_sessions(2)

            # Two oldest sessions should be cleaned up
            assert mock_cleanup.call_count == 2
            mock_cleanup.assert_any_call("oldest")
            mock_cleanup.assert_any_call("middle")

    def test_set_docker_cleanup_callback(self, session_manager):
        """Test setting Docker cleanup callback"""
        callback = AsyncMock()
        session_manager.set_docker_cleanup_callback(callback)

        assert session_manager.docker_cleanup_callback == callback