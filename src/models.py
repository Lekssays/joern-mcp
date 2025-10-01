"""Data models for the Joern MCP Server."""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# Configuration Models
class DockerConfig(BaseModel):
    """Docker configuration settings"""
    image: str = "joern:latest"
    cpu_limit: Optional[str] = "2"
    memory_limit: str = "4g"
    timeout: int = 300  # seconds
    network_mode: str = "none"  # isolated by default
    
class CacheConfig(BaseModel):
    """Cache configuration settings"""
    enabled: bool = True
    max_size_gb: int = 10
    ttl_hours: int = 24
    directory: str = "/tmp/joern_cache"

class ServerConfig(BaseModel):
    """Main server configuration"""
    docker: DockerConfig = DockerConfig()
    cache: CacheConfig = CacheConfig()
    max_concurrent_analyses: int = 3
    supported_languages: List[str] = [
        "c", "cpp", "java", "javascript", "typescript", 
        "python", "go", "kotlin", "scala", "csharp"
    ]
    github_token: Optional[str] = None
    log_level: str = "INFO"

# Data Models
class ProjectInfo(BaseModel):
    """Information about a loaded project"""
    id: str
    source_type: str  # "github" or "local"
    source_path: str
    languages: List[str] = []
    size_loc: Optional[int] = None
    cpg_generated: bool = False
    cpg_path: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    last_accessed: float = Field(default_factory=time.time)

class QueryResult(BaseModel):
    """Result of a Joern query execution"""
    query: str
    success: bool
    results: List[Dict[str, Any]] = []
    error: Optional[str] = None
    execution_time: float = 0.0
    timestamp: float = Field(default_factory=time.time)

# Exception Classes
class JoernMCPError(Exception):
    """Base exception for Joern MCP Server"""
    pass

class ProjectLoadError(JoernMCPError):
    """Error loading project"""
    pass

class CPGGenerationError(JoernMCPError):
    """Error generating CPG"""
    pass

class QueryExecutionError(JoernMCPError):
    """Error executing query"""
    pass