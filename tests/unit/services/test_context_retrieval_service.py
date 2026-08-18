import pytest
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
from unittest.mock import MagicMock
from src.services.context_retrieval_service import ContextRetrievalService
from src.models import ProjectVersion, QueryResult

def test_context_retrieval_service():
    mock_executor = MagicMock()
    mock_version_service = MagicMock()
    
    mock_version = ProjectVersion(
        id="v1", project_id="p1", commit_sha="abc", branch="main", content_digest="def",
        build_status="ready"
    )
    mock_version_service.get_version.return_value = mock_version
    
    mock_executor.execute_query.side_effect = [
        QueryResult(success=True, data=[{"filename": "a.py", "lineNumber": 1, "lineNumberEnd": 10, "code": "def test(): pass"}], row_count=1),
        QueryResult(success=True, data=[], row_count=0),
    ]
    
    service = ContextRetrievalService(mock_executor, mock_version_service)
    result = service.get_context("v1", "test")
    
    assert result["items"][0]["filename"] == "a.py"
    assert result["items"][0]["code"] == "def test(): pass"
    assert result["items"][0]["version_digest"] == "def"

def test_context_retrieval_enforces_max_items_budget():
    mock_executor = MagicMock()
    mock_version_service = MagicMock()
    
    mock_version = ProjectVersion(
        id="v1", project_id="p1", commit_sha="abc", branch="main", content_digest="def",
        build_status="ready"
    )
    mock_version_service.get_version.return_value = mock_version
    
    mock_executor.execute_query.side_effect = [
        QueryResult(success=True, data=[
            {"filename": "a.py", "lineNumber": 1, "code": "A"},
            {"filename": "b.py", "lineNumber": 2, "code": "B"},
            {"filename": "c.py", "lineNumber": 3, "code": "C"}
        ], row_count=3),
        QueryResult(success=True, data=[], row_count=0),
    ]
    
    service = ContextRetrievalService(mock_executor, mock_version_service)
    result = service.get_context("v1", "test", max_items=2)
    
    assert len(result["items"]) == 2
    assert result["truncated"] is True
    assert result["budget"]["used_items"] == 2

def test_context_retrieval_enforces_max_bytes_budget():
    mock_executor = MagicMock()
    mock_version_service = MagicMock()
    
    mock_version = ProjectVersion(
        id="v1", project_id="p1", commit_sha="abc", branch="main", content_digest="def",
        build_status="ready"
    )
    mock_version_service.get_version.return_value = mock_version
    
    mock_executor.execute_query.side_effect = [
        QueryResult(success=True, data=[
            {"filename": "a.py", "lineNumber": 1, "code": "A" * 60},
            {"filename": "b.py", "lineNumber": 2, "code": "B" * 50}
        ], row_count=2),
        QueryResult(success=True, data=[], row_count=0),
    ]
    
    service = ContextRetrievalService(mock_executor, mock_version_service)
    result = service.get_context("v1", "test", max_bytes=100)
    
    assert len(result["items"]) == 1
    assert result["items"][0]["filename"] == "a.py"
    assert result["truncated"] is True
    assert result["budget"]["used_bytes"] == 60
