# joern-mcp Architecture

## Overview

**joern-mcp** is a Model Context Protocol (MCP) server that provides AI assistants with static code analysis capabilities using Joern's Code Property Graph (CPG) technology. It implements a microservices architecture with Docker isolation, Redis caching, and asynchronous query execution.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Client (Claude, etc)                     │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│         FastMCP Server (HTTP Transport)                      │
│         - Port 4242                                          │
│         - Async request handling                             │
│         - Streamable HTTP responses                          │
└─────────┬──────────────────────────────────────────────────┘
          │
          ├─────────────────────────────────────────────┐
          │                                             │
          ▼                                             ▼
┌──────────────────────────────┐      ┌───────────────────────────┐
│     Core Services            │      │  Tool Registries          │
├──────────────────────────────┤      ├───────────────────────────┤
│ • SessionManager             │      │ • Core Tools              │
│ • DockerOrchestrator         │      │ • Code Browsing Tools     │
│ • CPGGenerator               │      │ • Taint Analysis Tools    │
│ • QueryExecutor              │      │ • Additional Tools        │
│ • GitManager                 │      │                           │
│ • RedisClient                │      │                           │
└──────────────────────────────┘      └───────────────────────────┘
          │
          ├─────────────────────────────────────────────┐
          │                                             │
          ▼                                             ▼
┌──────────────────────────────┐      ┌───────────────────────────┐
│     Docker Containers        │      │    Redis Cache            │
│     (Joern per session)      │      │    - Sessions             │
│                              │      │    - Query Results        │
│ • One container per session  │      │    - CPG Mappings         │
│ • Isolated environments      │      │                           │
│ • CPG generation & queries   │      │                           │
└──────────────────────────────┘      └───────────────────────────┘
          │
          ▼
┌──────────────────────────────┐
│   Playground Directory       │
│   - codebases/               │
│   - cpgs/                    │
└──────────────────────────────┘
```

## Core Components

### 1. FastMCP Server (`main.py`)

**Purpose**: Entry point and server initialization using the FastMCP 2.12.4 framework.

**Key Features**:
- HTTP transport for network accessibility
- Lifespan context manager for startup/shutdown
- Concurrent client support
- Streamable HTTP responses

**Responsibilities**:
- Service initialization and lifecycle management
- Tool registration
- Request routing
- Error handling and logging

### 2. Service Layer (`src/services/`)

#### SessionManager
**File**: `session_manager.py`

Manages analysis sessions with:
- Session creation and lifecycle (CREATING → READY → CLOSED)
- TTL-based automatic cleanup
- Redis backing for persistence
- Session metadata (language, source type, source path)
- Container tracking

**Key Methods**:
```python
create_session(source_type, source_path, language)
get_session(session_id)
update_session(session_id, status)
touch_session(session_id)  # Reset TTL
close_session(session_id)
```

#### DockerOrchestrator
**File**: `docker_orchestrator.py`

Orchestrates Docker container lifecycle:
- Container creation per session
- Volume mounting (workspace + playground)
- Container cleanup
- Resource management

**Key Methods**:
```python
start_container(session_id, workspace_path, playground_path) → container_id
stop_container(container_id)
get_container(container_id)
cleanup()
```

**Mount Structure**:
```
Container
├── /workspace          → {workspace_root}/repos/{session_id}
├── /playground         → {playground_path}
└── /cpg.bin           → Generated CPG binary
```

#### CPGGenerator
**File**: `cpg_generator.py`

Generates Code Property Graphs from source code:
- Language detection
- Exclusion pattern application
- Java memory optimization
- CPG caching by source+language hash
- Progress tracking

**Key Methods**:
```python
generate_cpg(session_id, source_path, language) → cpg_path
register_session_container(session_id, container_id)
```

**Caching Strategy**:
- Cache key: `SHA256({source_path}|{language}|{exclusion_patterns})`
- CPGs stored in `playground/cpgs/{cache_key}/cpg.bin`
- Reuse across sessions with identical sources

#### QueryExecutor
**File**: `query_executor.py`

Executes CPGQL queries in Docker containers:
- Two execution paths:
  - **Persistent shell mode**: Reuses loaded CPG (fast)
  - **Direct mode**: Spawns new Joern process (slower, fallback)
- Query timeout handling
- Result parsing (JSON, CSV)
- Error recovery

**Query Execution Flow**:
```
1. Get container for session
2. Create unique query ID
3. Write query to temp file in container
4. Execute via Joern shell/script
5. Read JSON result from /tmp/
6. Parse and return results
```

#### GitManager
**File**: `git_manager.py`

Handles repository operations:
- Repository cloning
- Branch selection
- Token-based authentication
- Rate limiting

**Key Methods**:
```python
clone_repository(repo_url, target_path, branch, token)
```

#### RedisClient
**File**: `src/utils/redis_client.py`

Async Redis wrapper for:
- Session persistence
- Query result caching
- Container ID mapping
- Connection pooling

### 3. Tool Layer (`src/tools/`)

#### Core Tools (`core_tools.py`)
- `create_cpg_session`: Initialize analysis session
- `run_cpgql_query`: Synchronous query execution
- `run_cpgql_query_async`: Asynchronous query execution
- `get_query_status`: Poll async query status
- `get_query_result`: Retrieve async results
- `get_session_status`: Session metadata
- `list_sessions`: Active sessions with filtering
- `close_session`: Clean up session resources

#### Code Browsing Tools (`code_browsing_tools.py`)
- `get_codebase_summary`: File/method/call statistics
- `list_files`: Filter files by name/path patterns
- `list_methods`: Discover methods with filtering
- `get_method_source`: Retrieve method source code
- `list_calls`: Find call relationships
- `get_call_graph`: Build call graphs (depth-limited BFS)
- `list_parameters`: Method parameter information
- `find_literals`: Search for hardcoded values
- `get_code_snippet`: Extract code by line range
- `find_bounds_checks`: Detect buffer safety checks

#### Taint Analysis Tools (`taint_analysis_tools.py`)
- `find_taint_sources`: Locate external input points
- `find_taint_sinks`: Find dangerous operations
- `find_taint_flows`: Trace data from source to sink
- `find_argument_flows`: Match expressions across calls
- `check_method_reachability`: BFS reachability in call graph
- `list_taint_paths`: Enumerate detailed flow paths
- `get_program_slice`: Backward/forward data slicing
- `get_data_dependencies`: Variable dependency tracking

### 4. Configuration (`src/config.py`, `config.yaml`)

**ServerConfig**:
```yaml
host: 0.0.0.0
port: 4242
log_level: INFO
```

**RedisConfig**:
```yaml
host: localhost
port: 6379
password: null
db: 0
```

**JoernConfig**:
```yaml
binary_path: joern
memory_limit: 16g
java_opts: "-Xmx16G -Xms8G -XX:+UseG1GC"
```

**CPGConfig**:
- `generation_timeout`: 600s
- `max_repo_size_mb`: 500MB
- `exclusion_patterns`: 50+ patterns for test/doc/build dirs
- `supported_languages`: 13 languages
- `taint_sources/sinks`: Per-language patterns

**SessionConfig**:
```yaml
ttl: 3600              # Session timeout
idle_timeout: 1800     # Inactivity timeout
max_concurrent: 100    # Max concurrent sessions
```

**StorageConfig**:
```yaml
workspace_root: /tmp/joern-mcp
cleanup_on_shutdown: true
```

### 5. Data Models (`src/models.py`)

**Session**:
```python
@dataclass
class Session:
    id: str
    status: str                    # CREATING, READY, CLOSED
    source_type: str               # local, github
    source_path: str
    language: str
    created_at: float
    last_accessed: float
    container_id: Optional[str]
    cpg_path: Optional[str]
```

**QueryResult**:
```python
@dataclass
class QueryResult:
    success: bool
    data: List[Any]                # Query results
    error: Optional[str]           # Error message
    row_count: int
    execution_time: float
```

**SourceType** (Enum):
- LOCAL: Local file system
- GITHUB: GitHub repository

**SessionStatus** (Enum):
- CREATING: CPG generation in progress
- READY: Ready for queries
- CLOSED: Cleaned up

## Request Flow Diagram

### Create Session Flow
```
client.create_cpg_session()
        │
        ▼
validate inputs (source_type, language)
        │
        ├─ GITHUB: git_manager.clone_repository()
        └─ LOCAL: use source_path directly
        │
        ▼
session_manager.create_session() → Session(CREATING)
        │
        ▼
docker.start_container(workspace_path, playground_path)
        │
        ▼
cpg_generator.generate_cpg(source_path, language)
        │ (runs in container)
        ▼
Session(READY) + CPG path stored in Redis
```

### Query Execution Flow
```
client.run_cpgql_query(session_id, query)
        │
        ▼
session_manager.get_session(session_id)
        │
        ▼
query_executor.execute_query()
        │
        ├─ Get container for session
        │
        ├─ Generate unique query_id
        │
        ├─ Write query script to /tmp/query_{id}.sc
        │
        ├─ Execute: joern --script /tmp/query_{id}.sc
        │   └─ Output: /tmp/query_result_{id}.json
        │
        ├─ Read result JSON
        │
        └─ Parse and return QueryResult
```

## Directory Structure

```
joern-mcp/
├── src/
│   ├── __init__.py
│   ├── config.py                 # Configuration loading
│   ├── models.py                 # Data models
│   ├── utils.py                  # Helper utilities
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── session_manager.py    # Session lifecycle
│   │   ├── docker_orchestrator.py # Docker management
│   │   ├── cpg_generator.py      # CPG generation
│   │   ├── query_executor.py     # Query execution
│   │   └── git_manager.py        # Git operations
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── core_tools.py         # Core MCP tools
│   │   ├── code_browsing_tools.py
│   │   ├── taint_analysis_tools.py
│   │   └── mcp_tools.py          # Tool registry
│   │
│   └── utils/
│       ├── __init__.py
│       ├── redis_client.py       # Redis wrapper
│       ├── validators.py         # Input validation
│       └── exceptions.py         # Custom exceptions
│
├── playground/
│   ├── codebases/                # Source code to analyze
│   │   └── core/                 # Sample C codebase
│   │       └── core.c
│   └── cpgs/                     # Cached CPG binaries
│
├── tests/
│   ├── test_utils.py
│   ├── test_mcp_tools.py
│   ├── test_data_dependencies.py
│   └── ...
│
├── examples/
│   ├── sample_client.py          # Basic usage demo
│   ├── browsing_client.py        # Code browsing demo
│   ├── taint_client.py           # Taint analysis demo
│   └── ...
│
├── main.py                       # Server entry point
├── config.yaml                   # Runtime configuration
├── config.example.yaml           # Configuration template
├── requirements.txt              # Python dependencies
├── pyproject.toml               # Project metadata
├── setup.sh                      # Setup script
├── build.sh                      # Build script
├── cleanup.py                    # Resource cleanup utility
├── Dockerfile.joern              # Joern container image
├── README.md                     # User documentation
└── ARCHITECTURE.md               # This file
```

## Data Flow Patterns

### Session Lifecycle
```
┌─────────────────────────────────────────────────────────────┐
│                      Session Lifecycle                       │
└─────────────────────────────────────────────────────────────┘

1. CREATE PHASE (0-2 min typically)
   ├─ create_cpg_session() called
   ├─ Session marked as CREATING
   ├─ Docker container started
   ├─ CPG generated (1-3 min for large repos)
   └─ Session marked as READY

2. ACTIVE PHASE (0-3600s)
   ├─ Queries executed via run_cpgql_query()
   ├─ Each query increments session.last_accessed
   ├─ Results cached in Redis
   └─ TTL reset on each access

3. IDLE PHASE (1800s max)
   ├─ No queries received for 30 minutes
   ├─ Session eligible for cleanup
   └─ Resources released

4. CLEANUP PHASE
   ├─ Container stopped
   ├─ Workspace deleted
   ├─ Redis session entry removed
   └─ Next access creates new session (cache CPG)
```

### Query Caching Strategy
```
┌──────────────────────────────────────────┐
│         Query Result Caching             │
└──────────────────────────────────────────┘

Query received
    │
    ├─ Generate cache key: SHA256(session_id + query)
    │
    ├─ Check Redis: cache_key exists?
    │   ├─ YES: Return cached result (fast path ~10ms)
    │   └─ NO: Continue to execution
    │
    ├─ Execute query in container (1-10s)
    │
    ├─ Store result in Redis
    │   └─ TTL: 5 minutes (QueryConfig.cache_ttl)
    │
    └─ Return result to client

Benefits:
- Identical queries return instantly
- Reduces container CPU load
- Enables fast iteration for analysis
```

### CPG Caching Strategy
```
┌──────────────────────────────────────────┐
│         CPG Generation Caching           │
└──────────────────────────────────────────┘

generate_cpg(source_path, language)
    │
    ├─ Calculate cache key:
    │   cache_key = SHA256(
    │       source_path +
    │       language +
    │       exclusion_patterns_hash
    │   )
    │
    ├─ Check: playground/cpgs/{cache_key}/cpg.bin exists?
    │   ├─ YES: Load from disk (2-5s, cache hit)
    │   └─ NO: Generate new CPG (2-10 min, cache miss)
    │
    └─ Return cpg_path

Implications:
- First session with source: slow (2-10 min)
- Subsequent sessions: fast (reuse CPG)
- GitHub repos cached by URL+branch
- Local codebases cached by absolute path
```

## Concurrency Model

### Threading & Async
```
FastMCP Server (Async)
├─ Handler 1: create_cpg_session()
│   └─ cpu_generator.generate_cpg() → runs in Docker
│
├─ Handler 2: run_cpgql_query()
│   └─ query_executor.execute_query() → Docker
│
└─ Handler N: ...

Each handler:
- Async/await for I/O
- Docker subprocess executed in executor thread pool
- Redis operations async via aioredis
- Max concurrent: 100 sessions (config)
```

### Session Isolation
```
Each session gets:
- Unique session_id (UUID)
- Dedicated Docker container
- Isolated /workspace directory
- Isolated /tmp within container
- Independent CPG instance

No cross-session interference:
- Queries only access own CPG
- Containers cannot see each other
- Workspace isolated by bind mount
- Redis keys namespaced by session_id
```

## Error Handling Strategy

### Error Classification

**Validation Errors** (HTTP 400):
- Invalid source_type
- Unsupported language
- Malformed queries

**Not Found Errors** (HTTP 404):
- Session doesn't exist
- Method not found

**Resource Errors** (HTTP 503):
- Docker connection failure
- Redis connection failure
- Disk space exhausted

**Execution Errors** (HTTP 500):
- CPG generation timeout
- Query execution timeout
- Joern subprocess crash

### Error Recovery

```python
# Example: Query Execution
try:
    result = await query_executor.execute_query(...)
except QueryExecutionError as e:
    logger.error(f"Query failed: {e}")
    return {
        "success": False,
        "error": {
            "code": "QUERY_ERROR",
            "message": str(e)
        }
    }
except Exception as e:
    logger.exception(f"Unexpected error: {e}")
    return {
        "success": False,
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "An unexpected error occurred"
        }
    }
```

## Performance Characteristics

### Typical Operation Times

| Operation | Time | Notes |
|-----------|------|-------|
| Session creation (new) | 2-10 min | Depends on repo size, CPG generation is slow |
| Session creation (cached) | 10-30s | Docker container startup + CPG load |
| Simple query | 500ms-2s | Depends on CPG complexity |
| Complex query | 5-30s | BFS traversals, large result sets |
| Query cache hit | ~10ms | Redis lookup |
| Codebase summary | 1-5s | Statistics collection |
| Call graph (depth 5) | 2-10s | Graph traversal |
| Taint analysis | 5-60s | Path exploration algorithm |

### Memory Usage

| Component | Typical | Peak |
|-----------|---------|------|
| Server process | 100-200MB | 300MB+ with many sessions |
| Docker container | 2-4GB | 8GB+ for large CPGs |
| Redis | 50-500MB | Per cached query results |
| Workspace (/tmp) | 500MB-5GB | Per CPG (persistent) |

### Scalability Limits

- **Max concurrent sessions**: 100 (configurable)
- **Max repo size**: 500MB (configurable)
- **Query timeout**: 300s (configurable)
- **CPG generation timeout**: 600s (configurable)
- **Session TTL**: 3600s (1 hour, configurable)

## Security Considerations

### Input Validation
```python
# All user inputs validated before processing
validate_source_type(source_type)           # Must be "local" or "github"
validate_language(language)                 # Must be in supported list
validate_session_id(session_id)             # Must be valid UUID
validate_github_url(url)                    # Must be valid GitHub URL
```

### Container Isolation
- Each session runs in separate Docker container
- No file system access outside bound volumes
- Network access controlled by Docker daemon
- Resource limits applied (CPU, memory)

### Query Safety
- CPGQL queries execute in isolated Joern instance
- No direct shell access (parameterized execution)
- Timeout prevents runaway queries
- Results sanitized before return

### Credential Management
- GitHub tokens not persisted
- Passed only at clone time
- Credentials never logged
- Environment variables for secrets

## Extension Points

### Adding New Tools

1. **Create tool function**:
```python
# tools/new_tools.py
@mcp.tool()
async def my_new_tool(session_id: str, param1: str) -> Dict[str, Any]:
    """Tool description"""
    pass
```

2. **Register tool**:
```python
# tools/__init__.py
from .new_tools import register_new_tools

def register_tools(mcp, services):
    # ... existing registrations
    register_new_tools(mcp, services)
```

### Adding New Services

1. **Create service class**:
```python
# services/new_service.py
class NewService:
    async def initialize(self):
        pass
    
    async def cleanup(self):
        pass
```

2. **Integrate in lifespan**:
```python
# main.py
services['new_service'] = NewService()
await services['new_service'].initialize()
```

## Testing Strategy

### Unit Tests (`tests/`)
- Model validation
- Utility function behavior
- Error handling

### Integration Tests
- Service interactions
- Docker communication
- Redis operations

### End-to-End Tests
- Full request workflows
- Examples in `examples/`

## Deployment

### Production Checklist
- [ ] Configure `config.yaml` with production settings
- [ ] Set environment variables for secrets
- [ ] Configure Redis for persistence
- [ ] Set up monitoring/logging aggregation
- [ ] Configure resource limits
- [ ] Set up backup for playground/cpgs
- [ ] Test with target codebase size
- [ ] Monitor memory and disk usage

---

**Last Updated**: October 2025
**Version**: 0.2.1