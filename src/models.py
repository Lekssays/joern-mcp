"""
Data models for Joern MCP Server
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum


class SessionStatus(str, Enum):
    """Session status enumeration"""
    INITIALIZING = "initializing"
    GENERATING = "generating"
    READY = "ready"
    ERROR = "error"


class SourceType(str, Enum):
    """Source type enumeration"""
    LOCAL = "local"
    GITHUB = "github"


@dataclass
class Session:
    """CPG session data model"""
    id: str
    container_id: Optional[str] = None
    source_type: str = ""
    source_path: str = ""
    language: str = ""
    status: str = SessionStatus.INITIALIZING.value
    cpg_path: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_accessed: datetime = field(default_factory=datetime.utcnow)
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert session to dictionary"""
        return {
            "id": self.id,
            "container_id": self.container_id,
            "source_type": self.source_type,
            "source_path": self.source_path,
            "language": self.language,
            "status": self.status,
            "cpg_path": self.cpg_path,
            "created_at": self.created_at.isoformat(),
            "last_accessed": self.last_accessed.isoformat(),
            "error_message": self.error_message,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Session':
        """Create session from dictionary"""
        return cls(
            id=data["id"],
            container_id=data.get("container_id"),
            source_type=data.get("source_type", ""),
            source_path=data.get("source_path", ""),
            language=data.get("language", ""),
            status=data.get("status", SessionStatus.INITIALIZING.value),
            cpg_path=data.get("cpg_path"),
            created_at=datetime.fromisoformat(data["created_at"]),
            last_accessed=datetime.fromisoformat(data["last_accessed"]),
            error_message=data.get("error_message"),
            metadata=data.get("metadata", {})
        )


@dataclass
class QueryResult:
    """Query execution result"""
    success: bool
    data: Optional[List[Dict[str, Any]]] = None
    error: Optional[str] = None
    execution_time: float = 0.0
    row_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary"""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "execution_time": self.execution_time,
            "row_count": self.row_count
        }


@dataclass
class JoernConfig:
    """Joern configuration"""
    binary_path: str = "joern"
    memory_limit: str = "4g"


@dataclass
class ServerConfig:
    """Server configuration"""
    host: str = "0.0.0.0"
    port: int = 4242
    log_level: str = "INFO"


@dataclass
class RedisConfig:
    """Redis configuration"""
    host: str = "localhost"
    port: int = 6379
    password: Optional[str] = None
    db: int = 0
    decode_responses: bool = True


@dataclass
class SessionConfig:
    """Session management configuration"""
    ttl: int = 3600  # 1 hour
    idle_timeout: int = 1800  # 30 minutes
    max_concurrent: int = 100


@dataclass
class CPGConfig:
    """CPG generation configuration"""
    generation_timeout: int = 600  # 10 minutes
    max_repo_size_mb: int = 500
    supported_languages: List[str] = field(default_factory=lambda: [
        "java", "c", "cpp", "javascript", "python", "go", "kotlin"
    ])


@dataclass
class QueryConfig:
    """Query execution configuration"""
    timeout: int = 30
    cache_enabled: bool = True
    cache_ttl: int = 300  # 5 minutes


@dataclass
class StorageConfig:
    """Storage configuration"""
    workspace_root: str = "/tmp/joern-mcp"
    cleanup_on_shutdown: bool = True


@dataclass
class Config:
    """Main configuration"""
    server: ServerConfig = field(default_factory=ServerConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    joern: JoernConfig = field(default_factory=JoernConfig)
    sessions: SessionConfig = field(default_factory=SessionConfig)
    cpg: CPGConfig = field(default_factory=CPGConfig)
    query: QueryConfig = field(default_factory=QueryConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)