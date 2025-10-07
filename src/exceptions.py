"""
Custom exceptions for Joern MCP Server
"""


class JoernMCPError(Exception):
    """Base exception for Joern MCP"""
    pass


class SessionNotFoundError(JoernMCPError):
    """Session does not exist"""
    pass


class SessionNotReadyError(JoernMCPError):
    """Session is not in ready state"""
    pass


class CPGGenerationError(JoernMCPError):
    """CPG generation failed"""
    pass


class QueryExecutionError(JoernMCPError):
    """Query execution failed"""
    pass


class DockerError(JoernMCPError):
    """Docker operation failed"""
    pass


class ResourceLimitError(JoernMCPError):
    """Resource limit exceeded"""
    pass


class ValidationError(JoernMCPError):
    """Input validation failed"""
    pass


class GitOperationError(JoernMCPError):
    """Git operation failed"""
    pass
