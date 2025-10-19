"""
Tests for custom exceptions
"""

import pytest

from src.exceptions import (
    CPGGenerationError,
    DockerError,
    GitOperationError,
    JoernMCPError,
    QueryExecutionError,
    ResourceLimitError,
    SessionNotFoundError,
    SessionNotReadyError,
    ValidationError,
)


class TestExceptions:
    """Test custom exception classes"""

    def test_base_exception(self):
        """Test base JoernMCPError"""
        error = JoernMCPError("Test error")
        assert str(error) == "Test error"
        assert isinstance(error, Exception)

    def test_session_not_found_error(self):
        """Test SessionNotFoundError"""
        error = SessionNotFoundError("Session 123 not found")
        assert str(error) == "Session 123 not found"
        assert isinstance(error, JoernMCPError)

    def test_session_not_ready_error(self):
        """Test SessionNotReadyError"""
        error = SessionNotReadyError("Session not ready")
        assert str(error) == "Session not ready"
        assert isinstance(error, JoernMCPError)

    def test_cpg_generation_error(self):
        """Test CPGGenerationError"""
        error = CPGGenerationError("CPG generation failed")
        assert str(error) == "CPG generation failed"
        assert isinstance(error, JoernMCPError)

    def test_query_execution_error(self):
        """Test QueryExecutionError"""
        error = QueryExecutionError("Query execution failed")
        assert str(error) == "Query execution failed"
        assert isinstance(error, JoernMCPError)

    def test_docker_error(self):
        """Test DockerError"""
        error = DockerError("Docker operation failed")
        assert str(error) == "Docker operation failed"
        assert isinstance(error, JoernMCPError)

    def test_resource_limit_error(self):
        """Test ResourceLimitError"""
        error = ResourceLimitError("Resource limit exceeded")
        assert str(error) == "Resource limit exceeded"
        assert isinstance(error, JoernMCPError)

    def test_validation_error(self):
        """Test ValidationError"""
        error = ValidationError("Invalid input")
        assert str(error) == "Invalid input"
        assert isinstance(error, JoernMCPError)

    def test_git_operation_error(self):
        """Test GitOperationError"""
        error = GitOperationError("Git operation failed")
        assert str(error) == "Git operation failed"
        assert isinstance(error, JoernMCPError)

    def test_exception_hierarchy(self):
        """Test that all exceptions inherit from JoernMCPError"""
        exceptions = [
            SessionNotFoundError("test"),
            SessionNotReadyError("test"),
            CPGGenerationError("test"),
            QueryExecutionError("test"),
            DockerError("test"),
            ResourceLimitError("test"),
            ValidationError("test"),
            GitOperationError("test"),
        ]

        for exc in exceptions:
            assert isinstance(exc, JoernMCPError)
            assert isinstance(exc, Exception)

    def test_exception_with_custom_message(self):
        """Test exceptions with custom messages"""
        test_cases = [
            (SessionNotFoundError, "Session abc-123 not found"),
            (SessionNotReadyError, "Session is still generating"),
            (CPGGenerationError, "Failed to generate CPG for Java project"),
            (QueryExecutionError, "Invalid CPGQL syntax"),
            (DockerError, "Cannot connect to Docker daemon"),
            (ResourceLimitError, "Maximum concurrent sessions reached"),
            (ValidationError, "Unsupported language: rust"),
            (GitOperationError, "Repository not found"),
        ]

        for exc_class, message in test_cases:
            error = exc_class(message)
            assert str(error) == message
