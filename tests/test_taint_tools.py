import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.tools.mcp_tools import register_tools
from src.models import Session, CPGConfig, Config, QueryResult


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
    ready_session = Session(id=ready_id, container_id="c1", source_type="local", source_path="/tmp", language="c", status="ready")
    session_manager.get_session = AsyncMock(return_value=ready_session)
    session_manager.touch_session = AsyncMock(return_value=None)

    # query executor mock
    query_executor = AsyncMock()

    # sample QueryResult structures matching tool expectations
    query_executor.execute_query = AsyncMock(return_value=QueryResult(
        success=True,
        data=[{"_1": 123, "_2": "getenv", "_3": "char *s = getenv(\"FOO\")", "_4": "core.c", "_5": 10, "_6": "main"}],
        row_count=1
    ))

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
    res = await func(session_id=fake_services['session_id'], language="c", limit=10)

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

    res = await func(session_id=fake_services['session_id'], language="c", limit=10)

    assert res.get("success") is True
    assert "sinks" in res
    assert isinstance(res["sinks"], list)
    assert res["total"] == 1


@pytest.mark.asyncio
async def test_find_taint_flows_success(fake_services):
    # For flows, adjust the mocked execute_query to return tuple-like fields
    services = fake_services
    services["query_executor"].execute_query = AsyncMock(return_value=QueryResult(
        success=True,
        data=[{"_1": "char *s = getenv(\"FOO\")", "_2": "core.c", "_3": 10, "_4": "system(cmd)", "_5": "core.c", "_6": 42, "_7": 3}],
        row_count=1
    ))

    mcp = FakeMCP()
    register_tools(mcp, services)

    func = mcp.registered.get("find_taint_flows")
    assert func is not None

    res = await func(session_id=fake_services['session_id'], timeout=10, limit=10)

    assert res.get("success") is True
    assert "flows" in res
    assert isinstance(res["flows"], list)
    assert res["total"] == 1
