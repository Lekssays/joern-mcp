"""
Tests for the get_data_dependencies tool
"""

import pytest
from unittest.mock import AsyncMock

from src.models import QueryResult, Session, SessionStatus


class FakeMCP:
    """Fake MCP class for testing"""

    def __init__(self):
        self.registered = {}

    def tool(self):
        """Decorator to register tool functions"""

        def _decorator(func):
            self.registered[func.__name__] = func
            return func

        return _decorator


@pytest.fixture
def mock_services():
    """Create mock services for testing"""
    import uuid

    session_manager = AsyncMock()
    query_executor = AsyncMock()

    # Mock session with valid UUID
    session_id = str(uuid.uuid4())
    mock_session = Session(
        id=session_id,
        source_type="github",
        source_path="https://github.com/test/repo",
        language="c",
        status=SessionStatus.READY.value,
        created_at=1234567890.0,
    )

    session_manager.get_session = AsyncMock(return_value=mock_session)
    session_manager.touch_session = AsyncMock()

    return {
        "session_manager": session_manager,
        "query_executor": query_executor,
        "session_id": session_id,
    }


@pytest.mark.asyncio
async def test_get_data_dependencies_backward_success(mock_services):
    """Test successful backward dependency analysis"""
    from src.tools.mcp_tools import register_tools

    mcp = FakeMCP()

    # Mock query result with backward dependencies
    mock_result = QueryResult(
        success=True,
        data=[
            """{
                "success": true,
                "target": {
                    "file": "parser.c",
                    "line": 3393,
                    "variable": "len",
                    "method": "xmlParseNmtoken"
                },
                "direction": "backward",
                "dependencies": [
                    {
                        "line": 3383,
                        "code": "int len = 0",
                        "type": "initialization",
                        "filename": "parser.c"
                    },
                    {
                        "line": 3390,
                        "code": "len++",
                        "type": "modification",
                        "filename": "parser.c"
                    }
                ],
                "total": 2
            }"""
        ],
        row_count=1,
        execution_time=0.5,
    )

    mock_services["query_executor"].execute_query = AsyncMock(return_value=mock_result)

    register_tools(mcp, mock_services)

    tool_func = mcp.registered.get("get_data_dependencies")
    assert tool_func is not None

    # Call the tool
    result = await tool_func(
        session_id=mock_services["session_id"],
        location="parser.c:3393",
        variable="len",
        direction="backward",
    )

    # Verify result
    assert result["success"] is True
    assert result["target"]["file"] == "parser.c"
    assert result["target"]["line"] == 3393
    assert result["target"]["variable"] == "len"
    assert result["direction"] == "backward"
    assert len(result["dependencies"]) == 2
    assert result["total"] == 2

    # Verify dependencies
    assert result["dependencies"][0]["type"] == "initialization"
    assert result["dependencies"][1]["type"] == "modification"


@pytest.mark.asyncio
async def test_get_data_dependencies_forward_success(mock_services):
    """Test successful forward dependency analysis"""
    from src.tools.mcp_tools import register_tools

    mcp = FakeMCP()

    # Mock query result with forward dependencies
    mock_result = QueryResult(
        success=True,
        data=[
            """{
                "success": true,
                "target": {
                    "file": "parser.c",
                    "line": 3383,
                    "variable": "len",
                    "method": "xmlParseNmtoken"
                },
                "direction": "forward",
                "dependencies": [
                    {
                        "line": 3390,
                        "code": "COPY_BUF(len)",
                        "type": "usage",
                        "filename": "parser.c"
                    },
                    {
                        "line": 3395,
                        "code": "total = len",
                        "type": "propagation",
                        "filename": "parser.c"
                    }
                ],
                "total": 2
            }"""
        ],
        row_count=1,
        execution_time=0.5,
    )

    mock_services["query_executor"].execute_query = AsyncMock(return_value=mock_result)

    register_tools(mcp, mock_services)

    tool_func = mcp.registered.get("get_data_dependencies")
    assert tool_func is not None

    result = await tool_func(
        session_id=mock_services["session_id"],
        location="parser.c:3383",
        variable="len",
        direction="forward",
    )

    assert result["success"] is True
    assert result["direction"] == "forward"
    assert len(result["dependencies"]) == 2
    assert result["dependencies"][0]["type"] == "usage"
    assert result["dependencies"][1]["type"] == "propagation"


@pytest.mark.asyncio
async def test_get_data_dependencies_invalid_location_format(mock_services):
    """Test error handling for invalid location format"""
    from src.tools.mcp_tools import register_tools

    mcp = FakeMCP()
    register_tools(mcp, mock_services)

    tool_func = mcp.registered.get("get_data_dependencies")
    assert tool_func is not None

    # Test missing colon
    result = await tool_func(
        session_id=mock_services["session_id"],
        location="parser.c",
        variable="len",
        direction="backward",
    )

    assert result["success"] is False
    assert "VALIDATIONERROR" in result["error"]["code"]


@pytest.mark.asyncio
async def test_get_data_dependencies_session_not_found(mock_services):
    """Test error handling when session doesn't exist"""
    from src.tools.mcp_tools import register_tools
    import uuid

    mcp = FakeMCP()

    # Mock session not found
    mock_services["session_manager"].get_session = AsyncMock(return_value=None)

    register_tools(mcp, mock_services)

    tool_func = mcp.registered.get("get_data_dependencies")
    assert tool_func is not None

    # Use a valid UUID format for a nonexistent session
    nonexistent_id = str(uuid.uuid4())
    result = await tool_func(
        session_id=nonexistent_id,
        location="parser.c:3393",
        variable="len",
        direction="backward",
    )

    assert result["success"] is False
    assert "SESSIONNOTFOUNDERROR" in result["error"]["code"]


@pytest.mark.asyncio
async def test_get_data_dependencies_query_execution_error(mock_services):
    """Test error handling when query execution fails"""
    from src.tools.mcp_tools import register_tools

    mcp = FakeMCP()

    # Mock query execution error
    mock_result = QueryResult(
        success=False, error="Query execution timeout", execution_time=30.0
    )

    mock_services["query_executor"].execute_query = AsyncMock(return_value=mock_result)

    register_tools(mcp, mock_services)

    tool_func = mcp.registered.get("get_data_dependencies")
    assert tool_func is not None

    result = await tool_func(
        session_id=mock_services["session_id"],
        location="parser.c:3393",
        variable="len",
        direction="backward",
    )

    assert result["success"] is False
    assert result["error"]["code"] == "QUERY_ERROR"


@pytest.mark.asyncio
async def test_get_data_dependencies_no_dependencies_found(mock_services):
    """Test when no dependencies are found for the variable"""
    from src.tools.mcp_tools import register_tools

    mcp = FakeMCP()

    # Mock query result with empty dependencies
    mock_result = QueryResult(
        success=True,
        data=[
            """{
                "success": true,
                "target": {
                    "file": "parser.c",
                    "line": 3393,
                    "variable": "unknown_var",
                    "method": "xmlParseNmtoken"
                },
                "direction": "backward",
                "dependencies": [],
                "total": 0
            }"""
        ],
        row_count=1,
        execution_time=0.5,
    )

    mock_services["query_executor"].execute_query = AsyncMock(return_value=mock_result)

    register_tools(mcp, mock_services)

    tool_func = mcp.registered.get("get_data_dependencies")
    assert tool_func is not None

    result = await tool_func(
        session_id=mock_services["session_id"],
        location="parser.c:3393",
        variable="unknown_var",
        direction="backward",
    )

    assert result["success"] is True
    assert len(result["dependencies"]) == 0
    assert result["total"] == 0


@pytest.mark.asyncio
async def test_get_data_dependencies_touch_session_called(mock_services):
    """Test that touch_session is called to update last access time"""
    from src.tools.mcp_tools import register_tools

    mcp = FakeMCP()

    mock_result = QueryResult(
        success=True,
        data=[
            """{
                "success": true,
                "target": {
                    "file": "parser.c",
                    "line": 3393,
                    "variable": "len",
                    "method": "xmlParseNmtoken"
                },
                "direction": "backward",
                "dependencies": [],
                "total": 0
            }"""
        ],
        row_count=1,
        execution_time=0.5,
    )

    mock_services["query_executor"].execute_query = AsyncMock(return_value=mock_result)

    register_tools(mcp, mock_services)

    tool_func = mcp.registered.get("get_data_dependencies")
    assert tool_func is not None

    await tool_func(
        session_id=mock_services["session_id"],
        location="parser.c:3393",
        variable="len",
        direction="backward",
    )

    # Verify touch_session was called
    mock_services["session_manager"].touch_session.assert_called_once_with(
        mock_services["session_id"]
    )
