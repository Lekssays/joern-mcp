# 🕷️ joern-mcp - Complete Feature Documentation

**Version:** 0.2.1  
**Last Updated:** October 2025

This document provides comprehensive documentation of all features and tools available in the joern-mcp Model Context Protocol (MCP) server, extracted from source code docstrings and implementation details.

---

## Table of Contents

1. [Overview](#overview)
2. [Getting Started](#getting-started)
3. [Core Features](#core-features)
   - [Session Management](#session-management)
   - [Query Execution](#query-execution)
4. [Code Browsing Tools](#code-browsing-tools)
5. [Security Analysis Tools](#security-analysis-tools)
6. [Example Workflows](#example-workflows)
7. [Advanced Topics](#advanced-topics)

---

## Overview

**joern-mcp** is a Model Context Protocol (MCP) server that provides AI assistants with static code analysis capabilities using Joern's Code Property Graph (CPG) technology.

### Key Capabilities

- **Multi-Language Support:** Java, C/C++, JavaScript, Python, Go, Kotlin, C#, Ghidra, Jimple, PHP, Ruby, Swift
- **Docker Isolation:** Each analysis session runs in a secure, isolated container
- **GitHub Integration:** Analyze repositories directly from GitHub URLs with optional authentication
- **Persistent Sessions:** Session-based analysis with automatic cleanup after configurable TTL
- **Redis Caching:** Fast caching of CPG binaries and query results for rapid iteration
- **Asynchronous Operations:** Non-blocking CPG generation and query execution
- **Security Analysis:** Taint analysis, data flow tracking, and vulnerability detection

---

## Getting Started

### Installation & Setup

1. **Clone and install dependencies:**
   ```bash
   git clone https://github.com/Lekssays/joern-mcp.git
   cd joern-mcp
   pip install -r requirements.txt
   ```

2. **Run setup (builds Joern image and starts Redis):**
   ```bash
   ./setup.sh
   ```

3. **Configure (optional):**
   ```bash
   cp config.example.yaml config.yaml
   # Edit config.yaml as needed
   ```

4. **Run the server:**
   ```bash
   python main.py
   # Server will be available at http://localhost:4242
   ```

### Supported Languages

| Language | Status | CPG Support |
|----------|--------|-------------|
| Java | ✅ | Full |
| C | ✅ | Full |
| C++ | ✅ | Full |
| JavaScript | ✅ | Full |
| Python | ✅ | Full |
| Go | ✅ | Full |
| Kotlin | ✅ | Full |
| C# | ✅ | Full |
| Ghidra | ✅ | Binary analysis |
| Jimple | ✅ | Bytecode analysis |
| PHP | ✅ | Full |
| Ruby | ✅ | Full |
| Swift | ✅ | Full |

---

## Core Features

### Session Management

#### `create_cpg_session`

Creates a new Code Property Graph analysis session for a codebase.

**Description:** Initiates CPG generation for a codebase. For GitHub repositories, it clones the repo first. For local paths, it uses the existing directory. The CPG generation happens asynchronously in a Docker container. CPG binaries are cached by source+language, enabling rapid session creation for subsequent analyses.

**Parameters:**
- `source_type` (string, required): Either `"local"` or `"github"`
- `source_path` (string, required): 
  - For local: Absolute path to source directory (e.g., `/home/user/projects/myapp`)
  - For github: Full GitHub URL (e.g., `https://github.com/user/repo`)
- `language` (string, required): Programming language - one of the supported languages listed above
- `github_token` (string, optional): GitHub Personal Access Token for accessing private repositories
- `branch` (string, optional): Specific git branch to checkout (defaults to repository default branch)

**Returns:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "initializing",
  "message": "CPG generation started",
  "estimated_time": "2-5 minutes"
}
```

**Response Fields:**
- `session_id`: Unique identifier for the session; use this for all subsequent operations
- `status`: Current session status - `"initializing"`, `"generating"`, `"ready"`, or `"error"`
- `message`: Human-readable status message
- `estimated_time`: Rough estimate of CPG generation time (depends on codebase size)

**Example - GitHub Repository:**
```json
{
  "tool": "create_cpg_session",
  "arguments": {
    "source_type": "github",
    "source_path": "https://github.com/torvalds/linux",
    "language": "c",
    "branch": "master"
  }
}
```

**Example - Local Directory:**
```json
{
  "tool": "create_cpg_session",
  "arguments": {
    "source_type": "local",
    "source_path": "/home/user/myproject",
    "language": "java"
  }
}
```

**Example - Private GitHub Repository:**
```json
{
  "tool": "create_cpg_session",
  "arguments": {
    "source_type": "github",
    "source_path": "https://github.com/company/private-repo",
    "language": "python",
    "github_token": "ghp_xxxxx..."
  }
}
```

**Important Notes:**
- First session with a codebase: 2-10 minutes (CPG generation is computationally expensive)
- Subsequent sessions: 10-30 seconds (CPG reused from cache)
- CPG size typically 2-5GB for medium projects
- Sessions automatically close after 1 hour of inactivity (configurable)

---

#### `get_session_status`

Retrieve the current status and metadata of a session.

**Parameters:**
- `session_id` (string, required): The session ID from `create_cpg_session`

**Returns:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "ready",
  "source_type": "github",
  "source_path": "https://github.com/user/repo",
  "language": "java",
  "created_at": "2025-10-07T10:00:00Z",
  "last_accessed": "2025-10-07T10:05:00Z",
  "cpg_size": "125MB",
  "error_message": null
}
```

**Use Cases:**
- Check if CPG generation is complete before running queries
- Monitor session activity and resource usage
- Verify session still exists and hasn't been cleaned up

---

#### `list_sessions`

List all active sessions with optional filtering.

**Parameters:**
- `status` (string, optional): Filter by status - `"ready"`, `"generating"`, `"error"`, `"initializing"`
- `source_type` (string, optional): Filter by source type - `"local"` or `"github"`

**Returns:**
```json
{
  "sessions": [
    {
      "session_id": "550e8400-e29b-41d4-a716-446655440000",
      "status": "ready",
      "source_path": "https://github.com/user/repo",
      "language": "java",
      "created_at": "2025-10-07T10:00:00Z"
    },
    {
      "session_id": "550e8400-e29b-41d4-a716-446655441111",
      "status": "generating",
      "source_path": "/home/user/myproject",
      "language": "python",
      "created_at": "2025-10-07T11:00:00Z"
    }
  ],
  "total": 2
}
```

---

#### `close_session`

Close a session and clean up its resources.

**Parameters:**
- `session_id` (string, required): The session ID to close

**Returns:**
```json
{
  "success": true,
  "message": "Session closed successfully",
  "freed_resources": {
    "container_id": "abc123def456",
    "workspace_path": "/tmp/joern-mcp/repos/550e8400-e29b-41d4-a716-446655440000",
    "freed_disk_space_mb": 4096
  }
}
```

**Important:** 
- This immediately terminates the Docker container
- All unsaved analysis results are lost
- CPG cache is preserved for future sessions

---

#### `cleanup_all_sessions`

Clean up multiple sessions and their containers.

**Parameters:**
- `max_age_hours` (integer, optional): Only cleanup sessions older than this many hours
- `force` (boolean, optional): If `true`, cleanup all sessions regardless of age (default: `false`)

**Returns:**
```json
{
  "success": true,
  "cleaned_up": 5,
  "session_ids": ["id1", "id2", "id3", "id4", "id5"],
  "message": "Cleaned up 5 sessions"
}
```

---

### Query Execution

#### `run_cpgql_query`

Execute a synchronous CPGQL query against a loaded CPG.

**Description:** Runs CPGQL queries against the Code Property Graph and waits for completion before returning results. For long-running queries, consider using `run_cpgql_query_async` instead.

**Parameters:**
- `session_id` (string, required): The session ID from `create_cpg_session`
- `query` (string, required): CPGQL query string (Scala-based DSL for Joern)
- `timeout` (integer, optional): Maximum execution time in seconds (default: 30)
- `limit` (integer, optional): Maximum number of results to return (default: 150)

**Returns:**
```json
{
  "success": true,
  "data": [
    {"property1": "value1", "property2": "value2"},
    {"property1": "value3", "property2": "value4"}
  ],
  "row_count": 2,
  "execution_time": 1.23
}
```

**Example - Find all methods:**
```json
{
  "tool": "run_cpgql_query",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "query": "cpg.method.name.l",
    "limit": 100
  }
}
```

**Example - Find hardcoded secrets:**
```json
{
  "tool": "run_cpgql_query",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "query": "cpg.literal.code(\"(?i).*(password|secret|api_key).*\").l",
    "limit": 50
  }
}
```

**Example - Find SQL injection risks:**
```json
{
  "tool": "run_cpgql_query",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "query": "cpg.call.name(\".*execute.*\").where(_.argument.isLiteral.code(\".*SELECT.*\")).l",
    "limit": 20
  }
}
```

**Example - Find complex methods:**
```json
{
  "tool": "run_cpgql_query",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "query": "cpg.method.filter(_.cyclomaticComplexity > 10).l",
    "limit": 30
  }
}
```

**Performance Characteristics:**
- Simple queries: 500ms - 2s
- Complex queries: 5 - 30s
- Cached queries: ~10ms
- First query in a session: 3-5s (CPG load time)

---

#### `run_cpgql_query_async`

Execute a CPGQL query asynchronously and get status updates.

**Description:** Starts a CPGQL query execution and returns immediately with a query ID. Use `get_query_status` to check progress and `get_query_result` to retrieve results once completed.

**Parameters:**
- `session_id` (string, required): The session ID
- `query` (string, required): CPGQL query string
- `timeout` (integer, optional): Maximum execution time in seconds (default: 30)
- `limit` (integer, optional): Maximum number of results (default: 150)

**Returns:**
```json
{
  "success": true,
  "query_id": "query-uuid-123",
  "status": "pending",
  "message": "Query started successfully"
}
```

**Example:**
```json
{
  "tool": "run_cpgql_query_async",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "query": "cpg.method.name.l",
    "timeout": 60
  }
}
```

---

#### `get_query_status`

Check the status of an asynchronously running query.

**Parameters:**
- `query_id` (string, required): The query ID from `run_cpgql_query_async`

**Returns:**
```json
{
  "query_id": "query-uuid-123",
  "status": "completed",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "query": "cpg.method.name.l",
  "created_at": 1697524800.0,
  "execution_time": 1.23,
  "error": null
}
```

**Possible Status Values:**
- `"pending"`: Query waiting to be executed
- `"running"`: Query currently executing
- `"completed"`: Query finished successfully
- `"failed"`: Query execution failed
- `"timeout"`: Query exceeded timeout limit

---

#### `get_query_result`

Retrieve the results of a completed async query.

**Parameters:**
- `query_id` (string, required): The query ID from `run_cpgql_query_async`

**Returns:**
```json
{
  "success": true,
  "data": [
    {"_1": "value1", "_2": "value2"},
    {"_1": "value3", "_2": "value4"}
  ],
  "row_count": 2,
  "execution_time": 1.23
}
```

**Note:** Only available when query status is `"completed"`.

---

#### `cleanup_queries`

Clean up old completed query results to free resources.

**Description:** Remove old query results and temporary files from completed or failed queries. Helps maintain system performance by cleaning up accumulated query data.

**Parameters:**
- `session_id` (string, optional): Only cleanup queries for specific session
- `max_age_hours` (integer, optional): Remove queries older than this many hours (default: 1)

**Returns:**
```json
{
  "success": true,
  "cleaned_up": 3,
  "message": "Cleaned up 3 old queries"
}
```

---

## Code Browsing Tools

### Overview

Code browsing tools help you understand the structure and composition of a codebase by navigating methods, calls, dependencies, and source code.

---

### `list_methods`

List all methods/functions in the codebase with optional filtering.

**Description:** Discover all methods and functions defined in the analyzed code. This is essential for understanding the codebase structure and finding specific functions to analyze.

**Parameters:**
- `session_id` (string, required): The session ID
- `name_pattern` (string, optional): Regex to filter method names (e.g., `".*authenticate.*"`)
- `file_pattern` (string, optional): Regex to filter by file path
- `callee_pattern` (string, optional): Regex to filter for methods that call a specific function (e.g., `"memcpy|free|malloc"`)
- `include_external` (boolean, optional): Include external/library methods (default: `false`)
- `limit` (integer, optional): Maximum number of results to return (default: 100)

**Returns:**
```json
{
  "success": true,
  "methods": [
    {
      "node_id": "12345",
      "name": "main",
      "fullName": "main",
      "signature": "int main(int, char**)",
      "filename": "main.c",
      "lineNumber": 10,
      "isExternal": false
    }
  ],
  "total": 1
}
```

**Examples:**

Find authentication-related methods:
```json
{
  "tool": "list_methods",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "name_pattern": ".*auth.*",
    "limit": 50
  }
}
```

Find methods that use memory allocation:
```json
{
  "tool": "list_methods",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "callee_pattern": "malloc|calloc|realloc",
    "limit": 50
  }
}
```

---

### `get_method_source`

Retrieve the actual source code for a specific method.

**Description:** Get the full source code implementation of a method to understand its implementation details and behavior.

**Parameters:**
- `session_id` (string, required): The session ID
- `method_name` (string, required): Name of the method (can be regex pattern)
- `filename` (string, optional): Optional filename to disambiguate methods with same name

**Returns:**
```json
{
  "success": true,
  "methods": [
    {
      "name": "main",
      "filename": "main.c",
      "lineNumber": 10,
      "lineNumberEnd": 20,
      "code": "int main() {\n    printf(\"Hello World\");\n    return 0;\n}"
    }
  ],
  "total": 1
}
```

**Example:**
```json
{
  "tool": "get_method_source",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "method_name": "authenticate",
    "filename": "auth.c"
  }
}
```

---

### `list_calls`

List function/method calls in the codebase.

**Description:** Discover call relationships between functions. Essential for understanding control flow and dependencies in the code.

**Parameters:**
- `session_id` (string, required): The session ID
- `caller_pattern` (string, optional): Regex to filter caller method names
- `callee_pattern` (string, optional): Regex to filter callee method names
- `limit` (integer, optional): Maximum number of results (default: 100)

**Returns:**
```json
{
  "success": true,
  "calls": [
    {
      "caller": "main",
      "callee": "helper",
      "code": "helper(x)",
      "filename": "main.c",
      "lineNumber": 15
    }
  ],
  "total": 1
}
```

**Examples:**

Find all system calls:
```json
{
  "tool": "list_calls",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "callee_pattern": "system",
    "limit": 50
  }
}
```

Find all calls from a specific method:
```json
{
  "tool": "list_calls",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "caller_pattern": "main",
    "limit": 50
  }
}
```

---

### `get_call_graph`

Build a call graph for a specific method showing its dependencies.

**Description:** Understand what functions a method calls (outgoing) or what functions call it (incoming). Essential for impact analysis and understanding code dependencies.

**Parameters:**
- `session_id` (string, required): The session ID
- `method_name` (string, required): Name of the method to analyze (can be regex)
- `depth` (integer, optional): How many levels deep to traverse (default: 5, max: 15)
- `direction` (string, optional): `"outgoing"` (callees) or `"incoming"` (callers) - default: `"outgoing"`

**Returns:**
```json
{
  "success": true,
  "root_method": "authenticate",
  "direction": "outgoing",
  "calls": [
    {
      "from": "authenticate",
      "to": "validate_password",
      "depth": 1
    },
    {
      "from": "validate_password",
      "to": "hash_password",
      "depth": 2
    }
  ],
  "total": 2
}
```

**Examples:**

What does `authenticate` call?
```json
{
  "tool": "get_call_graph",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "method_name": "authenticate",
    "direction": "outgoing",
    "depth": 3
  }
}
```

What calls `process_data`?
```json
{
  "tool": "get_call_graph",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "method_name": "process_data",
    "direction": "incoming",
    "depth": 3
  }
}
```

---

### `list_parameters`

Get detailed parameter information for methods.

**Description:** Retrieve the parameter list and types for a specific method, useful for understanding function signatures and API contracts.

**Parameters:**
- `session_id` (string, required): The session ID
- `method_name` (string, required): Name of the method (can be regex pattern)

**Returns:**
```json
{
  "success": true,
  "methods": [
    {
      "method": "authenticate",
      "parameters": [
        {"name": "username", "type": "string", "index": 1},
        {"name": "password", "type": "string", "index": 2}
      ]
    }
  ],
  "total": 1
}
```

---

### `find_literals`

Search for hardcoded values (strings, numbers, constants) in the codebase.

**Description:** Find literal values like strings, numbers, or constants. Useful for finding configuration values, API keys, URLs, magic numbers, or potential security issues.

**Parameters:**
- `session_id` (string, required): The session ID
- `pattern` (string, optional): Regex to filter literal values (e.g., `".*password.*"`)
- `literal_type` (string, optional): Type filter - `"string"` or `"int"`
- `limit` (integer, optional): Maximum number of results (default: 50)

**Returns:**
```json
{
  "success": true,
  "literals": [
    {
      "value": "admin_password",
      "type": "string",
      "filename": "config.c",
      "lineNumber": 42,
      "method": "init_config"
    }
  ],
  "total": 1
}
```

**Examples:**

Find potential hardcoded secrets:
```json
{
  "tool": "find_literals",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "pattern": "(?i).*(password|secret|api|token|key).*",
    "limit": 100
  }
}
```

Find all magic numbers:
```json
{
  "tool": "find_literals",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "literal_type": "int",
    "limit": 50
  }
}
```

---

### `get_code_snippet`

Extract source code by file and line range.

**Description:** Retrieve a specific snippet of code from a file using line numbers.

**Parameters:**
- `session_id` (string, required): The session ID
- `filename` (string, required): Name of file relative to source root (e.g., `"src/main.c"`)
- `start_line` (integer, required): Starting line number (1-indexed)
- `end_line` (integer, required): Ending line number (1-indexed, inclusive)

**Returns:**
```json
{
  "success": true,
  "filename": "main.c",
  "start_line": 10,
  "end_line": 20,
  "code": "int main() {\n    printf(\"Hello\");\n    return 0;\n}"
}
```

**Example:**
```json
{
  "tool": "get_code_snippet",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "filename": "main.c",
    "start_line": 10,
    "end_line": 25
  }
}
```

---

### `get_codebase_summary`

Get a high-level overview of the codebase structure.

**Description:** Provides statistical overview of the codebase including file count, method count, language, and other metadata. Useful as a first step when exploring a new codebase.

**Parameters:**
- `session_id` (string, required): The session ID

**Returns:**
```json
{
  "success": true,
  "summary": {
    "language": "C",
    "total_files": 15,
    "total_methods": 127,
    "total_calls": 456,
    "external_methods": 89,
    "lines_of_code": 5432
  }
}
```

---

### `list_files`

List all source files in the analyzed codebase.

**Description:** Discover the file structure of the codebase by listing all files with optional regex filtering.

**Parameters:**
- `session_id` (string, required): The session ID
- `pattern` (string, optional): Regex pattern to filter file paths (e.g., `".*\\.java$"` for Java files)

**Returns:**
```json
{
  "success": true,
  "tree": {
    "src": {
      "main.py": null,
      "api": {
        "handler.py": null
      }
    },
    "tests": {
      "test_main.py": null
    }
  },
  "total": 15
}
```

**Examples:**

List all Java files:
```json
{
  "tool": "list_files",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "pattern": ".*\\.java$"
  }
}
```

---

### `find_bounds_checks`

Detect buffer safety checks in the code.

**Description:** Find where buffer bounds are being checked, useful for identifying potential buffer overflow vulnerabilities or understanding defensive coding patterns.

**Parameters:**
- `session_id` (string, required): The session ID
- `pattern` (string, optional): Regex to filter methods containing bounds checks
- `limit` (integer, optional): Maximum number of results (default: 100)

**Returns:**
```json
{
  "success": true,
  "bounds_checks": [
    {
      "method": "process_buffer",
      "filename": "buffer.c",
      "lineNumber": 42,
      "check_code": "if (size > MAX_SIZE)",
      "protection_pattern": "MAX_SIZE"
    }
  ],
  "total": 1
}
```

---

## Security Analysis Tools

### Overview

Security analysis tools help identify potential vulnerabilities by analyzing taint flows, data dependencies, and dangerous function usage patterns.

---

### `find_taint_sources`

Locate external input points (taint sources).

**Description:** Search for function calls that could be entry points for untrusted data, such as user input, environment variables, or network data. Useful for identifying where external data enters the program.

**Parameters:**
- `session_id` (string, required): The session ID
- `language` (string, optional): Programming language for default patterns (e.g., `"c"`, `"java"`)
  - If not provided, uses the session's language
- `source_patterns` (array, optional): List of regex patterns to match source function names
  - Examples: `["getenv", "fgets", "scanf"]`
  - If not provided, uses default patterns for the language
- `limit` (integer, optional): Maximum number of results (default: 200)

**Returns:**
```json
{
  "success": true,
  "sources": [
    {
      "node_id": "12345",
      "name": "getenv",
      "code": "getenv(\"PATH\")",
      "filename": "main.c",
      "lineNumber": 42,
      "method": "main"
    }
  ],
  "total": 1
}
```

**Example:**
```json
{
  "tool": "find_taint_sources",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "language": "c",
    "source_patterns": ["getenv", "fgets", "scanf", "read"],
    "limit": 200
  }
}
```

**Default Source Patterns (C):**
`getenv`, `fgets`, `scanf`, `read`, `recv`, `accept`, `fopen`

---

### `find_taint_sinks`

Locate dangerous functions where tainted data could cause vulnerabilities.

**Description:** Search for function calls that could be security-sensitive destinations for data, such as system execution, file operations, or format strings. Useful for identifying where untrusted data could cause harm.

**Parameters:**
- `session_id` (string, required): The session ID
- `language` (string, optional): Programming language for default patterns
- `sink_patterns` (array, optional): List of regex patterns to match sink function names
  - Examples: `["system", "popen", "sprintf"]`
  - If not provided, uses default patterns
- `limit` (integer, optional): Maximum number of results (default: 200)

**Returns:**
```json
{
  "success": true,
  "sinks": [
    {
      "node_id": "67890",
      "name": "system",
      "code": "system(cmd)",
      "filename": "main.c",
      "lineNumber": 100,
      "method": "execute_command"
    }
  ],
  "total": 1
}
```

**Example:**
```json
{
  "tool": "find_taint_sinks",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "language": "c",
    "sink_patterns": ["system", "popen", "execl", "sprintf", "fprintf"],
    "limit": 200
  }
}
```

**Default Sink Patterns (C):**
`system`, `popen`, `execl`, `execv`, `sprintf`, `fprintf`

---

### `find_taint_flows`

Find dataflow paths from source to sink.

**Description:** Traces how data flows from a source call (e.g., `malloc`, `getenv`) to a sink call (e.g., `free`, `system`) by following intermediate variables, assignments, and identifiers.

**⚠️ Important Limitations:**

**What It CAN Do:**
- Track return value flows: `allocate() → variable → deallocate(variable)`
- Trace variable assignments across statements in the same function
- Find direct identifier matches between source output and sink input
- Work within intra-procedural scope (same function/method)

**What It CANNOT Do:**
- Interprocedural dataflow (across function boundaries)
- Complex transformations or computations on data
- Array element or struct field flows
- Control-flow dependent paths

**Parameters:**
- `session_id` (string, required): The session ID
- `source_node_id` (string, optional): Node ID of source call (from `find_taint_sources`)
- `sink_node_id` (string, optional): Node ID of sink call (from `find_taint_sinks`)
- `source_location` (string, optional): Alternative format `"filename:line"` or `"filename:line:method"`
- `sink_location` (string, optional): Alternative format `"filename:line"` or `"filename:line:method"`
- `max_path_length` (integer, optional): Maximum path length to consider (default: 20)
- `timeout` (integer, optional): Maximum execution time in seconds (default: 60)

**Returns (with both source and sink):**
```json
{
  "success": true,
  "source": {
    "node_id": "12345",
    "code": "allocate_memory(100)",
    "filename": "main.c",
    "lineNumber": 42,
    "method": "process_data"
  },
  "sink": {
    "node_id": "67890",
    "code": "deallocate_memory(buffer)",
    "filename": "main.c",
    "lineNumber": 58,
    "method": "process_data"
  },
  "flow_found": true,
  "flow_type": "direct_identifier_match",
  "intermediate_variable": "buffer",
  "details": {
    "assignment": "buffer = allocate_memory(100)",
    "assignment_line": 42,
    "variable_uses": 3,
    "explanation": "allocate_memory() returns value assigned to 'buffer', which is used as argument to deallocate_memory()"
  }
}
```

**Returns (with only source):**
```json
{
  "success": true,
  "source": {
    "node_id": "12345",
    "code": "allocate_memory(100)",
    "filename": "main.c",
    "lineNumber": 42,
    "method": "process_data"
  },
  "flows": [
    {
      "path_id": 0,
      "path_length": 3,
      "nodes": [
        ["allocate_memory(100)", "main.c", 42, "CALL"],
        ["buffer", "main.c", 42, "IDENTIFIER"],
        ["deallocate_memory(buffer)", "main.c", 58, "CALL"]
      ]
    }
  ],
  "total_flows": 1,
  "message": "Found 1 flows from source to dangerous sinks"
}
```

**Examples:**

Find flow from specific source to sink:
```json
{
  "tool": "find_taint_flows",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "source_location": "main.c:42",
    "sink_location": "main.c:58"
  }
}
```

Find all flows from a source:
```json
{
  "tool": "find_taint_flows",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "source_node_id": "12345"
  }
}
```

---

### `check_method_reachability`

Check if one method can reach another through the call graph.

**Description:** Determines whether the target method is reachable from the source method by following function calls. Useful for understanding code dependencies and potential execution paths.

**Parameters:**
- `session_id` (string, required): The session ID
- `source_method` (string, required): Name of the source method (can be regex pattern)
- `target_method` (string, required): Name of the target method (can be regex pattern)

**Returns:**
```json
{
  "success": true,
  "reachable": true,
  "source_method": "main",
  "target_method": "helper",
  "message": "Method 'helper' is reachable from 'main'"
}
```

**Example:**
```json
{
  "tool": "check_method_reachability",
  "arguments": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "source_method": "main",
    "target_method": "execute_command"
  }
}
```

---

### `find_argument_flows`

Find flows where the same expression is passed between source and sink calls.

**Description:** Locate cases where exact expressions are reused between function calls, useful for identifying potential propagation of unsanitized data.

**Parameters:**
- `session_id` (string, required): The session ID
- `source_name` (string, required): Name of the source function
- `sink_name` (string, required): Name of the sink function
- `arg_index` (integer, optional): Specific argument index to track (0-based)
- `limit` (integer, optional): Maximum number of flows (default: 100)

**Returns:**
```json
{
  "success": true,
  "flows": [
    {
      "flow_id": 0,
      "source_call": "validate_input(data)",
      "sink_call": "process_data(data)",
      "shared_argument": "data",
      "source_line": 42,
      "sink_line": 58,
      "method": "main"
    }
  ],
  "total": 1
}
```

---

### `list_taint_paths`

List detailed taint flow paths from sources to sinks.

**Description:** Enumerate and display detailed propagation chains from taint sources to sinks, showing all intermediate steps.

**Parameters:**
- `session_id` (string, required): The session ID
- `source_pattern` (string, optional): Regex pattern for source functions
- `sink_pattern` (string, optional): Regex pattern for sink functions
- `max_paths` (integer, optional): Maximum number of paths to return (default: 50)
- `max_path_length` (integer, optional): Maximum path length (default: 10)

**Returns:**
```json
{
  "success": true,
  "paths": [
    {
      "path_id": 0,
      "length": 3,
      "nodes": [
        {
          "type": "source",
          "function": "getenv",
          "line": 42,
          "code": "getenv(\"PATH\")"
        },
        {
          "type": "assignment",
          "variable": "path_str",
          "line": 42,
          "code": "path_str = getenv(\"PATH\")"
        },
        {
          "type": "sink",
          "function": "system",
          "line": 58,
          "code": "system(path_str)"
        }
      ]
    }
  ],
  "total_paths": 1
}
```

---

### `get_program_slice`

Build a program slice from a specific line or call.

**Description:** Extracts all code affecting a specific operation (backward slice) or affected by it (forward slice). Useful for understanding dependencies and impact analysis.

**Parameters:**
- `session_id` (string, required): The session ID
- `filename` (string, required): File containing the target
- `line_number` (integer, required): Line number of interest
- `call_name` (string, optional): Optional specific call name to slice

**Returns:**
```json
{
  "success": true,
  "slice_type": "backward",
  "root_line": 42,
  "slice_nodes": [
    {
      "type": "assignment",
      "line": 35,
      "code": "size = 100",
      "variable": "size"
    },
    {
      "type": "call",
      "line": 42,
      "code": "allocate_memory(size)",
      "method": "main"
    }
  ],
  "total_nodes": 2
}
```

---

### `get_data_dependencies`

Analyze data dependencies for a variable or expression.

**Description:** Track which variables or expressions a given variable depends on, or which variables depend on it. Useful for understanding variable flow and dependencies.

**Parameters:**
- `session_id` (string, required): The session ID
- `filename` (string, required): File containing the variable
- `line_number` (integer, required): Line number where variable appears
- `variable_name` (string, required): Name of the variable to analyze
- `direction` (string, optional): `"backward"` (what it depends on) or `"forward"` (what depends on it) - default: `"backward"`

**Returns:**
```json
{
  "success": true,
  "variable": "buffer",
  "location": "main.c:42",
  "direction": "backward",
  "dependencies": [
    {
      "variable": "size",
      "line": 35,
      "code": "size = 100",
      "type": "parameter"
    },
    {
      "variable": "ptr",
      "line": 40,
      "code": "ptr = allocate_memory(size)",
      "type": "return_value"
    }
  ],
  "total": 2
}
```

---

## Example Workflows

### Workflow 1: Security Audit of a GitHub Repository

**Goal:** Identify potential security vulnerabilities in a C project

1. **Create analysis session:**
   ```json
   {
     "tool": "create_cpg_session",
     "arguments": {
       "source_type": "github",
       "source_path": "https://github.com/user/vulnerable-app",
       "language": "c"
     }
   }
   ```
   
   → Returns `session_id: "session-123"`

2. **Get codebase overview:**
   ```json
   {
     "tool": "get_codebase_summary",
     "arguments": {
       "session_id": "session-123"
     }
   }
   ```

3. **Find taint sources (external input):**
   ```json
   {
     "tool": "find_taint_sources",
     "arguments": {
       "session_id": "session-123",
       "language": "c",
       "source_patterns": ["getenv", "fgets", "scanf", "recv"],
       "limit": 50
     }
   }
   ```

4. **Find taint sinks (dangerous functions):**
   ```json
   {
     "tool": "find_taint_sinks",
     "arguments": {
       "session_id": "session-123",
       "language": "c",
       "sink_patterns": ["system", "popen", "sprintf", "strcpy"],
       "limit": 50
     }
   }
   ```

5. **Check for flows from sources to sinks:**
   For each source found, check if it flows to a sink:
   ```json
   {
     "tool": "find_taint_flows",
     "arguments": {
       "session_id": "session-123",
       "source_location": "main.c:42",
       "sink_location": "main.c:100"
     }
   }
   ```

6. **Examine vulnerable code:**
   ```json
   {
     "tool": "get_code_snippet",
     "arguments": {
       "session_id": "session-123",
       "filename": "main.c",
       "start_line": 40,
       "end_line": 50
     }
   }
   ```

7. **Understand call chain:**
   ```json
   {
     "tool": "get_call_graph",
     "arguments": {
       "session_id": "session-123",
       "method_name": "vulnerable_function",
       "direction": "incoming",
       "depth": 3
     }
   }
   ```

---

### Workflow 2: Code Complexity Analysis

**Goal:** Find and analyze complex methods in a Java project

1. **Create session:**
   ```json
   {
     "tool": "create_cpg_session",
     "arguments": {
       "source_type": "local",
       "source_path": "/home/user/java-app",
       "language": "java"
     }
   }
   ```

2. **Find all methods:**
   ```json
   {
     "tool": "list_methods",
     "arguments": {
       "session_id": "session-456",
       "limit": 500
     }
   }
   ```

3. **Find methods with specific patterns:**
   ```json
   {
     "tool": "list_methods",
     "arguments": {
       "session_id": "session-456",
       "name_pattern": ".*process.*",
       "limit": 50
     }
   }
   ```

4. **Examine method source:**
   ```json
   {
     "tool": "get_method_source",
     "arguments": {
       "session_id": "session-456",
       "method_name": "processData"
     }
   }
   ```

5. **Analyze dependencies:**
   ```json
   {
     "tool": "get_call_graph",
     "arguments": {
       "session_id": "session-456",
       "method_name": "processData",
       "direction": "outgoing",
       "depth": 3
     }
   }
   ```

---

### Workflow 3: Hardcoded Secrets Scanning

**Goal:** Find hardcoded secrets, API keys, and credentials

1. **Create session:**
   ```json
   {
     "tool": "create_cpg_session",
     "arguments": {
       "source_type": "github",
       "source_path": "https://github.com/user/app",
       "language": "python"
     }
   }
   ```

2. **Search for potential secrets:**
   ```json
   {
     "tool": "find_literals",
     "arguments": {
       "session_id": "session-789",
       "pattern": "(?i).*(password|secret|api|token|key|credential).*",
       "limit": 200
     }
   }
   ```

3. **For each finding, get context:**
   ```json
   {
     "tool": "get_code_snippet",
     "arguments": {
       "session_id": "session-789",
       "filename": "config.py",
       "start_line": 35,
       "end_line": 45
     }
   }
   ```

4. **Understand usage of secrets:**
   ```json
   {
     "tool": "get_method_source",
     "arguments": {
       "session_id": "session-789",
       "method_name": "initialize_api"
     }
   }
   ```

---

## Advanced Topics

### Configuration

#### Environment Variables

Override configuration via environment variables (takes precedence over `config.yaml`):

```bash
export MCP_HOST=127.0.0.1
export MCP_PORT=5000
export MCP_LOG_LEVEL=DEBUG
export REDIS_HOST=redis.example.com
export REDIS_PORT=6380
export SESSION_TTL=7200
export JOERN_MEMORY_LIMIT=32g
```

#### Session Configuration

Key settings in `config.yaml`:

```yaml
sessions:
  ttl: 3600                # Session timeout (seconds)
  idle_timeout: 1800       # Inactivity timeout (seconds)
  max_concurrent: 100      # Maximum concurrent sessions

cpg:
  generation_timeout: 600  # CPG generation timeout (seconds)
  max_repo_size_mb: 500    # Maximum repository size

query:
  timeout: 300             # Query execution timeout (seconds)
  cache_enabled: true      # Enable query result caching
  cache_ttl: 300           # Cache time-to-live (seconds)
```

### Performance Optimization

#### CPG Caching Strategy

- **First session:** 2-10 minutes (CPG generated from scratch)
- **Subsequent sessions:** 10-30 seconds (CPG reused from cache)
- **Cache key:** SHA256 of (source_path + language + exclusion_patterns)
- **Cache location:** `playground/cpgs/{cache_key}/cpg.bin`

#### Query Optimization

- Use `.take(limit)` to reduce results early
- Use filters (`.where()`) before `.map()` for efficiency
- Cache query results are returned in ~10ms
- Complex queries: consider increasing `timeout` parameter

#### Resource Management

```bash
# Monitor running sessions
docker ps | grep joern

# Check disk usage
du -sh /tmp/joern-mcp
du -sh playground/cpgs

# Clean up old sessions
python main.py --cleanup-old-sessions --max-age-hours 24

# Explicit cleanup
python cleanup.py
```

### Troubleshooting

#### Session creation timeout

**Issue:** CPG generation exceeds 10 minutes

**Solution:**
1. Increase `cpg.generation_timeout` in config
2. Check codebase size: `du -sh {source_path}`
3. Consider using `source_path` exclusion patterns to reduce scope

#### Query execution timeout

**Issue:** Query returns timeout error

**Solution:**
1. Increase `timeout` parameter in query call
2. Increase `query.timeout` in config
3. Simplify query using filters and limits

#### Out of memory

**Issue:** Docker container crashes with OOM

**Solution:**
1. Increase `joern.memory_limit` in config (e.g., `"32g"`)
2. Reduce max concurrent sessions: `sessions.max_concurrent`
3. Clean up old CPGs: `rm playground/cpgs/*`

#### Redis connection errors

**Issue:** Cannot connect to Redis

**Solution:**
```bash
# Check Redis is running
docker ps | grep joern-redis

# Test Redis connection
docker exec joern-redis redis-cli ping

# Restart Redis
docker restart joern-redis
```

### Advanced Querying

#### CPGQL Syntax Examples

**Find all external calls:**
```scala
cpg.call.isExternal(true).code.l
```

**Find methods with high cyclomatic complexity:**
```scala
cpg.method.filter(_.cyclomaticComplexity > 10).name.l
```

**Find variables used before assignment:**
```scala
cpg.identifier.where(_.inAssignment.assignment.code.size == 0).name.l
```

**Find all data flows from parameter to sink:**
```scala
cpg.method.parameter.name("input")
  .reachableByFlows(cpg.call.name("system"))
  .l
```

### Custom Tool Development

To add custom tools, implement them in `src/tools/custom_tools.py`:

```python
@mcp.tool()
async def my_custom_tool(session_id: str, param: str) -> Dict[str, Any]:
    """
    My custom analysis tool.
    
    Args:
        session_id: The session ID
        param: Custom parameter
    
    Returns:
        Tool result
    """
    session_manager = services["session_manager"]
    query_executor = services["query_executor"]
    
    session = await session_manager.get_session(session_id)
    if not session:
        raise SessionNotFoundError(f"Session {session_id} not found")
    
    # Your custom logic here
    result = await query_executor.execute_query(...)
    
    return {"success": True, "result": result}
```

Register the tool in `src/tools/mcp_tools.py`:

```python
from .custom_tools import register_custom_tools

def register_tools(mcp, services):
    # ... existing registrations
    register_custom_tools(mcp, services)
```

---

## API Reference Summary

### Session Management
| Tool | Purpose |
|------|---------|
| `create_cpg_session` | Create new analysis session |
| `get_session_status` | Check session status |
| `list_sessions` | List active sessions |
| `close_session` | Close and cleanup session |
| `cleanup_all_sessions` | Cleanup multiple sessions |

### Query Execution
| Tool | Purpose |
|------|---------|
| `run_cpgql_query` | Execute synchronous query |
| `run_cpgql_query_async` | Execute asynchronous query |
| `get_query_status` | Check async query status |
| `get_query_result` | Get async query results |
| `cleanup_queries` | Clean old query results |

### Code Browsing
| Tool | Purpose |
|------|---------|
| `list_methods` | List methods in codebase |
| `get_method_source` | Get method source code |
| `list_calls` | List function calls |
| `get_call_graph` | Build call graph |
| `list_parameters` | Get method parameters |
| `find_literals` | Find hardcoded values |
| `get_code_snippet` | Extract code by lines |
| `get_codebase_summary` | Get codebase statistics |
| `list_files` | List source files |
| `find_bounds_checks` | Detect buffer checks |

### Security Analysis
| Tool | Purpose |
|------|---------|
| `find_taint_sources` | Find external inputs |
| `find_taint_sinks` | Find dangerous functions |
| `find_taint_flows` | Trace data flows |
| `find_argument_flows` | Find expression reuse |
| `check_method_reachability` | Check call graph paths |
| `list_taint_paths` | List detailed flows |
| `get_program_slice` | Extract program slice |
| `get_data_dependencies` | Analyze dependencies |

---

## Support & Resources

- **Documentation:** [README.md](README.md), [ARCHITECTURE.md](ARCHITECTURE.md)
- **Examples:** See `examples/` directory for sample usage
- **Issue Tracking:** GitHub Issues
- **Joern Documentation:** https://joern.io/docs/
