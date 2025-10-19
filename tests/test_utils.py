"""
Tests for utility functions
"""

import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the utils.py file directly
utils_spec = importlib.util.spec_from_file_location(
    "utils", Path(__file__).parent.parent / "src" / "utils.py"
)
utils_module = importlib.util.module_from_spec(utils_spec)
sys.modules["utils"] = utils_module
utils_spec.loader.exec_module(utils_module)

detect_project_language = utils_module.detect_project_language
calculate_loc = utils_module.calculate_loc


class TestDetectProjectLanguage:
    """Test project language detection"""

    def test_detect_python_project(self):
        """Test detecting Python project"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create Python files
            Path(tmpdir, "main.py").touch()
            Path(tmpdir, "utils.py").touch()
            Path(tmpdir, "requirements.txt").touch()

            languages = detect_project_language(Path(tmpdir))
            assert "python" in languages

    def test_detect_java_project(self):
        """Test detecting Java project"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create Java files
            Path(tmpdir, "Main.java").touch()
            Path(tmpdir, "Utils.java").touch()
            Path(tmpdir, "pom.xml").touch()

            languages = detect_project_language(Path(tmpdir))
            assert "java" in languages

    def test_detect_javascript_project(self):
        """Test detecting JavaScript project"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create JS files
            Path(tmpdir, "app.js").touch()
            Path(tmpdir, "package.json").touch()

            languages = detect_project_language(Path(tmpdir))
            assert "javascript" in languages

    def test_detect_c_project(self):
        """Test detecting C project"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create C files
            Path(tmpdir, "main.c").touch()
            Path(tmpdir, "utils.h").touch()

            languages = detect_project_language(Path(tmpdir))
            assert "c" in languages

    def test_detect_cpp_project(self):
        """Test detecting C++ project"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create C++ files
            Path(tmpdir, "main.cpp").touch()
            Path(tmpdir, "utils.hpp").touch()

            languages = detect_project_language(Path(tmpdir))
            assert "cpp" in languages

    def test_detect_go_project(self):
        """Test detecting Go project"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create Go files
            Path(tmpdir, "main.go").touch()
            Path(tmpdir, "go.mod").touch()

            languages = detect_project_language(Path(tmpdir))
            assert "go" in languages

    def test_detect_kotlin_project(self):
        """Test detecting Kotlin project"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create Kotlin files
            Path(tmpdir, "Main.kt").touch()
            Path(tmpdir, "Utils.kts").touch()

            languages = detect_project_language(Path(tmpdir))
            assert "kotlin" in languages

    def test_detect_csharp_project(self):
        """Test detecting C# project"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create C# files
            Path(tmpdir, "Program.cs").touch()
            Path(tmpdir, "Utils.cs").touch()

            languages = detect_project_language(Path(tmpdir))
            assert "csharp" in languages

    def test_detect_multiple_languages(self):
        """Test detecting multiple languages in one project"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create files for multiple languages
            Path(tmpdir, "main.py").touch()
            Path(tmpdir, "Main.java").touch()
            Path(tmpdir, "app.js").touch()

            languages = detect_project_language(Path(tmpdir))
            assert "python" in languages
            assert "java" in languages
            assert "javascript" in languages

    def test_detect_unknown_language(self):
        """Test detecting unknown language (no recognized files)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create unrecognized files
            Path(tmpdir, "README.md").touch()
            Path(tmpdir, "Dockerfile").touch()

            languages = detect_project_language(Path(tmpdir))
            assert languages == ["unknown"]

    def test_detect_empty_directory(self):
        """Test detecting language in empty directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            languages = detect_project_language(Path(tmpdir))
            assert languages == ["unknown"]

    def test_detect_nested_files(self):
        """Test detecting languages in nested directories"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure
            src_dir = Path(tmpdir, "src")
            src_dir.mkdir()
            Path(src_dir, "main.py").touch()
            Path(src_dir, "utils.py").touch()

            test_dir = Path(tmpdir, "tests")
            test_dir.mkdir()
            Path(test_dir, "test_main.py").touch()

            languages = detect_project_language(Path(tmpdir))
            assert "python" in languages


class TestCalculateLoc:
    """Test lines of code calculation"""

    def test_calculate_loc_python(self):
        """Test LOC calculation for Python files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create Python files with known line counts
            py_file = Path(tmpdir, "test.py")
            py_file.write_text(
                """# Comment line
import os
import sys

def hello():
    print("Hello World")
    return True

if __name__ == "__main__":
    hello()
"""
            )

            loc = calculate_loc(Path(tmpdir), ["python"])
            assert loc == 8  # Count of non-empty lines

    def test_calculate_loc_java(self):
        """Test LOC calculation for Java files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create Java file
            java_file = Path(tmpdir, "Test.java")
            java_file.write_text(
                """public class Test {
    public static void main(String[] args) {
        System.out.println("Hello World");
    }
}
"""
            )

            loc = calculate_loc(Path(tmpdir), ["java"])
            assert loc == 5

    def test_calculate_loc_multiple_files(self):
        """Test LOC calculation across multiple files"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create multiple Python files
            file1 = Path(tmpdir, "file1.py")
            file1.write_text("print('hello')\nprint('world')\n")

            file2 = Path(tmpdir, "file2.py")
            file2.write_text("def test():\n    return True\n")

            loc = calculate_loc(Path(tmpdir), ["python"])
            assert loc == 4

    def test_calculate_loc_mixed_languages(self):
        """Test LOC calculation with multiple languages"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create Python file
            py_file = Path(tmpdir, "main.py")
            py_file.write_text("print('python')\n")

            # Create Java file
            java_file = Path(tmpdir, "Main.java")
            java_file.write_text("System.out.println('java');\n")

            # Calculate for Python only
            loc_python = calculate_loc(Path(tmpdir), ["python"])
            assert loc_python == 1

            # Calculate for Java only
            loc_java = calculate_loc(Path(tmpdir), ["java"])
            assert loc_java == 1

            # Calculate for both
            loc_both = calculate_loc(Path(tmpdir), ["python", "java"])
            assert loc_both == 2

    def test_calculate_loc_empty_file(self):
        """Test LOC calculation for empty file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_file = Path(tmpdir, "empty.py")
            empty_file.touch()

            loc = calculate_loc(Path(tmpdir), ["python"])
            assert loc == 0

    def test_calculate_loc_whitespace_only(self):
        """Test LOC calculation for whitespace-only file"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ws_file = Path(tmpdir, "whitespace.py")
            ws_file.write_text("   \n\t\n  \n")

            loc = calculate_loc(Path(tmpdir), ["python"])
            assert loc == 0

    def test_calculate_loc_binary_file_ignored(self):
        """Test that binary/unreadable files are ignored"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a text file
            text_file = Path(tmpdir, "test.py")
            text_file.write_text("print('hello')\n")

            # Create a "binary" file (we'll just make it unreadable)
            binary_file = Path(tmpdir, "binary.py")
            binary_file.write_text("print('hello')\n")
            binary_file.chmod(0o000)  # Remove read permissions

            try:
                loc = calculate_loc(Path(tmpdir), ["python"])
                # Should still count the readable file
                assert loc == 1
            finally:
                binary_file.chmod(0o644)  # Restore permissions for cleanup

    def test_calculate_loc_no_matching_files(self):
        """Test LOC calculation when no files match the language"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create Python file
            py_file = Path(tmpdir, "test.py")
            py_file.write_text("print('hello')\n")

            # Calculate for Java (no Java files)
            loc = calculate_loc(Path(tmpdir), ["java"])
            assert loc == 0

    def test_calculate_loc_unknown_language(self):
        """Test LOC calculation for unknown language"""
        with tempfile.TemporaryDirectory() as tmpdir:
            py_file = Path(tmpdir, "test.py")
            py_file.write_text("print('hello')\n")

            loc = calculate_loc(Path(tmpdir), ["unknown"])
            assert loc == 0
