"""Configuration management for the Joern MCP Server."""

import os
import yaml
from typing import Optional
from pathlib import Path

from .models import (
    Config,
    ServerConfig,
    RedisConfig,
    SessionConfig,
    CPGConfig,
    QueryConfig,
    StorageConfig,
    JoernConfig
)


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from file or environment variables"""
    if config_path and os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
            # Process environment variable substitutions
            config_data = _substitute_env_vars(config_data)
        return _dict_to_config(config_data)
    else:
        # Load from environment variables
        return Config(
            server=ServerConfig(
                host=os.getenv("MCP_HOST", "0.0.0.0"),
                port=int(os.getenv("MCP_PORT", "4242")),
                log_level=os.getenv("MCP_LOG_LEVEL", "INFO")
            ),
            redis=RedisConfig(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                password=os.getenv("REDIS_PASSWORD"),
                db=int(os.getenv("REDIS_DB", "0"))
            ),
            joern=JoernConfig(
                binary_path=os.getenv("JOERN_BINARY_PATH", "joern"),
                memory_limit=os.getenv("JOERN_MEMORY_LIMIT", "4g")
            ),
            sessions=SessionConfig(
                ttl=int(os.getenv("SESSION_TTL", "3600")),
                idle_timeout=int(os.getenv("SESSION_IDLE_TIMEOUT", "1800")),
                max_concurrent=int(os.getenv("MAX_CONCURRENT_SESSIONS", "10"))
            ),
            cpg=CPGConfig(
                generation_timeout=int(os.getenv("CPG_GENERATION_TIMEOUT", "600")),
                max_repo_size_mb=int(os.getenv("MAX_REPO_SIZE_MB", "500"))
            ),
            query=QueryConfig(
                timeout=int(os.getenv("QUERY_TIMEOUT", "30")),
                cache_enabled=os.getenv("QUERY_CACHE_ENABLED", "true").lower() == "true",
                cache_ttl=int(os.getenv("QUERY_CACHE_TTL", "300"))
            ),
            storage=StorageConfig(
                workspace_root=os.getenv("WORKSPACE_ROOT", "/tmp/joern-mcp"),
                cleanup_on_shutdown=os.getenv("CLEANUP_ON_SHUTDOWN", "true").lower() == "true"
            )
        )


def _substitute_env_vars(data):
    """Recursively substitute environment variables in config"""
    if isinstance(data, dict):
        return {k: _substitute_env_vars(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_substitute_env_vars(item) for item in data]
    elif isinstance(data, str) and data.startswith("${") and data.endswith("}"):
        env_var = data[2:-1]
        default = None
        if ":" in env_var:
            env_var, default = env_var.split(":", 1)
        return os.getenv(env_var, default)
    return data


def _dict_to_config(data: dict) -> Config:
    """Convert dictionary to Config object with proper type conversions"""
    # Helper function to convert values based on dataclass field types
    def convert_config_section(config_class, values):
        if not values:
            return config_class()
        converted = {}
        for field_name, field_type in config_class.__annotations__.items():
            if field_name in values:
                value = values[field_name]
                # Handle type conversions
                if field_type == int or (hasattr(field_type, '__origin__') and field_type.__origin__ == int):
                    converted[field_name] = int(value) if value is not None else None
                elif field_type == float or (hasattr(field_type, '__origin__') and field_type.__origin__ == float):
                    converted[field_name] = float(value) if value is not None else None
                elif field_type == bool or (hasattr(field_type, '__origin__') and field_type.__origin__ == bool):
                    if isinstance(value, str):
                        converted[field_name] = value.lower() in ('true', '1', 'yes')
                    else:
                        converted[field_name] = bool(value)
                else:
                    converted[field_name] = value
        return config_class(**converted)
    
    return Config(
        server=convert_config_section(ServerConfig, data.get("server", {})),
        redis=convert_config_section(RedisConfig, data.get("redis", {})),
        joern=convert_config_section(JoernConfig, data.get("joern", {})),
        sessions=convert_config_section(SessionConfig, data.get("sessions", {})),
        cpg=convert_config_section(CPGConfig, data.get("cpg", {})),
        query=convert_config_section(QueryConfig, data.get("query", {})),
        storage=convert_config_section(StorageConfig, data.get("storage", {}))
    )