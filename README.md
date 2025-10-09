# 🕷️ joern-mcp

A Model Context Protocol (MCP) server that provides AI assistants with static code analysis capabilities using [Joern](https://joern.io)'s Code Property Graph (CPG) technology.

## Features

- **Multi-Language Support**: Java, C/C++, JavaScript, Python, Go, Kotlin, C#, Ghidra, Jimple, PHP, Ruby, Swift
- **Docker Isolation**: Each analysis session runs in a secure container
- **GitHub Integration**: Analyze repositories directly from GitHub URLs
- **Session-Based**: Persistent CPG sessions with automatic cleanup
- **Redis-Backed**: Fast caching and session management
- **Async Queries**: Non-blocking CPG generation and query execution
- **Built-in Security Queries**: Pre-configured queries for common vulnerabilities

## Quick Start

### Prerequisites

- Python 3.8+
- Docker
- Redis
- Git

### Installation

1. **Clone and install dependencies**:
```bash
git clone https://github.com/Lekssays/joern-mcp.git
cd joern-mcp
pip install -r requirements.txt
```

2. **Setup (builds Joern image and starts Redis)**:
```bash
./setup.sh
```

3. **Configure** (optional):
```bash
cp config.example.yaml config.yaml
# Edit config.yaml as needed
```

4. **Run the server**:
```bash
python main.py
# Server will be available at http://localhost:4242
```

## Integration with GitHub Copilot

The server uses **Streamable HTTP** transport for network accessibility and supports multiple concurrent clients.

Add to your VS Code `settings.json`:

```json
{
  "github.copilot.advanced": {
    "mcp": {
      "servers": {
        "joern-mcp": {
          "url": "http://localhost:4242/mcp",
        }
      }
    }
  }
}
```

Make sure the server is running before using it with Copilot:
```bash
python main.py
```

## Available Tools

### Core Tools

- **`create_cpg_session`**: Initialize analysis session from local path or GitHub URL
- **`run_cpgql_query`**: Execute synchronous CPGQL queries with JSON output
- **`run_cpgql_query_async`**: Execute asynchronous queries with status tracking
- **`get_session_status`**: Check session state and metadata
- **`list_sessions`**: View active sessions with filtering
- **`close_session`**: Clean up session resources
- **`list_queries`**: Get pre-built security and quality queries

### Code Browsing Tools

- **`get_codebase_summary`**: Get high-level overview of codebase (file count, method count, language)
- **`list_files`**: List all source files with optional regex filtering
- **`list_methods`**: Discover all methods/functions with filtering by name, file, or external status
- **`get_method_source`**: Retrieve actual source code for specific methods
- **`list_calls`**: Find function call relationships and dependencies
- **`get_call_graph`**: Build call graphs (outgoing callees or incoming callers) with configurable depth
- **`list_parameters`**: Get detailed parameter information for methods
- **`find_literals`**: Search for hardcoded values (strings, numbers, API keys, etc)
- **`get_code_snippet`**: Retrieve code snippets from files with line range

### Example Usage

```python
# Create session from GitHub
{
  "tool": "create_cpg_session",
  "arguments": {
    "source_type": "github",
    "source_path": "https://github.com/user/repo",
    "language": "java"
  }
}

# Get codebase overview
{
  "tool": "get_codebase_summary",
  "arguments": {
    "session_id": "abc-123-def"
  }
}

# List all methods in the codebase
{
  "tool": "list_methods",
  "arguments": {
    "session_id": "abc-123-def",
    "include_external": false,
    "limit": 50
  }
}

# Get source code for a specific method
{
  "tool": "get_method_source",
  "arguments": {
    "session_id": "abc-123-def",
    "method_name": "authenticate"
  }
}

# Find what methods call a specific function
{
  "tool": "get_call_graph",
  "arguments": {
    "session_id": "abc-123-def",
    "method_name": "execute_query",
    "depth": 2,
    "direction": "incoming"
  }
}

# Search for hardcoded secrets
{
  "tool": "find_literals",
  "arguments": {
    "session_id": "abc-123-def",
    "pattern": "(?i).*(password|secret|api_key).*",
    "limit": 20
  }
}

# Get code snippet from a file
{
  "tool": "get_code_snippet",
  "arguments": {
    "session_id": "abc-123-def",
    "filename": "src/main.c",
    "start_line": 10,
    "end_line": 25
  }
}

# Run custom CPGQL query
{
  "tool": "run_cpgql_query",
  "arguments": {
    "session_id": "abc-123-def",
    "query": "cpg.method.name.l"
  }
}
```

### Pre-Built Queries

The `list_queries` tool provides 20+ pre-configured queries including:

**Security:**
- SQL injection detection
- XSS vulnerabilities
- Hardcoded secrets
- Command injection
- Path traversal

**Memory Safety:**
- Buffer overflow risks
- Memory leaks
- Null pointer dereferences
- Uninitialized variables

**Code Quality:**
- All methods/functions
- Control structures
- Function calls
- String literals

## Configuration

Key settings in `config.yaml`:

```yaml
server:
  host: 0.0.0.0
  port: 4242
  log_level: INFO

redis:
  host: localhost
  port: 6379

sessions:
  ttl: 3600                # Session timeout (seconds)
  max_concurrent: 50       # Max concurrent sessions

cpg:
  generation_timeout: 600  # CPG generation timeout (seconds)
  supported_languages: [java, c, cpp, javascript, python, go, kotlin, csharp, ghidra, jimple, php, ruby, swift]
```

Environment variables override config file settings (e.g., `MCP_HOST`, `REDIS_HOST`, `SESSION_TTL`).

## Example CPGQL Queries

**Find all methods:**
```scala
cpg.method.name.l
```

**Find hardcoded secrets:**
```scala
cpg.literal.code("(?i).*(password|secret|api_key).*").l
```

**Find SQL injection risks:**
```scala
cpg.call.name(".*execute.*").where(_.argument.isLiteral.code(".*SELECT.*")).l
```

**Find complex methods:**
```scala
cpg.method.filter(_.cyclomaticComplexity > 10).l
```

## Architecture

- **FastMCP Server**: Built on FastMCP 2.12.4 framework with **Streamable HTTP** transport
- **HTTP Transport**: Network-accessible API supporting multiple concurrent clients
- **Docker Containers**: One isolated Joern container per session
- **Redis**: Session state and query result caching
- **Async Processing**: Non-blocking CPG generation
- **CPG Caching**: Reuse CPGs for identical source/language combinations

## Development

### Project Structure

```
joern-mcp/
├── src/
│   ├── services/       # Session, Docker, Git, CPG, Query services
│   ├── tools/          # MCP tool definitions
│   ├── utils/          # Redis, logging, validators
│   └── models.py       # Data models
├── playground/         # Test codebases and CPGs
├── main.py            # Server entry point
├── config.yaml        # Configuration
└── requirements.txt   # Dependencies
```

### Running Tests

```bash
# Install dev dependencies
pip install -r requirements.txt

# Run tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html
```

### Code Quality

```bash
# Format
black src/ tests/
isort src/ tests/

# Lint
flake8 src/ tests/
mypy src/
```

## Troubleshooting

**Setup issues:**
```bash
# Re-run setup to rebuild and restart services
./setup.sh
```

**Docker issues:**
```bash
# Verify Docker is running
docker ps

# Check Joern image
docker images | grep joern

# Check Redis container
docker ps | grep joern-redis
```

**Redis connection issues:**
```bash
# Test Redis connection
docker exec joern-redis redis-cli ping

# Check Redis logs
docker logs joern-redis

# Restart Redis
docker restart joern-redis
```

**Server connectivity:**
```bash
# Test server is running
curl http://localhost:4242/health

# Check server logs for errors
python main.py
```

**Debug logging:**
```bash
export MCP_LOG_LEVEL=DEBUG
python main.py
```

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make changes and add tests
4. Run tests: `pytest && black . && flake8`
5. Submit a pull request

## Acknowledgments

- [Joern](https://github.com/joernio/joern) - Static analysis platform
- [FastMCP](https://github.com/jlowin/fastmcp) - MCP framework
- [Model Context Protocol](https://modelcontextprotocol.io/) - MCP specification
