"""
Tests for data models
"""

from datetime import datetime

import pytest

from src.models import (
    Config,
    CPGConfig,
    JoernConfig,
    QueryConfig,
    QueryResult,
    RedisConfig,
    ServerConfig,
    Session,
    SessionConfig,
    SessionStatus,
    SourceType,
    StorageConfig,
)


class TestSession:
    """Test Session model"""

    def test_session_creation(self):
        """Test basic session creation"""
        session = Session(
            id="test-id",
            source_type="github",
            source_path="https://github.com/user/repo",
            language="python",
        )

        assert session.id == "test-id"
        assert session.source_type == "github"
        assert session.source_path == "https://github.com/user/repo"
        assert session.language == "python"
        assert session.status == SessionStatus.INITIALIZING.value
        assert session.container_id is None
        assert session.cpg_path is None
        assert isinstance(session.created_at, datetime)
        assert isinstance(session.last_accessed, datetime)
        assert session.error_message is None
        assert session.metadata == {}

    def test_session_to_dict(self):
        """Test session serialization"""
        session = Session(
            id="test-id",
            source_type="local",
            source_path="/path/to/code",
            language="java",
            status="ready",
            container_id="container-123",
            cpg_path="/path/to/cpg.bin",
            error_message="Test error",
        )

        data = session.to_dict()

        assert data["id"] == "test-id"
        assert data["source_type"] == "local"
        assert data["source_path"] == "/path/to/code"
        assert data["language"] == "java"
        assert data["status"] == "ready"
        assert data["container_id"] == "container-123"
        assert data["cpg_path"] == "/path/to/cpg.bin"
        assert data["error_message"] == "Test error"
        assert "created_at" in data
        assert "last_accessed" in data

    def test_session_from_dict(self):
        """Test session deserialization"""
        data = {
            "id": "test-id",
            "source_type": "github",
            "source_path": "https://github.com/user/repo",
            "language": "python",
            "status": "ready",
            "container_id": "container-123",
            "cpg_path": "/path/to/cpg.bin",
            "created_at": "2023-01-01T12:00:00",
            "last_accessed": "2023-01-01T12:30:00",
            "error_message": None,
            "metadata": {"key": "value"},
        }

        session = Session.from_dict(data)

        assert session.id == "test-id"
        assert session.source_type == "github"
        assert session.source_path == "https://github.com/user/repo"
        assert session.language == "python"
        assert session.status == "ready"
        assert session.container_id == "container-123"
        assert session.cpg_path == "/path/to/cpg.bin"
        assert session.error_message is None
        assert session.metadata == {"key": "value"}
        assert isinstance(session.created_at, datetime)
        assert isinstance(session.last_accessed, datetime)


class TestQueryResult:
    """Test QueryResult model"""

    def test_query_result_creation(self):
        """Test basic query result creation"""
        result = QueryResult(success=True, data=[{"name": "test"}], execution_time=1.5)

        assert result.success is True
        assert result.data == [{"name": "test"}]
        assert result.error is None
        assert result.execution_time == 1.5
        assert result.row_count == 0

    def test_query_result_with_error(self):
        """Test query result with error"""
        result = QueryResult(success=False, error="Query failed", execution_time=0.5)

        assert result.success is False
        assert result.data is None
        assert result.error == "Query failed"
        assert result.execution_time == 0.5

    def test_query_result_to_dict(self):
        """Test query result serialization"""
        result = QueryResult(
            success=True, data=[{"name": "test"}], execution_time=1.5, row_count=1
        )

        data = result.to_dict()

        assert data["success"] is True
        assert data["data"] == [{"name": "test"}]
        assert data["error"] is None
        assert data["execution_time"] == 1.5
        assert data["row_count"] == 1


class TestEnums:
    """Test enumeration classes"""

    def test_session_status_values(self):
        """Test SessionStatus enum values"""
        assert SessionStatus.INITIALIZING.value == "initializing"
        assert SessionStatus.GENERATING.value == "generating"
        assert SessionStatus.READY.value == "ready"
        assert SessionStatus.ERROR.value == "error"

    def test_source_type_values(self):
        """Test SourceType enum values"""
        assert SourceType.LOCAL.value == "local"
        assert SourceType.GITHUB.value == "github"


class TestConfigModels:
    """Test configuration models"""

    def test_server_config(self):
        """Test ServerConfig creation"""
        config = ServerConfig(host="127.0.0.1", port=8080, log_level="DEBUG")

        assert config.host == "127.0.0.1"
        assert config.port == 8080
        assert config.log_level == "DEBUG"

    def test_redis_config(self):
        """Test RedisConfig creation"""
        config = RedisConfig(host="localhost", port=6379, password="secret", db=1)

        assert config.host == "localhost"
        assert config.port == 6379
        assert config.password == "secret"
        assert config.db == 1
        assert config.decode_responses is True

    def test_session_config(self):
        """Test SessionConfig creation"""
        config = SessionConfig(ttl=7200, idle_timeout=3600, max_concurrent=50)

        assert config.ttl == 7200
        assert config.idle_timeout == 3600
        assert config.max_concurrent == 50

    def test_cpg_config(self):
        """Test CPGConfig creation"""
        config = CPGConfig(generation_timeout=1200, max_repo_size_mb=1000)

        assert config.generation_timeout == 1200
        assert config.max_repo_size_mb == 1000
        assert "java" in config.supported_languages
        assert "python" in config.supported_languages

    def test_query_config(self):
        """Test QueryConfig creation"""
        config = QueryConfig(timeout=60, cache_enabled=False, cache_ttl=600)

        assert config.timeout == 60
        assert config.cache_enabled is False
        assert config.cache_ttl == 600

    def test_storage_config(self):
        """Test StorageConfig creation"""
        config = StorageConfig(workspace_root="/tmp/test", cleanup_on_shutdown=False)

        assert config.workspace_root == "/tmp/test"
        assert config.cleanup_on_shutdown is False

    def test_joern_config(self):
        """Test JoernConfig creation"""
        config = JoernConfig(binary_path="/usr/local/bin/joern", memory_limit="8g")

        assert config.binary_path == "/usr/local/bin/joern"
        assert config.memory_limit == "8g"

    def test_config_composition(self):
        """Test Config composition"""
        config = Config(
            server=ServerConfig(host="0.0.0.0", port=4242),
            redis=RedisConfig(host="redis", port=6379),
            joern=JoernConfig(binary_path="joern"),
            sessions=SessionConfig(ttl=3600),
            cpg=CPGConfig(generation_timeout=600),
            query=QueryConfig(timeout=30),
            storage=StorageConfig(workspace_root="/tmp/joern"),
        )

        assert config.server.host == "0.0.0.0"
        assert config.redis.host == "redis"
        assert config.joern.binary_path == "joern"
        assert config.sessions.ttl == 3600
        assert config.cpg.generation_timeout == 600
        assert config.query.timeout == 30
        assert config.storage.workspace_root == "/tmp/joern"
