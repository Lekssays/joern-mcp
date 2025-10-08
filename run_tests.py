#!/usr/bin/env python3
"""
Test runner for Joern MCP
"""
import sys
import subprocess
from pathlib import Path

def run_tests():
    """Run the test suite"""
    project_root = Path(__file__).parent

    # Ensure we're in the project root
    if not (project_root / "pyproject.toml").exists():
        print("Error: Must run from project root directory")
        sys.exit(1)

    # Run pytest
    cmd = [sys.executable, "-m", "pytest", "tests/"]
    result = subprocess.run(cmd, cwd=project_root)

    sys.exit(result.returncode)

if __name__ == "__main__":
    run_tests()