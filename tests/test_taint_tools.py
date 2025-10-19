import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models import Config, CPGConfig, QueryResult, Session, SessionStatus
from src.tools.mcp_tools import register_tools


class FakeMCP:
    def __init__(self):
        self.registered = {}

    def tool(self):
        # decorator to register functions by name
        def _decorator(func):
            self.registered[func.__name__] = func
            return func

        return _decorator


@pytest.fixture
def fake_services():
    # session manager mock
    session_manager = AsyncMock()
    import uuid

    # create a ready session with valid UUID
    ready_id = str(uuid.uuid4())
    ready_session = Session(
        id=ready_id,
        container_id="c1",
        source_type="local",
        source_path="/tmp",
        language="c",
        status="ready",
    )
    session_manager.get_session = AsyncMock(return_value=ready_session)
    session_manager.touch_session = AsyncMock(return_value=None)

    # query executor mock
    query_executor = AsyncMock()

    # sample QueryResult structures matching tool expectations
    query_executor.execute_query = AsyncMock(
        return_value=QueryResult(
            success=True,
            data=[
                {
                    "_1": 123,
                    "_2": "getenv",
                    "_3": 'char *s = getenv("FOO")',
                    "_4": "core.c",
                    "_5": 10,
                    "_6": "main",
                }
            ],
            row_count=1,
        )
    )

    # config with taint lists
    cpg = CPGConfig()
    cpg.taint_sources = {"c": ["getenv", "fgets"]}
    cpg.taint_sinks = {"c": ["system", "popen"]}
    cfg = Config(cpg=cpg)

    services = {
        "session_manager": session_manager,
        "query_executor": query_executor,
        "config": cfg,
        "session_id": ready_id,
    }

    return services


@pytest.mark.asyncio
async def test_find_taint_sources_success(fake_services):
    mcp = FakeMCP()
    register_tools(mcp, fake_services)

    func = mcp.registered.get("find_taint_sources")
    assert func is not None

    # call the registered tool function
    res = await func(session_id=fake_services["session_id"], language="c", limit=10)

    assert res.get("success") is True
    assert "sources" in res
    assert isinstance(res["sources"], list)
    assert res["total"] == 1


@pytest.mark.asyncio
async def test_find_taint_sinks_success(fake_services):
    mcp = FakeMCP()
    register_tools(mcp, fake_services)

    func = mcp.registered.get("find_taint_sinks")
    assert func is not None

    res = await func(session_id=fake_services["session_id"], language="c", limit=10)

    assert res.get("success") is True
    assert "sinks" in res
    assert isinstance(res["sinks"], list)
    assert res["total"] == 1


@pytest.mark.asyncio
async def test_find_taint_flows_success(fake_services):
    # Setup mock for source, sink, and flow queries
    services = fake_services

    # Create side effect to return different results for 3 queries
    source_result = QueryResult(
        success=True,
        data=[
            {"_1": 1001, "_2": 'getenv("FOO")', "_3": "core.c", "_4": 10, "_5": "main"}
        ],
        row_count=1,
    )

    sink_result = QueryResult(
        success=True,
        data=[
            {"_1": 1002, "_2": "system(cmd)", "_3": "core.c", "_4": 42, "_5": "execute"}
        ],
        row_count=1,
    )

    flow_result = QueryResult(
        success=True,
        data=[
            {
                "_1": 0,
                "_2": 3,
                "_3": [
                    {"_1": 'getenv("FOO")', "_2": "core.c", "_3": 10, "_4": "CALL"},
                    {"_1": "cmd", "_2": "core.c", "_3": 25, "_4": "IDENTIFIER"},
                    {"_1": "system(cmd)", "_2": "core.c", "_3": 42, "_4": "CALL"},
                ],
            }
        ],
        row_count=1,
    )

    call_count = [0]

    async def mock_execute(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return source_result
        elif call_count[0] == 2:
            return sink_result
        else:
            return flow_result

    services["query_executor"].execute_query = AsyncMock(side_effect=mock_execute)
    services["session_manager"].get_session = AsyncMock(
        return_value=Session(
            id=services["session_id"],
            language="c",
            status=SessionStatus.READY.value,
            source_path="/path",
            source_type="local",
            created_at=datetime.now(timezone.utc),
            last_accessed=datetime.now(timezone.utc),
        )
    )

    mcp = FakeMCP()
    register_tools(mcp, services)

    func = mcp.registered.get("find_taint_flows")
    assert func is not None

    res = await func(
        session_id=services["session_id"],
        source_node_id="1001",
        sink_node_id="1002",
        timeout=10,
    )

    assert res.get("success") is True
    assert res["source"]["node_id"] == 1001
    assert res["sink"]["node_id"] == 1002
    assert "flows" in res
    assert isinstance(res["flows"], list)
