"""Tests for data models."""

import pytest
import time
import sys
from pathlib import Path

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import (
    ServerConfig, DockerConfig, CacheConfig, 
    ProjectInfo, QueryResult,
    JoernMCPError, ProjectLoadError
)


def test_docker_config_defaults():
    """Test DockerConfig default values"""
    config = DockerConfig()
    assert config.image == "joern:latest"
    assert config.memory_limit == "4g"
    assert config.timeout == 300
    assert config.network_mode == "none"


def test_cache_config_defaults():
    """Test CacheConfig default values"""
    config = CacheConfig()
    assert config.enabled is True
    assert config.max_size_gb == 10
    assert config.ttl_hours == 24
    assert config.directory == "/tmp/joern_cache"


def test_server_config_defaults():
    """Test ServerConfig default values"""
    config = ServerConfig()
    assert config.max_concurrent_analyses == 3
    assert "c" in config.supported_languages
    assert "python" in config.supported_languages
    assert config.log_level == "INFO"


def test_project_info_creation():
    """Test ProjectInfo model creation"""
    project = ProjectInfo(
        id="test123",
        source_type="github",
        source_path="/tmp/test",
        languages=["c", "cpp"],
        size_loc=100
    )
    
    assert project.id == "test123"
    assert project.source_type == "github"
    assert project.languages == ["c", "cpp"]
    assert project.size_loc == 100
    assert project.cpg_generated is False
    assert project.cpg_path is None
    assert project.created_at > 0
    assert project.last_accessed > 0


def test_project_info_timestamps():
    """Test that timestamps are properly set"""
    before = time.time()
    project = ProjectInfo(
        id="test123",
        source_type="local",
        source_path="/tmp/test"
    )
    after = time.time()
    
    assert before <= project.created_at <= after
    assert before <= project.last_accessed <= after


def test_query_result_success():
    """Test successful QueryResult creation"""
    result = QueryResult(
        query="cpg.method.l",
        success=True,
        results=[{"name": "main", "id": 123}],
        execution_time=1.5
    )
    
    assert result.success is True
    assert result.error is None
    assert len(result.results) == 1
    assert result.execution_time == 1.5
    assert result.timestamp > 0


def test_query_result_error():
    """Test error QueryResult creation"""
    result = QueryResult(
        query="invalid.query",
        success=False,
        error="Invalid query syntax",
        execution_time=0.1
    )
    
    assert result.success is False
    assert result.error == "Invalid query syntax"
    assert result.results == []


def test_joern_mcp_error():
    """Test base exception class"""
    error = JoernMCPError("Test error")
    assert str(error) == "Test error"


def test_project_load_error():
    """Test ProjectLoadError inheritance"""
    error = ProjectLoadError("Failed to load project")
    assert isinstance(error, JoernMCPError)
    assert str(error) == "Failed to load project"