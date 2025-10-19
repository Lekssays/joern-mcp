"""
Input validation utilities
"""

import hashlib
import re
from typing import Optional
from urllib.parse import urlparse

from ..exceptions import ValidationError
from ..models import SourceType


def validate_source_type(source_type: str):
    """Validate source type"""
    valid_types = [e.value for e in SourceType]
    if source_type not in valid_types:
        raise ValidationError(
            f"Invalid source_type '{source_type}'. Must be one of: {
                ', '.join(valid_types)}"
        )


def validate_language(language: str):
    """Validate programming language"""
    supported = [
        "java",
        "c",
        "cpp",
        "javascript",
        "python",
        "go",
        "kotlin",
        "csharp",
        "ghidra",
        "jimple",
        "php",
        "ruby",
        "swift",
    ]
    if language not in supported:
        raise ValidationError(
            f"Unsupported language '{language}'. Supported: {', '.join(supported)}"
        )


def validate_session_id(session_id: str):
    """Validate session ID format"""
    if not session_id or not isinstance(session_id, str):
        raise ValidationError("session_id must be a non-empty string")

    # UUID pattern
    uuid_pattern = r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"
    if not re.match(uuid_pattern, session_id):
        raise ValidationError("session_id must be a valid UUID")


def validate_github_url(url: str) -> bool:
    """Validate GitHub URL format"""
    try:
        parsed = urlparse(url)
        if parsed.netloc not in ["github.com", "www.github.com"]:
            raise ValidationError("Only GitHub URLs are supported")

        # Check for valid path format: /owner/repo
        parts = parsed.path.strip("/").split("/")
        if len(parts) < 2:
            raise ValidationError(
                "Invalid GitHub URL format. Expected: https://github.com/owner/repo"
            )

        return True
    except Exception as e:
        raise ValidationError(f"Invalid GitHub URL: {str(e)}")


def validate_local_path(path: str) -> bool:
    """Validate local file path"""
    import os

    if not os.path.isabs(path):
        raise ValidationError("Local path must be absolute")

    if not os.path.exists(path):
        raise ValidationError(f"Path does not exist: {path}")

    if not os.path.isdir(path):
        raise ValidationError(f"Path is not a directory: {path}")

    return True


def validate_cpgql_query(query: str):
    """Validate CPGQL query"""
    if not query or not isinstance(query, str):
        raise ValidationError("Query must be a non-empty string")

    if len(query) > 10000:
        raise ValidationError("Query too long (max 10000 characters)")

    # Basic safety checks
    dangerous_patterns = [
        r"System\.exit",
        r"Runtime\.getRuntime",
        r"ProcessBuilder",
        r"java\.io\.File.*delete",
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, query, re.IGNORECASE):
            raise ValidationError(
                f"Query contains potentially dangerous operation: {pattern}"
            )


def hash_query(query: str) -> str:
    """Generate hash for query caching"""
    return hashlib.sha256(query.encode()).hexdigest()


def sanitize_path(path: str) -> str:
    """Sanitize file path"""
    # Remove any .. or other path traversal attempts
    path = re.sub(r"\.\.+", "", path)
    return path


def validate_timeout(timeout: int, max_timeout: int = 300):
    """Validate timeout value"""
    if timeout < 1:
        raise ValidationError("Timeout must be at least 1 second")

    if timeout > max_timeout:
        raise ValidationError(f"Timeout cannot exceed {max_timeout} seconds")
