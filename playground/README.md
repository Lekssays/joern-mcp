# Joern MCP Playground

This directory is mounted to Joern Docker containers at `/playground`, providing a shared workspace for codebases and CPGs.

## Directory Structure

```
playground/
├── codebases/          # Source code to analyze
│   └── sample/         # Example C codebase
│       └── sample.c
└── cpgs/              # Generated Code Property Graphs (optional)
```

## Usage

### For Local Codebases

When creating a CPG session with `source_type="local"`, provide paths relative to or within `playground/codebases/`:

```python
# Example: Analyze the sample codebase
create_cpg_session(
    source_type="local",
    source_path="playground/codebases/sample",  # Or absolute path
    language="c"
)
```

The Joern container will access this at `/playground/codebases/sample`.

### For GitHub Repositories

When using `source_type="github"`, repositories are automatically cloned into `playground/codebases/{session_id}/`:

```python
create_cpg_session(
    source_type="github",
    source_path="https://github.com/user/repo",
    language="java"
)
```

### CPG Storage

CPGs are stored in the session workspace (`/tmp/joern-mcp/repos/{session_id}/cpg.bin`), but you can optionally store them in `playground/cpgs/` for persistence.

## Benefits

1. **Shared Access**: All Joern containers can access the same codebases
2. **Persistence**: Codebases survive container restarts
3. **Easy Management**: Add/remove codebases without rebuilding containers
4. **Testing**: Perfect for testing with multiple sample projects

## Adding New Codebases

Simply create a new directory under `playground/codebases/`:

```bash
mkdir -p playground/codebases/my-project
cp -r /path/to/source/* playground/codebases/my-project/
```

Then analyze it:

```python
create_cpg_session(
    source_type="local",
    source_path="playground/codebases/my-project",
    language="java"
)
```
