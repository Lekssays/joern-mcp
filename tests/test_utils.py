"""Tests for utility functions."""

import pytest
import sys
from pathlib import Path

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils import detect_project_language, calculate_loc


def test_detect_c_language(sample_c_project):
    """Test detection of C language"""
    languages = detect_project_language(sample_c_project)
    assert "c" in languages


def test_detect_python_language(sample_python_project):
    """Test detection of Python language"""
    languages = detect_project_language(sample_python_project)
    assert "python" in languages


def test_detect_unknown_language(temp_dir):
    """Test detection when no known languages are present"""
    # Create a file with unknown extension
    unknown_file = temp_dir / "test.xyz"
    unknown_file.write_text("some content")
    
    languages = detect_project_language(temp_dir)
    assert languages == ["unknown"]


def test_calculate_loc_c_project(sample_c_project):
    """Test LOC calculation for C project"""
    languages = ["c"]
    loc = calculate_loc(sample_c_project, languages)
    assert loc > 0  # Should count non-empty lines
    assert loc < 20  # Simple project should have reasonable LOC


def test_calculate_loc_python_project(sample_python_project):
    """Test LOC calculation for Python project"""
    languages = ["python"]
    loc = calculate_loc(sample_python_project, languages)
    assert loc > 0
    assert loc < 15


def test_calculate_loc_empty_project(temp_dir):
    """Test LOC calculation for empty project"""
    languages = ["c"]
    loc = calculate_loc(temp_dir, languages)
    assert loc == 0


def test_calculate_loc_unsupported_language(sample_c_project):
    """Test LOC calculation with unsupported language"""
    languages = ["unsupported"]
    loc = calculate_loc(sample_c_project, languages)
    assert loc == 0  # Should not count files for unsupported languages