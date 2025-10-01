#!/usr/bin/env python3
"""
Validation script for Joern MCP Server setup.

This script checks that all prerequisites are properly configured.
"""

import subprocess
import sys
from pathlib import Path

def check_python():
    """Check Python version"""
    version = sys.version_info
    if version.major >= 3 and version.minor >= 8:
        print(f"✅ Python {version.major}.{version.minor}.{version.micro}")
        return True
    else:
        print(f"❌ Python {version.major}.{version.minor}.{version.micro} (requires 3.8+)")
        return False

def check_docker():
    """Check Docker availability"""
    try:
        result = subprocess.run(['docker', '--version'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print(f"✅ Docker: {result.stdout.strip()}")
            return True
        else:
            print("❌ Docker not found or not working")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("❌ Docker not found or not responding")
        return False

def check_docker_running():
    """Check if Docker daemon is running"""
    try:
        result = subprocess.run(['docker', 'info'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("✅ Docker daemon is running")
            return True
        else:
            print("❌ Docker daemon is not running")
            return False
    except subprocess.TimeoutExpired:
        print("❌ Docker daemon not responding")
        return False

def check_joern_image():
    """Check if Joern Docker image exists"""
    try:
        result = subprocess.run(['docker', 'images', 'joern:latest', '--format', '{{.Repository}}:{{.Tag}}'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and 'joern:latest' in result.stdout:
            print("✅ Joern Docker image (joern:latest) found")
            return True
        else:
            print("❌ Joern Docker image not found")
            print("   Run: ./build.sh or docker build -t joern:latest .")
            return False
    except subprocess.TimeoutExpired:
        print("❌ Docker not responding when checking images")
        return False

def check_dependencies():
    """Check if Python dependencies are available"""
    required_modules = ['docker', 'git', 'pydantic', 'mcp', 'yaml']
    missing = []
    
    for module in required_modules:
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    
    if not missing:
        print("✅ All Python dependencies available")
        return True
    else:
        print(f"❌ Missing Python dependencies: {', '.join(missing)}")
        print("   Run: pip install -r requirements.txt")
        return False

def check_project_structure():
    """Check if project structure is correct"""
    required_files = [
        'main.py',
        'src/__init__.py',
        'src/server.py',
        'src/models.py',
        'src/config.py',
        'src/utils.py',
        'requirements.txt',
        'Dockerfile',
        'build.sh'
    ]
    
    missing = []
    for file_path in required_files:
        if not Path(file_path).exists():
            missing.append(file_path)
    
    if not missing:
        print("✅ Project structure is complete")
        return True
    else:
        print(f"❌ Missing files: {', '.join(missing)}")
        return False

def main():
    """Run all validation checks"""
    print("🔍 Validating Joern MCP Server setup...\n")
    
    checks = [
        ("Python version", check_python),
        ("Docker availability", check_docker),
        ("Docker daemon", check_docker_running),
        ("Python dependencies", check_dependencies),
        ("Project structure", check_project_structure),
        ("Joern Docker image", check_joern_image),
    ]
    
    passed = 0
    total = len(checks)
    
    for name, check_func in checks:
        print(f"Checking {name}...")
        if check_func():
            passed += 1
        print()
    
    print(f"📊 Validation Results: {passed}/{total} checks passed")
    
    if passed == total:
        print("🎉 All checks passed! Joern MCP Server is ready to run.")
        print("   Start with: python main.py")
        return 0
    else:
        print("❌ Some checks failed. Please fix the issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())