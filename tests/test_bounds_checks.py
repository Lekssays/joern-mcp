"""
Tests for find_bounds_checks tool
"""

import pytest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from src.tools.code_browsing_tools import register_code_browsing_tools
from src.models import SessionStatus

TEST_SESSION_ID = str(uuid.uuid4())


@pytest.mark.asyncio
async def test_find_bounds_checks_success():
    """Test successful bounds check analysis"""
    # Mock MCP server
    mcp = MagicMock()
    registered_tools = {}

    def tool_decorator():
        def wrapper(func):
            registered_tools[func.__name__] = func
            return func

        return wrapper

    mcp.tool = tool_decorator

    # Mock services
    session_manager = AsyncMock()
    query_executor = AsyncMock()

    services = {
        "session_manager": session_manager,
        "query_executor": query_executor,
    }

    # Mock session
    mock_session = MagicMock()
    mock_session.status = SessionStatus.READY.value
    session_manager.get_session.return_value = mock_session
    session_manager.touch_session.return_value = None

    # Mock query result with bounds checks
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.data = [
        '{"success": true, "buffer_access": {"line": 3393, "code": "buf[len++]", "buffer": "buf", "index": "len++"}, "bounds_checks": [{"line": 3396, "code": "len >= XML_MAX_NAMELEN", "checked_variable": "len", "bound": "XML_MAX_NAMELEN", "operator": ">=", "position": "AFTER_ACCESS"}], "check_before_access": false, "check_after_access": true}'
    ]
    query_executor.execute_query.return_value = mock_result

    # Register tools
    register_code_browsing_tools(mcp, services)

    # Get the find_bounds_checks function
    find_bounds_checks = registered_tools["find_bounds_checks"]

    # Call the tool
    result = await find_bounds_checks(TEST_SESSION_ID, "parser.c:3393")

    # Verify result
    assert result["success"] is True
    assert result["buffer_access"]["line"] == 3393
    assert result["buffer_access"]["buffer"] == "buf"
    assert result["buffer_access"]["index"] == "len++"
    assert len(result["bounds_checks"]) == 1
    assert result["bounds_checks"][0]["line"] == 3396
    assert result["bounds_checks"][0]["position"] == "AFTER_ACCESS"
    assert result["check_before_access"] is False
    assert result["check_after_access"] is True

    # Verify service calls
    session_manager.get_session.assert_called_once_with(TEST_SESSION_ID)
    session_manager.touch_session.assert_called_once_with(TEST_SESSION_ID)
    query_executor.execute_query.assert_called_once()


@pytest.mark.asyncio
async def test_find_bounds_checks_invalid_location_format():
    """Test with invalid location format"""
    mcp = MagicMock()
    registered_tools = {}

    def tool_decorator():
        def wrapper(func):
            registered_tools[func.__name__] = func
            return func

        return wrapper

    mcp.tool = tool_decorator

    services = {
        "session_manager": AsyncMock(),
        "query_executor": AsyncMock(),
    }

    register_code_browsing_tools(mcp, services)
    find_bounds_checks = registered_tools["find_bounds_checks"]

    # Test without colon
    result = await find_bounds_checks(TEST_SESSION_ID, "parser.c")
    assert result["success"] is False
    assert "format" in result["error"]["message"].lower()

    # Test with invalid line number
    result = await find_bounds_checks(TEST_SESSION_ID, "parser.c:abc")
    assert result["success"] is False
    assert "invalid" in result["error"]["message"].lower()


@pytest.mark.asyncio
async def test_find_bounds_checks_not_found():
    """Test when buffer access is not found"""
    mcp = MagicMock()
    registered_tools = {}

    def tool_decorator():
        def wrapper(func):
            registered_tools[func.__name__] = func
            return func

        return wrapper

    mcp.tool = tool_decorator

    session_manager = AsyncMock()
    query_executor = AsyncMock()

    services = {
        "session_manager": session_manager,
        "query_executor": query_executor,
    }

    mock_session = MagicMock()
    mock_session.status = SessionStatus.READY.value
    session_manager.get_session.return_value = mock_session

    # Mock result when buffer access not found
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.data = [
        '{"success": false, "error": {"code": "NOT_FOUND", "message": "No buffer access found at parser.c:9999"}}'
    ]
    query_executor.execute_query.return_value = mock_result

    register_code_browsing_tools(mcp, services)
    find_bounds_checks = registered_tools["find_bounds_checks"]

    result = await find_bounds_checks(TEST_SESSION_ID, "parser.c:9999")

    assert result["success"] is False
    assert result["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_find_bounds_checks_session_not_ready():
    """Test when session is not ready"""
    mcp = MagicMock()
    registered_tools = {}

    def tool_decorator():
        def wrapper(func):
            registered_tools[func.__name__] = func
            return func

        return wrapper

    mcp.tool = tool_decorator

    session_manager = AsyncMock()
    services = {
        "session_manager": session_manager,
        "query_executor": AsyncMock(),
    }

    # Mock session in generating state
    mock_session = MagicMock()
    mock_session.status = SessionStatus.GENERATING.value
    session_manager.get_session.return_value = mock_session

    register_code_browsing_tools(mcp, services)
    find_bounds_checks = registered_tools["find_bounds_checks"]

    result = await find_bounds_checks(TEST_SESSION_ID, "parser.c:3393")

    assert result["success"] is False
    assert "SESSIONNOTREADYERROR" in result["error"]["code"]


@pytest.mark.asyncio
async def test_find_bounds_checks_with_before_check():
    """Test bounds check that happens before access"""
    mcp = MagicMock()
    registered_tools = {}

    def tool_decorator():
        def wrapper(func):
            registered_tools[func.__name__] = func
            return func

        return wrapper

    mcp.tool = tool_decorator

    session_manager = AsyncMock()
    query_executor = AsyncMock()

    services = {
        "session_manager": session_manager,
        "query_executor": query_executor,
    }

    mock_session = MagicMock()
    mock_session.status = SessionStatus.READY.value
    session_manager.get_session.return_value = mock_session

    # Mock result with bounds check BEFORE access
    mock_result = MagicMock()
    mock_result.success = True
    mock_result.data = [
        '{"success": true, "buffer_access": {"line": 100, "code": "arr[i]", "buffer": "arr", "index": "i"}, "bounds_checks": [{"line": 98, "code": "i < SIZE", "checked_variable": "i", "bound": "SIZE", "operator": "<", "position": "BEFORE_ACCESS"}], "check_before_access": true, "check_after_access": false}'
    ]
    query_executor.execute_query.return_value = mock_result

    register_code_browsing_tools(mcp, services)
    find_bounds_checks = registered_tools["find_bounds_checks"]

    result = await find_bounds_checks(TEST_SESSION_ID, "test.c:100")

    assert result["success"] is True
    assert result["check_before_access"] is True
    assert result["check_after_access"] is False
    assert result["bounds_checks"][0]["position"] == "BEFORE_ACCESS"
