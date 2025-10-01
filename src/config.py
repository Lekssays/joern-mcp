"""Configuration management for the Joern MCP Server."""

import os
from typing import Optional

from .models import ServerConfig, DockerConfig, CacheConfig


def load_config(config_path: Optional[str] = None) -> ServerConfig:
    """Load configuration from file or environment variables"""
    if config_path and os.path.exists(config_path):
        import yaml
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
        return ServerConfig(**config_data)
    else:
        # Load from environment variables
        return ServerConfig(
            docker=DockerConfig(
                image=os.getenv("JOERN_DOCKER_IMAGE", "joern:latest"),
                cpu_limit=os.getenv("JOERN_CPU_LIMIT", "2"),
                memory_limit=os.getenv("JOERN_MEMORY_LIMIT", "4g"),
                timeout=int(os.getenv("JOERN_TIMEOUT", "300"))
            ),
            cache=CacheConfig(
                enabled=os.getenv("JOERN_CACHE_ENABLED", "true").lower() == "true",
                max_size_gb=int(os.getenv("JOERN_CACHE_SIZE_GB", "10")),
                directory=os.getenv("JOERN_CACHE_DIR", "/tmp/joern_cache")
            ),
            github_token=os.getenv("GITHUB_TOKEN"),
            log_level=os.getenv("JOERN_LOG_LEVEL", "INFO")
        )