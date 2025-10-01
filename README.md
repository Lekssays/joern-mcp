# 🕷️ joern-mcp

A production-ready Model Context Protocol (MCP) server that provides AI assistants with static code analysis capabilities using Joern's Code Property Graph (CPG) technology.

## Overview

The Joern MCP Server enables AI coding assistants to perform sophisticated static code analysis by leveraging Joern's powerful CPG-based analysis in isolated Docker environments. It implements the Model Context Protocol standard, making it compatible with various AI assistants and development environments.

## Features

- **Static Code Analysis**: Deep code analysis using Joern's CPG technology
- **Multi-Language Support**: C/C++, Java, JavaScript/TypeScript, Python, Go, Kotlin, Scala, C#
- **Isolated Execution**: All analysis runs in secure Docker containers
- **Intelligent Caching**: Efficient CPG caching with configurable TTL
- **GitHub Integration**: Direct analysis of GitHub repositories
- **Production Ready**: Comprehensive error handling, logging, and monitoring
- **MCP Compliance**: Full Model Context Protocol implementation

## Quick Start

### Prerequisites

- Python 3.8+
- Docker
- Git

### Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd joern-mcp
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Build Joern Docker image**:
   ```bash
   # Option 1: Use the build script (recommended)
   ./build.sh
   
   # Option 2: Build manually
   docker build -t joern:latest .
   ```

### Running the Server

**Validate setup first**:
```bash
python validate.py
```

**Basic usage**:
```bash
python main.py
```

**With configuration file**:
```bash
python main.py config.yml
```

**Using environment variables**:
```bash
export JOERN_DOCKER_IMAGE=joern:latest
export JOERN_CACHE_DIR=/tmp/joern_cache
export GITHUB_TOKEN=your_token_here
python main.py
```

> **Note**: The `joern:latest` image is built locally using the included Dockerfile, not pulled from a registry.

## Configuration

Create a `config.yml` file for custom configuration:

```yaml
docker:
  image: "joern:latest"
  cpu_limit: "2"
  memory_limit: "4g"
  timeout: 300
  network_mode: "none"

cache:
  enabled: true
  max_size_gb: 10
  ttl_hours: 24
  directory: "/tmp/joern_cache"

max_concurrent_analyses: 3
github_token: "your_github_token"  # Optional, for private repos
log_level: "INFO"
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `JOERN_DOCKER_IMAGE` | Joern Docker image | `joern:latest` |
| `JOERN_CPU_LIMIT` | CPU limit for containers | `2` |
| `JOERN_MEMORY_LIMIT` | Memory limit for containers | `4g` |
| `JOERN_TIMEOUT` | Container timeout (seconds) | `300` |
| `JOERN_CACHE_ENABLED` | Enable CPG caching | `true` |
| `JOERN_CACHE_SIZE_GB` | Cache size limit (GB) | `10` |
| `JOERN_CACHE_DIR` | Cache directory | `/tmp/joern_cache` |
| `GITHUB_TOKEN` | GitHub access token | - |
| `JOERN_LOG_LEVEL` | Logging level | `INFO` |

## Usage with AI Assistants

### VS Code with GitHub Copilot

Add to VS Code `settings.json`:
```json
{
  "github.copilot.advanced": {
    "mcp.servers": [{
      "name": "joern-mcp",
      "command": ["python", "main.py"],
      "workingDir": "/path/to/joern-mcp"
    }]
  }
}
```

### Claude Desktop

Configure in Claude Desktop settings:
```json
{
  "mcp": {
    "servers": [{
      "name": "joern-mcp",
      "command": ["python", "main.py"],
      "workingDirectory": "/path/to/joern-mcp"
    }]
  }
}
```

## Available Tools

### Core Tools

- **`load_project`**: Load code from GitHub URL or local path
- **`generate_cpg`**: Generate Code Property Graph for analysis
- **`run_query`**: Execute Joern queries against the CPG
- **`list_projects`**: List all loaded projects
- **`project_info`**: Get detailed project information
- **`cleanup_project`**: Clean up project resources

### Pre-built Queries

- **`list_queries`**: Access security, quality, and metrics queries

#### Security Queries
- SQL injection detection
- XSS sink identification
- Hardcoded secrets discovery
- Unsafe deserialization patterns

#### Quality Queries
- Complex methods detection
- Long methods identification
- Duplicate code analysis
- Unused variables discovery

#### Metrics Queries
- Total methods/classes/files count
- Average cyclomatic complexity

## Example Usage

### Load and Analyze a Project

```python
# Example MCP client interaction
{
  "tool": "load_project",
  "arguments": {
    "source": "https://github.com/user/repo",
    "branch": "main"
  }
}

{
  "tool": "generate_cpg",
  "arguments": {
    "project_id": "abc12345"
  }
}

{
  "tool": "run_query",
  "arguments": {
    "project_id": "abc12345",
    "query": "cpg.method.filter(_.cyclomaticComplexity > 10)"
  }
}
```

### Common Queries

**Find all functions**:
```scala
cpg.method.l
```

**Find function calls**:
```scala
cpg.call.l
```

**Security analysis**:
```scala
cpg.call.name(".*exec.*").code
```

**Complex methods**:
```scala
cpg.method.filter(_.cyclomaticComplexity > 10)
```

## Development

### Project Structure

```
joern-mcp/
├── src/
│   ├── __init__.py
│   ├── server.py          # Main server implementation
│   ├── models.py          # Data models and exceptions
│   ├── utils.py           # Utility functions
│   └── config.py          # Configuration management
├── tests/
│   ├── conftest.py        # Test configuration
│   ├── test_server.py     # Server integration tests
│   ├── test_models.py     # Model unit tests
│   └── test_utils.py      # Utility function tests
├── examples/
│   └── sample.c           # Sample code for testing
├── main.py                # Entry point
├── test_client.py         # Simple test client
├── validate.py            # Setup validation script
├── requirements.txt       # Dependencies
├── Dockerfile             # Joern Docker image
├── build.sh              # Docker build script
└── README.md
```

### Running Tests

**Run all tests**:
```bash
pytest
```

**Run with coverage**:
```bash
pytest --cov=src --cov-report=html
```

**Run integration tests** (requires Docker):
```bash
pytest -m integration
```

**Run specific test file**:
```bash
pytest tests/test_server.py
```

### Code Quality

**Format code**:
```bash
black src/ tests/
isort src/ tests/
```

**Lint code**:
```bash
flake8 src/ tests/
mypy src/
```

## Troubleshooting

### Common Issues

**Docker connection error**:
- Ensure Docker is running
- Check Docker daemon accessibility
- Verify user permissions for Docker socket

**Image not found**:
- Build the Joern image: `docker build -t joern:latest .`
- Check image name in configuration
- Verify the build completed successfully: `docker images | grep joern`

**Docker build issues**:
- Ensure Docker has sufficient disk space
- Check internet connectivity for downloading Joern
- Try building with more verbose output: `docker build -t joern:latest . --progress=plain`

**Memory issues**:
- Increase Docker memory limit in config
- Reduce concurrent analysis limit
- Clear cache directory

**Permission errors**:
- Check file/directory permissions
- Ensure cache directory is writable
- Verify Docker socket permissions

### Logging

Enable debug logging for troubleshooting:
```bash
export JOERN_LOG_LEVEL=DEBUG
python main.py
```

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make changes and add tests
4. Run tests and linting: `pytest && black . && flake8`
5. Commit changes: `git commit -am 'Add feature'`
6. Push to branch: `git push origin feature-name`
7. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- [Joern](https://github.com/joernio/joern) - Static analysis platform
- [Model Context Protocol](https://modelcontextprotocol.io/) - AI assistant integration standard