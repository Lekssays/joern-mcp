"""
Comprehensive tests for all MCP tools in mcp_tools.py
"""

import asyncio
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from src.exceptions import (
    QueryExecutionError,
    ResourceLimitError,
    SessionNotFoundError,
    SessionNotReadyError,
    ValidationError,
)
from src.models import Config, CPGConfig, QueryResult, Session, SessionStatus
from src.tools.core_tools import get_cpg_cache_key, get_cpg_cache_path
from src.tools.mcp_tools import register_tools


class FakeMCP:
    """Mock MCP server for testing tool registration"""

    def __init__(self):
        self.registered = {}

    def tool(self):
        """Decorator to register functions by name"""

        def _decorator(func):
            self.registered[func.__name__] = func
            return func

        return _decorator


@pytest.fixture
def fake_services():
    """Comprehensive mock services fixture"""
    # Session manager mock
    session_manager = AsyncMock()
    session_manager.create_session = AsyncMock()
    session_manager.get_session = AsyncMock()
    session_manager.update_session = AsyncMock()
    session_manager.list_sessions = AsyncMock(return_value=[])
    session_manager.touch_session = AsyncMock()
    session_manager.cleanup_session = AsyncMock()

    # Query executor mock
    query_executor = AsyncMock()
    query_executor.execute_query = AsyncMock()
    query_executor.execute_query_async = AsyncMock()
    query_executor.get_query_status = AsyncMock()
    query_executor.get_query_result = AsyncMock()
    query_executor.cleanup_query = AsyncMock()
    query_executor.cleanup_old_queries = AsyncMock()
    query_executor.list_queries = AsyncMock(return_value={})

    # Git manager mock
    git_manager = AsyncMock()
    git_manager.clone_repository = AsyncMock()

    # Docker orchestrator mock
    docker_orch = AsyncMock()
    docker_orch.start_container = AsyncMock(return_value="container123")
    docker_orch.stop_container = AsyncMock()

    # CPG generator mock
    cpg_generator = AsyncMock()
    cpg_generator.generate_cpg = AsyncMock()
    cpg_generator.register_session_container = AsyncMock()

    # Redis client mock
    redis_client = AsyncMock()
    redis_client.set_container_mapping = AsyncMock()

    # Config mock
    cpg_config = CPGConfig()
    cpg_config.taint_sources = {"c": ["getenv", "fgets"], "java": ["Scanner.next"]}
    cpg_config.taint_sinks = {"c": ["system", "popen"], "java": ["Runtime.exec"]}
    config = Config(cpg=cpg_config)
    config.storage.workspace_root = "/tmp/workspace"
    config.sessions.ttl = 3600

    services = {
        "session_manager": session_manager,
        "query_executor": query_executor,
        "git_manager": git_manager,
        "docker": docker_orch,
        "cpg_generator": cpg_generator,
        "redis": redis_client,
        "config": config,
    }

    return services


@pytest.fixture
def ready_session():
    """Ready session fixture"""
    import uuid

    session_id = str(uuid.uuid4())
    return Session(
        id=session_id,
        container_id="container123",
        source_type="local",
        source_path="/tmp/test",
        language="c",
        status=SessionStatus.READY.value,
        created_at=datetime.now(timezone.utc),
        last_accessed=datetime.now(timezone.utc),
        cpg_path="/tmp/workspace/repos/" + session_id + "/cpg.bin",
    )


@pytest.fixture
def temp_workspace():
    """Temporary workspace for testing"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


class TestMCPTools:
    """Comprehensive test suite for all MCP tools"""

    @pytest.mark.asyncio
    async def test_create_cpg_session_github_success(self, fake_services):
        """Test successful CPG session creation for GitHub repo"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        # Mock session creation
        import uuid

        session_id = str(uuid.uuid4())
        session = Session(
            id=session_id,
            source_type="github",
            source_path="https://github.com/user/repo",
            language="java",
            status=SessionStatus.GENERATING.value,
        )
        fake_services["session_manager"].create_session.return_value = session

        # Mock no existing CPG and patch shutil.copy2 calls
        with patch("os.path.exists", return_value=False), patch(
            "shutil.copy2"
        ) as mock_copy2:
            func = mcp.registered["create_cpg_session"]
            result = await func(
                source_type="github",
                source_path="https://github.com/user/repo",
                language="java",
            )

            # The function returns the session info directly on success
            assert "session_id" in result
            assert result["session_id"] == session_id
            assert result["status"] == SessionStatus.GENERATING.value

    @pytest.mark.asyncio
    async def test_create_cpg_session_cached_cpg(self, fake_services, temp_workspace):
        """Test CPG session creation with cached CPG"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        # Mock session creation
        import uuid

        session_id = str(uuid.uuid4())
        session = Session(
            id=session_id,
            source_type="github",
            source_path="https://github.com/user/repo",
            language="java",
            status=SessionStatus.READY.value,
        )
        fake_services["session_manager"].create_session.return_value = session

        # Create temporary playground structure
        playground_path = os.path.join(temp_workspace, "playground")
        os.makedirs(os.path.join(playground_path, "cpgs"), exist_ok=True)
        os.makedirs(os.path.join(playground_path, "codebases"), exist_ok=True)

        # Create mock cached CPG
        cache_key = get_cpg_cache_key("github", "https://github.com/user/repo", "java")
        cpg_path = get_cpg_cache_path(cache_key, playground_path)
        os.makedirs(os.path.dirname(cpg_path), exist_ok=True)
        with open(cpg_path, "w") as f:
            f.write("mock cpg")

        with patch(
            "src.tools.core_tools.os.path.abspath", return_value=playground_path
        ), patch("os.path.exists", side_effect=lambda p: p == cpg_path), patch(
            "shutil.copy2"
        ) as mock_copy2:

            func = mcp.registered["create_cpg_session"]
            result = await func(
                source_type="github",
                source_path="https://github.com/user/repo",
                language="java",
            )

            # Should return session info directly
            assert "session_id" in result
            assert result["session_id"] == session_id
            assert result["status"] == SessionStatus.READY.value
            assert result.get("cached") is True

    @pytest.mark.asyncio
    async def test_create_cpg_session_validation_error(self, fake_services):
        """Test CPG session creation with validation error"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        func = mcp.registered["create_cpg_session"]
        result = await func(
            source_type="invalid",
            source_path="https://github.com/user/repo",
            language="java",
        )

        assert result["success"] is False
        assert "VALIDATION_ERROR" in result["error"]["code"]

    @pytest.mark.asyncio
    async def test_run_cpgql_query_async_success(self, fake_services, ready_session):
        """Test successful async CPGQL query execution"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session
        fake_services["query_executor"].execute_query_async.return_value = "query123"

        func = mcp.registered["run_cpgql_query_async"]
        result = await func(
            session_id=ready_session.id, query="cpg.method.name.toJson", timeout=30
        )

        assert result["success"] is True
        assert result["query_id"] == "query123"
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_session_not_found_error(self, fake_services):
        """Test session not found error handling"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = None

        func = mcp.registered["run_cpgql_query_async"]
        result = await func(
            session_id="12345678-1234-5678-9012-123456789012",  # Valid UUID
            query="cpg.method.name.toJson",
        )

        assert result["success"] is False
        assert result["error"]["code"] == "SESSION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_get_query_status_success(self, fake_services):
        """Test successful query status retrieval"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        status_info = {
            "query_id": "query123",
            "status": "completed",
            "execution_time": 1.5,
        }
        fake_services["query_executor"].get_query_status.return_value = status_info

        func = mcp.registered["get_query_status"]
        result = await func(query_id="query123")

        assert result["success"] is True
        assert result["query_id"] == "query123"
        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_get_query_result_success(self, fake_services):
        """Test successful query result retrieval"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        query_result = QueryResult(
            success=True,
            data=[{"name": "main"}, {"name": "helper"}],
            row_count=2,
            execution_time=1.2,
        )
        fake_services["query_executor"].get_query_result.return_value = query_result

        func = mcp.registered["get_query_result"]
        result = await func(query_id="query123")

        assert result["success"] is True
        assert len(result["data"]) == 2
        assert result["row_count"] == 2

    @pytest.mark.asyncio
    async def test_cleanup_queries_success(self, fake_services):
        """Test successful query cleanup"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        func = mcp.registered["cleanup_queries"]
        result = await func(max_age_hours=2)

        assert result["success"] is True
        assert "cleaned_up" in result

    @pytest.mark.asyncio
    async def test_run_cpgql_query_success(self, fake_services, ready_session):
        """Test successful synchronous CPGQL query"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session
        query_result = QueryResult(
            success=True,
            data=[{"_1": "main"}, {"_1": "helper"}],
            row_count=2,
            execution_time=0.8,
        )
        fake_services["query_executor"].execute_query.return_value = query_result

        func = mcp.registered["run_cpgql_query"]
        result = await func(session_id=ready_session.id, query="cpg.method.name.l")

        assert result["success"] is True
        assert result["row_count"] == 2

    @pytest.mark.asyncio
    async def test_get_session_status_success(self, fake_services, ready_session):
        """Test successful session status retrieval"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session

        with patch("os.path.exists", return_value=True), patch(
            "os.path.getsize", return_value=1024 * 1024
        ):

            func = mcp.registered["get_session_status"]
            result = await func(session_id=ready_session.id)

            # Success returns session data directly
            assert "session_id" in result
            assert result["session_id"] == ready_session.id
            assert result["status"] == SessionStatus.READY.value
            assert "cpg_size" in result

    @pytest.mark.asyncio
    async def test_list_sessions_success(self, fake_services, ready_session):
        """Test successful session listing"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].list_sessions.return_value = [ready_session]

        func = mcp.registered["list_sessions"]
        result = await func()

        # Success returns data directly
        assert "sessions" in result
        assert len(result["sessions"]) == 1
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_close_session_success(self, fake_services, ready_session):
        """Test successful session closure"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session

        func = mcp.registered["close_session"]
        result = await func(session_id=ready_session.id)

        assert result["success"] is True
        assert "Session closed successfully" in result["message"]

    @pytest.mark.asyncio
    async def test_cleanup_all_sessions_success(self, fake_services, ready_session):
        """Test successful cleanup of all sessions"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].list_sessions.return_value = [ready_session]

        func = mcp.registered["cleanup_all_sessions"]
        result = await func(force=True)

        assert result["success"] is True
        assert result["cleaned_up"] == 1

    @pytest.mark.asyncio
    async def test_list_files_success(self, fake_services, ready_session):
        """Test successful file listing"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session
        query_result = QueryResult(
            success=True,
            data=["src/main.c", "src/utils.c", "include/header.h"],
            row_count=3,
        )
        fake_services["query_executor"].execute_query.return_value = query_result

        # `list_files` was removed from the tools. This test is no longer applicable.

    @pytest.mark.asyncio
    async def test_list_methods_success(self, fake_services, ready_session):
        """Test successful method listing"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session
        query_result = QueryResult(
            success=True,
            data=[
                {
                    "_1": "12345",
                    "_2": "main",
                    "_3": "main",
                    "_4": "int main(int, char**)",
                    "_5": "main.c",
                    "_6": 10,
                    "_7": False,
                }
            ],
            row_count=1,
        )
        fake_services["query_executor"].execute_query.return_value = query_result

        func = mcp.registered["list_methods"]
        result = await func(session_id=ready_session.id)

        assert result["success"] is True
        assert len(result["methods"]) == 1
        assert result["methods"][0]["node_id"] == "12345"
        assert result["methods"][0]["name"] == "main"

    @pytest.mark.asyncio
    async def test_get_method_source_success(
        self, fake_services, ready_session, temp_workspace
    ):
        """Test successful method source retrieval"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session

        # Mock query results
        query_result = QueryResult(
            success=True,
            data=[
                {
                    "_1": "main",
                    "_2": "main.c",
                    "_3": 3,  # Start line of function
                    "_4": 7,  # End line of function
                }
            ],
            row_count=1,
        )
        fake_services["query_executor"].execute_query.return_value = query_result

        # Create mock source file - need to match the path construction in the code
        # For local sessions, it uses session.source_path directly
        source_dir = ready_session.source_path  # This is "/tmp/test"
        os.makedirs(source_dir, exist_ok=True)
        source_file = os.path.join(source_dir, "main.c")
        with open(source_file, "w") as f:
            f.write(
                '#include <stdio.h>\n\nint main() {\n    printf("Hello\\n");\n    return 0;\n}\n'
            )

        with patch("src.tools.code_browsing_tools.os.path.abspath", return_value=temp_workspace):
            func = mcp.registered["get_method_source"]
            result = await func(session_id=ready_session.id, method_name="main")

            assert result["success"] is True
            assert len(result["methods"]) == 1
            assert "int main()" in result["methods"][0]["code"]

    @pytest.mark.asyncio
    async def test_list_calls_success(self, fake_services, ready_session):
        """Test successful call listing"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session
        query_result = QueryResult(
            success=True,
            data=[
                {
                    "_1": "main",
                    "_2": "printf",
                    "_3": 'printf("Hello")',
                    "_4": "main.c",
                    "_5": 6,
                }
            ],
            row_count=1,
        )
        fake_services["query_executor"].execute_query.return_value = query_result

        func = mcp.registered["list_calls"]
        result = await func(session_id=ready_session.id)

        assert result["success"] is True
        assert len(result["calls"]) == 1
        assert result["calls"][0]["callee"] == "printf"

    @pytest.mark.asyncio
    async def test_get_call_graph_success(self, fake_services, ready_session):
        """Test successful call graph retrieval"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session
        query_result = QueryResult(
            success=True, data=[{"_1": "main", "_2": "helper", "_3": 1}], row_count=1
        )
        fake_services["query_executor"].execute_query.return_value = query_result

        func = mcp.registered["get_call_graph"]
        result = await func(session_id=ready_session.id, method_name="main")

        assert result["success"] is True
        assert len(result["calls"]) == 1
        assert result["calls"][0]["from"] == "main"

    @pytest.mark.asyncio
    async def test_list_parameters_success(self, fake_services, ready_session):
        """Test successful parameter listing"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session
        query_result = QueryResult(
            success=True,
            data=[
                {
                    "_1": "authenticate",
                    "_2": [
                        {"_1": "username", "_2": "string", "_3": 1},
                        {"_1": "password", "_2": "string", "_3": 2},
                    ],
                }
            ],
            row_count=1,
        )
        fake_services["query_executor"].execute_query.return_value = query_result

        func = mcp.registered["list_parameters"]
        result = await func(session_id=ready_session.id, method_name="authenticate")

        assert result["success"] is True
        assert len(result["methods"]) == 1
        assert len(result["methods"][0]["parameters"]) == 2

    @pytest.mark.asyncio
    async def test_find_literals_success(self, fake_services, ready_session):
        """Test successful literal finding"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session
        query_result = QueryResult(
            success=True,
            data=[
                {
                    "_1": '"admin_password"',
                    "_2": "string",
                    "_3": "config.c",
                    "_4": 42,
                    "_5": "init_config",
                }
            ],
            row_count=1,
        )
        fake_services["query_executor"].execute_query.return_value = query_result

        func = mcp.registered["find_literals"]
        result = await func(session_id=ready_session.id)

        assert result["success"] is True
        assert len(result["literals"]) == 1
        assert result["literals"][0]["value"] == '"admin_password"'

    @pytest.mark.asyncio
    async def test_find_taint_sources_success(self, fake_services, ready_session):
        """Test successful taint source finding"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session
        query_result = QueryResult(
            success=True,
            data=[
                {
                    "_1": "12345",
                    "_2": "getenv",
                    "_3": 'getenv("PATH")',
                    "_4": "main.c",
                    "_5": 10,
                    "_6": "main",
                }
            ],
            row_count=1,
        )
        fake_services["query_executor"].execute_query.return_value = query_result

        func = mcp.registered["find_taint_sources"]
        result = await func(session_id=ready_session.id)

        assert result["success"] is True
        assert len(result["sources"]) == 1
        assert result["sources"][0]["name"] == "getenv"

    @pytest.mark.asyncio
    async def test_find_taint_sinks_success(self, fake_services, ready_session):
        """Test successful taint sink finding"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session
        query_result = QueryResult(
            success=True,
            data=[
                {
                    "_1": "67890",
                    "_2": "system",
                    "_3": "system(cmd)",
                    "_4": "main.c",
                    "_5": 100,
                    "_6": "execute_command",
                }
            ],
            row_count=1,
        )
        fake_services["query_executor"].execute_query.return_value = query_result

        func = mcp.registered["find_taint_sinks"]
        result = await func(session_id=ready_session.id)

        assert result["success"] is True
        assert len(result["sinks"]) == 1
        assert result["sinks"][0]["name"] == "system"

    @pytest.mark.asyncio
    async def test_find_taint_flows_success(self, fake_services, ready_session):
        """Test successful taint flow finding with node IDs"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session

        # Mock for source node lookup query
        source_info_result = QueryResult(
            success=True,
            data=[
                {
                    "_1": 12345,  # node_id
                    "_2": 'getenv("PATH")',
                    "_3": "main.c",
                    "_4": 42,
                    "_5": "main",
                }
            ],
            row_count=1,
        )

        # Mock for sink node lookup query
        sink_info_result = QueryResult(
            success=True,
            data=[
                {
                    "_1": 67890,  # node_id
                    "_2": "system(cmd)",
                    "_3": "main.c",
                    "_4": 100,
                    "_5": "execute_command",
                }
            ],
            row_count=1,
        )

        # Mock for flow query - returns one flow with path information
        flow_query_result = QueryResult(
            success=True,
            data=[
                {
                    "_1": 0,  # flow_idx
                    "_2": 3,  # path_length
                    "_3": [  # nodes
                        {
                            "_1": 'getenv("PATH")',
                            "_2": "main.c",
                            "_3": 42,
                            "_4": "CALL",
                        },
                        {
                            "_1": "path_var",
                            "_2": "main.c",
                            "_3": 45,
                            "_4": "IDENTIFIER",
                        },
                        {"_1": "system(cmd)", "_2": "main.c", "_3": 100, "_4": "CALL"},
                    ],
                }
            ],
            row_count=1,
        )

        # Setup mock to return different results for different queries
        call_count = [0]

        async def mock_execute_query(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return source_info_result
            elif call_count[0] == 2:
                return sink_info_result
            else:
                return flow_query_result

        fake_services["query_executor"].execute_query.side_effect = mock_execute_query

        func = mcp.registered["find_taint_flows"]
        result = await func(
            session_id=ready_session.id, source_node_id="12345", sink_node_id="67890"
        )

        assert result["success"] is True
        assert result["source"]["node_id"] == 12345
        assert result["source"]["code"] == 'getenv("PATH")'
        assert result["sink"]["node_id"] == 67890
        assert result["sink"]["code"] == "system(cmd)"
        assert len(result["flows"]) == 1
        assert result["flows"][0]["path_length"] == 3
        assert len(result["flows"][0]["nodes"]) == 3
        assert len(result["flows"]) == 1
        assert result["flows"][0]["path_length"] == 3
        assert len(result["flows"][0]["nodes"]) == 3

    @pytest.mark.asyncio
    async def test_check_method_reachability_success(
        self, fake_services, ready_session
    ):
        """Test successful method reachability check"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session
        query_result = QueryResult(success=True, data=[True], row_count=1)
        fake_services["query_executor"].execute_query.return_value = query_result

        func = mcp.registered["check_method_reachability"]
        result = await func(
            session_id=ready_session.id, source_method="main", target_method="helper"
        )

        assert result["success"] is True
        assert result["reachable"] is True
        assert "helper" in result["message"]

    @pytest.mark.asyncio
    async def test_get_program_slice_success(
        self, fake_services, ready_session, temp_workspace
    ):
        """Test successful program slice retrieval with node_id"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session

        # Mock the single inline Scala query that returns JSON directly
        json_result = QueryResult(
            success=True,
            data=[
                '{"success":true,"slice":{"target_call":{"node_id":"12345","name":"memcpy","code":"memcpy(buf, src, size)","filename":"main.c","lineNumber":42,"method":"vulnerable_function","arguments":["buf","src","size"]},"dataflow":[{"variable":"buf","code":"buf","filename":"main.c","lineNumber":10,"method":"vulnerable_function"}],"control_dependencies":[{"code":"if (size > 0)","filename":"main.c","lineNumber":35,"method":"vulnerable_function"}]},"total_nodes":3}'
            ],
            row_count=1,
        )

        fake_services["query_executor"].execute_query.return_value = json_result

        func = mcp.registered["get_program_slice"]
        result = await func(
            session_id=ready_session.id,
            node_id="12345",
            include_dataflow=True,
            include_control_flow=True,
        )

        assert result["success"] is True
        assert "slice" in result
        assert result["slice"]["target_call"]["node_id"] == "12345"
        assert result["slice"]["target_call"]["name"] == "memcpy"
        assert result["slice"]["target_call"]["arguments"] == ["buf", "src", "size"]

    @pytest.mark.asyncio
    async def test_get_program_slice_with_location(self, fake_services, ready_session):
        """Test program slice retrieval using location string"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session

        # Mock the single inline Scala query that returns JSON directly
        json_result = QueryResult(
            success=True,
            data=[
                '{"success":true,"slice":{"target_call":{"node_id":"67890","name":"system","code":"system(cmd)","filename":"main.c","lineNumber":100,"method":"execute_cmd","arguments":["cmd"]},"dataflow":[],"control_dependencies":[]},"total_nodes":1}'
            ],
            row_count=1,
        )

        fake_services["query_executor"].execute_query.return_value = json_result

        func = mcp.registered["get_program_slice"]
        result = await func(
            session_id=ready_session.id,
            location="main.c:100:system",
            include_dataflow=False,
            include_control_flow=True,
        )

        assert result["success"] is True
        assert result["slice"]["target_call"]["node_id"] == "67890"
        assert result["slice"]["target_call"]["name"] == "system"

    @pytest.mark.asyncio
    async def test_get_codebase_summary_success(self, fake_services, ready_session):
        """Test successful codebase summary retrieval"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session

        # Mock metadata query
        meta_result = QueryResult(
            success=True, data=[{"_1": "C", "_2": "11"}], row_count=1
        )

        # Mock stats query
        stats_result = QueryResult(
            success=True,
            data=[
                {
                    "_1": 5,  # files
                    "_2": 25,  # methods
                    "_3": 20,  # user methods
                    "_4": 50,  # calls
                    "_5": 15,  # literals
                }
            ],
            row_count=1,
        )

        fake_services["query_executor"].execute_query.side_effect = [
            meta_result,
            stats_result,
        ]

        func = mcp.registered["get_codebase_summary"]
        result = await func(session_id=ready_session.id)

        assert result["success"] is True
        assert result["summary"]["language"] == "C"
        assert result["summary"]["total_files"] == 5
        assert result["summary"]["total_methods"] == 25

    @pytest.mark.asyncio
    async def test_get_code_snippet_success(
        self, fake_services, ready_session, temp_workspace
    ):
        """Test successful code snippet retrieval"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session

        # Create mock source file
        source_dir = ready_session.source_path  # "/tmp/test"
        os.makedirs(source_dir, exist_ok=True)
        source_file = os.path.join(source_dir, "main.c")
        with open(source_file, "w") as f:
            f.write(
                '#include <stdio.h>\n\nint main() {\n    printf("Hello\\n");\n    return 0;\n}\n'
            )

        with patch("src.tools.code_browsing_tools.os.path.abspath", return_value=temp_workspace):
            func = mcp.registered["get_code_snippet"]
            result = await func(
                session_id=ready_session.id, filename="main.c", start_line=3, end_line=6
            )

            assert result["success"] is True
            assert "int main()" in result["code"]
            assert result["start_line"] == 3
            assert result["end_line"] == 6


class TestHelperFunctions:
    """Tests for helper functions"""

    def test_get_cpg_cache_key_github(self):
        """Test CPG cache key generation for GitHub URLs"""
        key = get_cpg_cache_key("github", "https://github.com/user/repo", "java")
        # Should return a 16-character hash
        assert isinstance(key, str)
        assert len(key) == 16
        # Should be deterministic
        key2 = get_cpg_cache_key("github", "https://github.com/user/repo", "java")
        assert key == key2

    def test_get_cpg_cache_key_local(self):
        """Test CPG cache key generation for local paths"""
        key = get_cpg_cache_key("local", "/home/user/project", "python")
        # Should return a 16-character hash
        assert isinstance(key, str)
        assert len(key) == 16
        # Should be deterministic
        key2 = get_cpg_cache_key("local", "/home/user/project", "python")
        assert key == key2

    def test_get_cpg_cache_path(self, temp_workspace):
        """Test CPG cache path generation"""
        cache_key = "test1234567890ab"
        path = get_cpg_cache_path(cache_key, temp_workspace)
        expected = os.path.join(temp_workspace, "cpgs", f"cpg_{cache_key}.bin")
        assert path == expected


class TestErrorHandling:
    """Tests for error handling across tools"""

    @pytest.mark.asyncio
    async def test_session_not_found_error(self, fake_services):
        """Test session not found error handling"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = None

        func = mcp.registered["get_session_status"]
        result = await func(
            session_id="12345678-1234-5678-9012-123456789012"
        )  # Valid UUID format

        assert result["success"] is False
        assert result["error"]["code"] == "SESSION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_session_not_ready_error(self, fake_services):
        """Test session not ready error handling"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        import uuid

        session_id = str(uuid.uuid4())
        generating_session = Session(
            id=session_id, status=SessionStatus.GENERATING.value
        )
        fake_services["session_manager"].get_session.return_value = generating_session

        func = mcp.registered["run_cpgql_query"]
        result = await func(session_id=session_id, query="cpg.method")

        assert result["success"] is False
        assert result["error"]["code"] == "SESSION_NOT_READY"

    @pytest.mark.asyncio
    async def test_validation_error(self, fake_services):
        """Test validation error handling"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        func = mcp.registered["create_cpg_session"]
        result = await func(
            source_type="github", source_path="not-a-url", language="java"
        )

        assert result["success"] is False
        assert "VALIDATION_ERROR" in result["error"]["code"]

    @pytest.mark.asyncio
    async def test_query_execution_error(self, fake_services, ready_session):
        """Test query execution error handling"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session
        fake_services["query_executor"].execute_query.side_effect = QueryExecutionError(
            "Query failed"
        )

        func = mcp.registered["run_cpgql_query"]
        result = await func(session_id=ready_session.id, query="invalid query")

        assert result["success"] is False
        assert result["error"]["code"] == "QUERY_EXECUTION_ERROR"


class TestEdgeCases:
    """Tests for edge cases and boundary conditions"""

    @pytest.mark.asyncio
    async def test_empty_query_results(self, fake_services, ready_session):
        """Test handling of empty query results"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session
        query_result = QueryResult(success=True, data=[], row_count=0)
        fake_services["query_executor"].execute_query.return_value = query_result

        func = mcp.registered["list_methods"]
        result = await func(session_id=ready_session.id)

        assert result["success"] is True
        assert result["methods"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_large_result_limits(self, fake_services, ready_session):
        """Test handling of large result sets with limits"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session

        # Mock large result set
        large_data = [{"_1": f"method{i}"} for i in range(200)]
        query_result = QueryResult(success=True, data=large_data, row_count=200)
        fake_services["query_executor"].execute_query.return_value = query_result

        func = mcp.registered["list_methods"]
        result = await func(session_id=ready_session.id, limit=50)

        assert result["success"] is True
        assert len(result["methods"]) == 200  # All results returned despite limit

    @pytest.mark.asyncio
    async def test_complex_call_graph_depth(self, fake_services, ready_session):
        """Test call graph with different depths"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session
        query_result = QueryResult(
            success=True,
            data=[
                {"_1": "main", "_2": "func1", "_3": 1},
                {"_1": "func1", "_2": "func2", "_3": 2},
                {"_1": "func2", "_2": "func3", "_3": 3},
            ],
            row_count=3,
        )
        fake_services["query_executor"].execute_query.return_value = query_result

        func = mcp.registered["get_call_graph"]
        result = await func(session_id=ready_session.id, method_name="main", depth=3)

        assert result["success"] is True
        assert len(result["calls"]) == 3
        assert result["calls"][-1]["depth"] == 3

    @pytest.mark.asyncio
    async def test_taint_flow_filters(self, fake_services, ready_session):
        """Test taint flow with node IDs and various filters"""
        mcp = FakeMCP()
        register_tools(mcp, fake_services)

        fake_services["session_manager"].get_session.return_value = ready_session

        # Mock source node lookup
        source_result = QueryResult(
            success=True,
            data=[
                {
                    "_1": 111,
                    "_2": 'getenv("X")',
                    "_3": "file.c",
                    "_4": 10,
                    "_5": "func1",
                }
            ],
            row_count=1,
        )

        # Mock sink node lookup
        sink_result = QueryResult(
            success=True,
            data=[
                {
                    "_1": 222,
                    "_2": "system(cmd)",
                    "_3": "file.c",
                    "_4": 20,
                    "_5": "func2",
                }
            ],
            row_count=1,
        )

        # Mock flow query
        flow_result = QueryResult(success=True, data=[], row_count=0)

        call_count = [0]

        async def mock_execute(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return source_result
            elif call_count[0] == 2:
                return sink_result
            else:
                return flow_result

        fake_services["query_executor"].execute_query.side_effect = mock_execute

        func = mcp.registered["find_taint_flows"]
        result = await func(
            session_id=ready_session.id,
            source_node_id="111",
            sink_node_id="222",
            max_path_length=5,
        )

        assert result["success"] is True
        assert result["flows"] == []
        assert result["total_flows"] == 0
