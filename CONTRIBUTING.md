# Contributing to joern-mcp

Thank you for your interest in contributing to joern-mcp! This document provides guidelines and instructions for contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Code Quality](#code-quality)
- [Submitting Changes](#submitting-changes)
- [Reporting Issues](#reporting-issues)
- [Documentation](#documentation)

## Code of Conduct

We are committed to providing a welcoming and inspiring community for all. Please read and adhere to our principles:

- Be respectful and inclusive
- Welcome diverse perspectives and experiences
- Focus on constructive feedback
- Report unacceptable behavior to the maintainers

## Getting Started

### Prerequisites

Before you begin, ensure you have:

- Python 3.8+
- Docker and Docker Compose
- Git
- Redis (or Docker for Redis)
- A GitHub account

### Fork and Clone

1. **Fork the repository** on GitHub
2. **Clone your fork**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/joern-mcp.git
   cd joern-mcp
   ```
3. **Add upstream remote** (to stay synced):
   ```bash
   git remote add upstream https://github.com/Lekssays/joern-mcp.git
   ```

## Development Setup

### 1. Create a Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Setup Services

```bash
./setup.sh
```

This will:
- Build the Joern Docker image
- Start Redis container
- Initialize the playground directory

### 4. Verify Setup

```bash
# Test that server starts
python main.py
```

## Making Changes

### Branch Strategy

1. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Branch naming conventions**:
   - `feature/` - New feature
   - `bugfix/` - Bug fix
   - `docs/` - Documentation changes
   - `test/` - Test improvements
   - `refactor/` - Code refactoring

3. **Keep your branch updated**:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

### Commit Messages

Follow these guidelines for commit messages:

```
<type>: <subject>

<body>

<footer>
```

**Format**:
- `<type>`: feat, fix, docs, test, refactor, perf, style
- `<subject>`: Clear, concise description (50 chars max)
- `<body>`: Detailed explanation of changes (optional, 72 chars per line)
- `<footer>`: References to issues (Fixes #123)

**Example**:
```
feat: add support for data dependency analysis

- Implement backward and forward slicing
- Add get_data_dependencies tool
- Add comprehensive tests for dependency tracking

Fixes #42
```

### Code Style

#### Python Style Guide

We follow [PEP 8](https://www.python.org/dev/peps/pep-0008/) with these tools:

**Format with Black**:
```bash
black src/ tests/ examples/
```

**Organize imports with isort**:
```bash
isort src/ tests/ examples/
```

**Type hints**:
```python
from typing import Dict, List, Optional
from dataclasses import dataclass

async def process_data(
    session_id: str,
    data: Dict[str, str],
    limit: Optional[int] = None
) -> List[Dict[str, str]]:
    """Process data with optional limit."""
    pass

@dataclass
class Result:
    success: bool
    error: Optional[str] = None
```

#### Docstring Format

Use Google-style docstrings:

```python
async def complex_analysis(
    session_id: str,
    query: str,
    timeout: int = 30
) -> Dict[str, Any]:
    """Perform complex code analysis.
    
    Execute a CPGQL query and return structured results.
    
    Args:
        session_id: The analysis session ID from create_cpg_session
        query: CPGQL query string (Scala-based DSL for Joern)
        timeout: Maximum execution time in seconds (default: 30)
    
    Returns:
        Dictionary containing:
            - success (bool): Whether query executed successfully
            - data (List[Dict]): Query results as list of records
            - error (Optional[str]): Error message if failed
            - execution_time (float): Query execution time in seconds
    
    Raises:
        SessionNotFoundError: If session_id doesn't exist
        QueryExecutionError: If query execution fails
        TimeoutError: If query exceeds timeout
    
    Example:
        result = await complex_analysis(
            session_id="abc-123",
            query="cpg.method.name.l"
        )
        print(result['data'])
    """
    pass
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_mcp_tools.py

# Run specific test
pytest tests/test_mcp_tools.py::test_create_session

# Run with coverage
pytest --cov=src --cov-report=html

# Run with verbose output
pytest -v
```

### Writing Tests

```python
import pytest
from src.services.session_manager import SessionManager
from src.exceptions import SessionNotFoundError

@pytest.fixture
async def session_manager():
    """Fixture providing a SessionManager instance."""
    manager = SessionManager()
    yield manager
    await manager.cleanup()

@pytest.mark.asyncio
async def test_create_session(session_manager):
    """Test session creation with valid parameters."""
    session = await session_manager.create_session(
        source_type="local",
        source_path="/tmp/test",
        language="python"
    )
    
    assert session.id is not None
    assert session.status == "CREATING"
    assert session.language == "python"

@pytest.mark.asyncio
async def test_session_not_found(session_manager):
    """Test that SessionNotFoundError is raised for invalid session."""
    with pytest.raises(SessionNotFoundError):
        await session_manager.get_session("invalid-id")
```

### Test Coverage

Maintain test coverage above 80%:

```bash
pytest --cov=src --cov-report=term-missing
```

## Code Quality

### Linting

```bash
# Lint with flake8
flake8 src/ tests/ examples/

# Check complexity
flake8 src/ --max-complexity=10
```

### Type Checking

```bash
# Type check with mypy
mypy src/
```

### Pre-commit Checks

Create `.git/hooks/pre-commit`:

```bash
#!/bin/bash
set -e

echo "Running pre-commit checks..."

# Format
echo "Formatting with black..."
black src/ tests/

# Organize imports
echo "Organizing imports with isort..."
isort src/ tests/

# Lint
echo "Linting with flake8..."
flake8 src/ tests/

# Type check
echo "Type checking with mypy..."
mypy src/

# Tests
echo "Running tests..."
pytest tests/ --tb=short

echo "All checks passed!"
```

Make it executable:
```bash
chmod +x .git/hooks/pre-commit
```

## Submitting Changes

### Before You Submit

1. **Update your branch**:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Run all checks**:
   ```bash
   black src/ tests/
   isort src/ tests/
   flake8 src/ tests/
   mypy src/
   pytest --cov=src
   ```

3. **Update documentation**:
   - Update README.md if behavior changes
   - Update DOCS.md for new features
   - Add docstrings to all new functions
   - Update ARCHITECTURE.md if architecture changes

### Pull Request Process

1. **Create Pull Request** on GitHub with:
   - Clear title describing the change
   - Description of what was changed and why
   - Reference to related issues (Fixes #123)
   - Link to relevant documentation

2. **PR Template**:
   ```markdown
   ## Description
   Brief description of changes
   
   ## Type of Change
   - [ ] Bug fix
   - [ ] New feature
   - [ ] Documentation update
   - [ ] Code refactoring
   
   ## Related Issues
   Fixes #123
   
   ## Testing
   - [ ] Unit tests added/updated
   - [ ] Integration tests added/updated
   - [ ] Manual testing performed
   
   ## Checklist
   - [ ] Code follows style guidelines
   - [ ] Documentation updated
   - [ ] Tests pass locally
   - [ ] No breaking changes
   ```

3. **PR Review Process**:
   - Maintainers will review within 48 hours
   - Address feedback and push updates
   - Request re-review when ready
   - PR must pass CI/CD checks before merge

## Reporting Issues

### Issue Types

1. **Bug Report**: Something isn't working
2. **Feature Request**: Suggest a new feature
3. **Documentation**: Documentation improvements
4. **Performance**: Performance optimization

### Creating an Issue

Include:

1. **Clear title**: What's the issue?
2. **Description**: What's happening?
3. **Steps to reproduce** (for bugs):
   - Environment (OS, Python version)
   - Exact steps to reproduce
   - Expected vs actual behavior
4. **Error output**:
   - Full error message
   - Stack trace
   - Relevant logs
5. **Environment**:
   - OS and version
   - Python version
   - Docker version (if relevant)
   - Relevant dependencies versions

**Example Bug Report**:
```markdown
## Bug: Session creation fails with large repositories

### Description
When creating a CPG session for a large repository (>500MB), 
the session creation times out.

### Steps to Reproduce
1. Clone a large repository (e.g., Linux kernel)
2. Call create_cpg_session with language="c"
3. Wait for CPG generation

### Expected Behavior
CPG generation completes within the timeout period

### Actual Behavior
CPG generation times out after 600 seconds

### Environment
- OS: Ubuntu 22.04
- Python: 3.10
- Docker: 24.0
- Repository: https://github.com/torvalds/linux (main branch)

### Error Output
```
TimeoutError: CPG generation exceeded timeout of 600s
```
```

## Documentation

### Adding Documentation

1. **README.md**: User-facing documentation
   - Feature overviews
   - Quick start guide
   - Configuration options

2. **DOCS.md**: Comprehensive feature documentation
   - Tool descriptions
   - Parameter specifications
   - Usage examples
   - Workflows

3. **ARCHITECTURE.md**: Technical documentation
   - System design
   - Component interactions
   - Data flows
   - Extension points

4. **Code comments**: Inline documentation
   - Complex logic
   - Design decisions
   - Workarounds

### Documentation Standards

- Clear and concise language
- Code examples for features
- Link to relevant sections
- Keep examples up-to-date
- Document breaking changes

## Area-Specific Guidelines

### Adding a New Tool

1. **Implement tool function** in appropriate file:
   - `core_tools.py` for core functionality
   - `code_browsing_tools.py` for code analysis
   - `taint_analysis_tools.py` for security analysis

2. **Add tests** in `tests/test_*.py`

3. **Document** in DOCS.md:
   - Tool purpose
   - Parameters
   - Return format
   - Usage example

4. **Update** ARCHITECTURE.md if needed

**Example**:
```python
# src/tools/core_tools.py

@mcp.tool()
async def my_new_tool(session_id: str, param1: str) -> Dict[str, Any]:
    """One-line description.
    
    Detailed description of what the tool does.
    
    Args:
        session_id: The session ID
        param1: Description of param1
    
    Returns:
        Dictionary with results
    
    Raises:
        SessionNotFoundError: If session doesn't exist
    """
    session = await session_manager.get_session(session_id)
    if not session:
        raise SessionNotFoundError(f"Session {session_id} not found")
    
    # Implementation
    result = await query_executor.execute_query(...)
    
    return {"success": True, "data": result}
```

### Improving Performance

1. **Profile before optimizing**:
   ```bash
   python -m cProfile -s cumulative main.py
   ```

2. **Use async appropriately**: I/O operations should be async

3. **Cache results**: Use Redis for repeated queries

4. **Document improvements** in commit message

### Fixing Security Issues

1. **Do not create public issues** for security bugs
2. **Email security@example.com** with details
3. **Include**:
   - Description of vulnerability
   - Steps to reproduce
   - Potential impact
4. **Allow 90 days** before public disclosure
5. **Credit** will be given in security advisory

## Community and Support

- **GitHub Issues**: Questions and bug reports
- **GitHub Discussions**: Feature discussions
- **GitHub Wiki**: Community tips and tricks
- **Email**: For security issues only

## Recognition

Contributors will be recognized in:
- CHANGELOG.md (with each release)
- GitHub contributors page
- Project website (coming soon)

## License

By contributing to joern-mcp, you agree that your contributions will be licensed under the same license as the project.

---

## Quick Reference

### Common Commands

```bash
# Setup development environment
git clone https://github.com/YOUR_USERNAME/joern-mcp.git
cd joern-mcp
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
./setup.sh

# Create feature branch
git checkout -b feature/my-feature

# Format and lint
black src/ tests/
isort src/ tests/
flake8 src/ tests/

# Run tests
pytest
pytest --cov=src

# Type checking
mypy src/

# Update from upstream
git fetch upstream
git rebase upstream/main

# Push and create PR
git push origin feature/my-feature
# Create PR on GitHub
```

### Getting Help

- **Issues**: Check existing issues first
- **Discussions**: Ask questions in GitHub Discussions
- **Documentation**: Read README.md and DOCS.md
- **Examples**: Check `examples/` directory
- **Tests**: Review `tests/` for usage patterns

Thank you for contributing to joern-mcp! 🙏
