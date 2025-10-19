"""
Tests for Redis client wrapper
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.exceptions import ValidationError
from src.models import RedisConfig, Session
from src.utils.redis_client import RedisClient


class TestRedisClient:
    """Test Redis client functionality"""

    @pytest.fixture
    def redis_config(self):
        """Redis configuration fixture"""
        return RedisConfig(
            host="localhost", port=6379, password=None, db=0, decode_responses=True
        )

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client"""
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock()
        return mock_redis

    @pytest.fixture
    def redis_client(self, redis_config, mock_redis):
        """Redis client fixture"""
        client = RedisClient(redis_config)
        client.client = mock_redis
        return client

    def test_init(self, redis_config):
        """Test Redis client initialization"""
        client = RedisClient(redis_config)

        assert client.config == redis_config
        assert client.client is None

    @pytest.mark.asyncio
    async def test_connect_success(self, redis_config, mock_redis):
        """Test successful Redis connection"""
        with patch(
            "src.utils.redis_client.redis.from_url", return_value=mock_redis
        ) as mock_from_url:
            client = RedisClient(redis_config)
            await client.connect()

            mock_from_url.assert_called_once_with(
                "redis://localhost:6379/0", password=None, decode_responses=True
            )
            mock_redis.ping.assert_called_once()
            assert client.client == mock_redis

    @pytest.mark.asyncio
    async def test_connect_failure(self, redis_config):
        """Test Redis connection failure"""
        with patch(
            "src.utils.redis_client.redis.from_url",
            side_effect=Exception("Connection failed"),
        ):
            client = RedisClient(redis_config)

            with pytest.raises(Exception, match="Connection failed"):
                await client.connect()

    @pytest.mark.asyncio
    async def test_close(self, redis_client, mock_redis):
        """Test closing Redis connection"""
        await redis_client.close()

        mock_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_session(self, redis_client, mock_redis):
        """Test saving session to Redis"""
        session = Session(
            id="test-session",
            source_type="github",
            source_path="https://github.com/user/repo",
            language="python",
        )

        mock_redis.set = AsyncMock()
        mock_redis.sadd = AsyncMock()

        await redis_client.save_session(session, ttl=3600)

        # Verify session data was saved
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "session:test-session"
        assert "test-session" in call_args[0][1]  # JSON data
        assert call_args[1]["ex"] == 3600

        # Verify session was added to active set
        mock_redis.sadd.assert_called_once_with("sessions:active", "test-session")

    @pytest.mark.asyncio
    async def test_get_session_found(self, redis_client, mock_redis):
        """Test retrieving existing session"""
        session_data = {
            "id": "test-session",
            "source_type": "local",
            "source_path": "/path/to/code",
            "language": "java",
            "status": "ready",
            "created_at": "2023-01-01T12:00:00",
            "last_accessed": "2023-01-01T12:30:00",
        }

        import json

        mock_redis.get = AsyncMock(return_value=json.dumps(session_data))

        session = await redis_client.get_session("test-session")

        assert session is not None
        assert session.id == "test-session"
        assert session.source_type == "local"
        assert session.language == "java"

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, redis_client, mock_redis):
        """Test retrieving non-existent session"""
        mock_redis.get = AsyncMock(return_value=None)

        session = await redis_client.get_session("nonexistent")

        assert session is None

    @pytest.mark.asyncio
    async def test_update_session(self, redis_client, mock_redis):
        """Test updating session fields"""
        # Mock existing session
        session_data = {
            "id": "test-session",
            "source_type": "github",
            "source_path": "https://github.com/user/repo",
            "language": "python",
            "status": "initializing",
            "created_at": "2023-01-01T12:00:00",
            "last_accessed": "2023-01-01T12:00:00",
        }

        import json

        mock_redis.get = AsyncMock(return_value=json.dumps(session_data))
        mock_redis.set = AsyncMock()

        await redis_client.update_session(
            "test-session", {"status": "ready", "language": "java"}, ttl=3600
        )

        # Verify updated session was saved
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        saved_data = json.loads(call_args[0][1])
        assert saved_data["status"] == "ready"
        assert saved_data["language"] == "java"
        assert call_args[1]["ex"] == 3600

    @pytest.mark.asyncio
    async def test_delete_session(self, redis_client, mock_redis):
        """Test deleting session from Redis"""
        mock_redis.delete = AsyncMock(return_value=1)
        mock_redis.srem = AsyncMock(return_value=1)

        await redis_client.delete_session("test-session")

        mock_redis.delete.assert_called_once_with("session:test-session")
        mock_redis.srem.assert_called_once_with("sessions:active", "test-session")

    @pytest.mark.asyncio
    async def test_list_sessions(self, redis_client, mock_redis):
        """Test listing all active sessions"""
        mock_redis.smembers = AsyncMock(
            return_value={"session1", "session2", "session3"}
        )

        sessions = await redis_client.list_sessions()

        assert set(sessions) == {"session1", "session2", "session3"}
        mock_redis.smembers.assert_called_once_with("sessions:active")

    @pytest.mark.asyncio
    async def test_touch_session(self, redis_client, mock_redis):
        """Test refreshing session TTL"""
        mock_redis.expire = AsyncMock(return_value=True)

        await redis_client.touch_session("test-session", ttl=3600)

        mock_redis.expire.assert_called_once_with("session:test-session", 3600)

    @pytest.mark.asyncio
    async def test_set_container_mapping(self, redis_client, mock_redis):
        """Test setting container mapping"""
        mock_redis.set = AsyncMock()

        await redis_client.set_container_mapping(
            "container-123", "session-456", ttl=3600
        )

        mock_redis.set.assert_called_once_with(
            "container:container-123", "session-456", ex=3600
        )

    @pytest.mark.asyncio
    async def test_get_session_by_container(self, redis_client, mock_redis):
        """Test getting session by container ID"""
        mock_redis.get = AsyncMock(return_value="session-456")

        session_id = await redis_client.get_session_by_container("container-123")

        assert session_id == "session-456"
        mock_redis.get.assert_called_once_with("container:container-123")

    @pytest.mark.asyncio
    async def test_delete_container_mapping(self, redis_client, mock_redis):
        """Test deleting container mapping"""
        mock_redis.delete = AsyncMock(return_value=1)

        await redis_client.delete_container_mapping("container-123")

        mock_redis.delete.assert_called_once_with("container:container-123")

    @pytest.mark.asyncio
    async def test_cache_query_result(self, redis_client, mock_redis):
        """Test caching query result"""
        result = {"data": [{"name": "test"}], "row_count": 1}

        import json

        mock_redis.set = AsyncMock()

        await redis_client.cache_query_result(
            "session-123", "query-hash", result, ttl=300
        )

        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "query:session-123:query-hash"
        assert json.loads(call_args[0][1]) == result
        assert call_args[1]["ex"] == 300

    @pytest.mark.asyncio
    async def test_get_cached_query(self, redis_client, mock_redis):
        """Test retrieving cached query result"""
        cached_result = {"data": [{"name": "test"}], "row_count": 1}

        import json

        mock_redis.get = AsyncMock(return_value=json.dumps(cached_result))

        result = await redis_client.get_cached_query("session-123", "query-hash")

        assert result == cached_result
        mock_redis.get.assert_called_once_with("query:session-123:query-hash")

    @pytest.mark.asyncio
    async def test_get_cached_query_not_found(self, redis_client, mock_redis):
        """Test retrieving non-existent cached query"""
        mock_redis.get = AsyncMock(return_value=None)

        result = await redis_client.get_cached_query("session-123", "query-hash")

        assert result is None
