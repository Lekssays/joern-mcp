"""Test configuration and fixtures for Joern MCP Server tests."""

import pytest
import tempfile
import shutil
import sys
from pathlib import Path

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import ServerConfig, DockerConfig, CacheConfig
from src.server import JoernMCPServer


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing"""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def test_config(temp_dir):
    """Create a test configuration"""
    return ServerConfig(
        docker=DockerConfig(
            image="joern:latest",
            timeout=60,
            memory_limit="2g"
        ),
        cache=CacheConfig(
            enabled=True,
            directory=str(temp_dir / "cache"),
            ttl_hours=1
        ),
        log_level="DEBUG"
    )


@pytest.fixture
def server(test_config):
    """Create a test server instance"""
    return JoernMCPServer(test_config)


@pytest.fixture
def sample_c_project(temp_dir):
    """Create a sample C project for testing"""
    project_dir = temp_dir / "sample_c"
    project_dir.mkdir()
    
    # Create a simple C file
    c_file = project_dir / "main.c"
    c_file.write_text("""
#include <stdio.h>
#include <stdlib.h>

int add(int a, int b) {
    return a + b;
}

int main() {
    int x = 5;
    int y = 10;
    int result = add(x, y);
    printf("Result: %d\\n", result);
    return 0;
}
""")
    
    return project_dir


@pytest.fixture
def sample_python_project(temp_dir):
    """Create a sample Python project for testing"""
    project_dir = temp_dir / "sample_python"
    project_dir.mkdir()
    
    # Create a simple Python file
    py_file = project_dir / "main.py"
    py_file.write_text("""
def add(a, b):
    return a + b

def main():
    x = 5
    y = 10
    result = add(x, y)
    print(f"Result: {result}")

if __name__ == "__main__":
    main()
""")
    
    # Create requirements.txt
    req_file = project_dir / "requirements.txt"
    req_file.write_text("pytest==7.0.0\n")
    
    return project_dir