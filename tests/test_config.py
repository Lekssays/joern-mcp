"""Tests for configuration management."""

import pytest
import tempfile
import os
import sys
from pathlib import Path

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import load_config
from src.models import ServerConfig


def test_load_config_from_environment():
    """Test loading configuration from environment variables"""
    # Set some environment variables
    os.environ["JOERN_DOCKER_IMAGE"] = "test:latest"
    os.environ["JOERN_MEMORY_LIMIT"] = "8g"
    os.environ["JOERN_LOG_LEVEL"] = "DEBUG"
    
    try:
        config = load_config()
        
        assert config.docker.image == "test:latest"
        assert config.docker.memory_limit == "8g"
        assert config.log_level == "DEBUG"
        
    finally:
        # Clean up environment variables
        for var in ["JOERN_DOCKER_IMAGE", "JOERN_MEMORY_LIMIT", "JOERN_LOG_LEVEL"]:
            os.environ.pop(var, None)


def test_load_config_defaults():
    """Test loading configuration with default values"""
    # Clear any existing environment variables
    env_vars = [
        "JOERN_DOCKER_IMAGE", "JOERN_CPU_LIMIT", "JOERN_MEMORY_LIMIT",
        "JOERN_TIMEOUT", "JOERN_CACHE_ENABLED", "JOERN_CACHE_SIZE_GB",
        "JOERN_CACHE_DIR", "GITHUB_TOKEN", "JOERN_LOG_LEVEL"
    ]
    
    original_values = {}
    for var in env_vars:
        original_values[var] = os.environ.pop(var, None)
    
    try:
        config = load_config()
        
        # Check defaults
        assert config.docker.image == "joern:latest"
        assert config.docker.memory_limit == "4g"
        assert config.docker.timeout == 300
        assert config.cache.enabled is True
        assert config.log_level == "INFO"
        
    finally:
        # Restore original environment
        for var, value in original_values.items():
            if value is not None:
                os.environ[var] = value


def test_load_config_from_yaml_file():
    """Test loading configuration from YAML file"""
    yaml_content = """
docker:
  image: "custom:latest"
  memory_limit: "6g"
  timeout: 600

cache:
  enabled: false
  max_size_gb: 5

log_level: "ERROR"
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as f:
        f.write(yaml_content)
        f.flush()
        
        try:
            config = load_config(f.name)
            
            assert config.docker.image == "custom:latest"
            assert config.docker.memory_limit == "6g"
            assert config.docker.timeout == 600
            assert config.cache.enabled is False
            assert config.cache.max_size_gb == 5
            assert config.log_level == "ERROR"
            
        finally:
            os.unlink(f.name)


def test_load_config_nonexistent_file():
    """Test loading configuration with non-existent file"""
    config = load_config("/nonexistent/config.yml")
    
    # Should fall back to environment/defaults
    assert isinstance(config, ServerConfig)
    assert config.docker.image == "joern:latest"  # default value