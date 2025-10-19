"""
Tests for query executor
"""

import asyncio
import json
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from src.exceptions import QueryExecutionError
from src.models import JoernConfig, QueryConfig, QueryResult
from src.services.query_executor import QueryExecutor, QueryStatus
from src.utils.redis_client import RedisClient


class TestQueryExecutor:
    """Test query executor functionality"""

    @pytest.fixture
    def query_config(self):
        """Query configuration fixture"""
        return QueryConfig(timeout=30, cache_enabled=True, cache_ttl=300)

    @pytest.fixture
    def joern_config(self):
        """Joern configuration fixture"""
        return JoernConfig()

    @pytest.fixture
    def mock_redis_client(self):
        """Mock Redis client fixture"""
        mock_client = AsyncMock(spec=RedisClient)
        # Mock get_cached_query to return None (no cache hit)
        mock_client.get_cached_query = AsyncMock(return_value=None)
        return mock_client

    @pytest.fixture
    def query_executor(self, query_config, joern_config, mock_redis_client):
        """Query executor fixture"""
        with patch("src.services.query_executor.docker.from_env") as mock_docker:
            mock_docker_client = MagicMock()
            mock_docker.return_value = mock_docker_client
            executor = QueryExecutor(query_config, joern_config, mock_redis_client)
            executor.docker_client = mock_docker_client  # Set it directly
            return executor

    def test_normalize_query_for_json_basic(self, query_executor):
        """Test basic query normalization"""
        result = query_executor._normalize_query_for_json("cpg.method")
        assert result == "cpg.method.toJsonPretty"

    def test_normalize_query_for_json_with_limit(self, query_executor):
        """Test query normalization with limit"""
        result = query_executor._normalize_query_for_json("cpg.method", limit=10)
        assert result == "cpg.method.take(10).toJsonPretty"

    def test_normalize_query_for_json_with_offset(self, query_executor):
        """Test query normalization with offset"""
        result = query_executor._normalize_query_for_json("cpg.method", offset=5)
        assert result == "cpg.method.drop(5).toJsonPretty"

    def test_normalize_query_for_json_with_offset_and_limit(self, query_executor):
        """Test query normalization with both offset and limit"""
        result = query_executor._normalize_query_for_json(
            "cpg.method", limit=10, offset=5
        )
        assert result == "cpg.method.drop(5).take(10).toJsonPretty"

    def test_normalize_query_for_json_remove_existing_modifiers(self, query_executor):
        """Test that existing modifiers are removed"""
        result = query_executor._normalize_query_for_json("cpg.method.take(20).toJson")
        assert result == "cpg.method.toJsonPretty"

    @pytest.mark.asyncio
    async def test_execute_query_success(self, query_executor):
        """Test successful query execution"""
        # Mock the container operations
        with patch.object(
            query_executor, "_get_container_id", return_value="container-123"
        ), patch.object(
            query_executor, "_ensure_cpg_loaded"
        ) as mock_ensure, patch.object(
            query_executor, "_execute_query_in_shell"
        ) as mock_execute:

            mock_ensure.return_value = None  # Do nothing
            mock_execute.return_value = QueryResult(
                success=True, data=[{"name": "test"}], row_count=1, execution_time=1.5
            )

            result = await query_executor.execute_query(
                session_id="test-session",
                cpg_path="/workspace/cpg.bin",
                query="cpg.method",
                timeout=30,
                limit=10,
            )

            assert result.success is True
            assert result.data == [{"name": "test"}]
            assert result.row_count == 1
            assert result.execution_time >= 0  # Just check it's a valid time

    @pytest.mark.asyncio
    async def test_execute_query_with_offset(self, query_executor):
        """Test query execution with offset"""
        with patch.object(
            query_executor, "_get_container_id", return_value="container-123"
        ), patch.object(
            query_executor, "_ensure_cpg_loaded"
        ) as mock_ensure, patch.object(
            query_executor, "_execute_query_in_shell"
        ) as mock_execute:

            mock_ensure.return_value = None
            mock_execute.return_value = QueryResult(
                success=True,
                data=[{"name": "method2"}, {"name": "method3"}],
                row_count=2,
                execution_time=1.0,
            )

            result = await query_executor.execute_query(
                session_id="test-session",
                cpg_path="/workspace/cpg.bin",
                query="cpg.method",
                timeout=30,
                limit=2,
                offset=1,
            )

            assert result.success is True
            assert len(result.data) == 2
            assert result.row_count == 2

            # Verify that the query was normalized with offset and limit
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            normalized_query = call_args[0][1]  # Second argument is the query
            assert "drop(1)" in normalized_query
            assert "take(2)" in normalized_query

    @pytest.mark.asyncio
    async def test_execute_query_invalid_query(self, query_executor):
        """Test query execution with invalid query"""
        with patch.object(
            query_executor, "_get_container_id", return_value="container-123"
        ), patch.object(
            query_executor, "_ensure_cpg_loaded"
        ) as mock_ensure, patch.object(
            query_executor, "_execute_query_in_shell"
        ) as mock_execute:

            mock_ensure.return_value = None
            mock_execute.return_value = QueryResult(
                success=False, error="Invalid query syntax", execution_time=0.5
            )

            result = await query_executor.execute_query(
                session_id="test-session",
                cpg_path="/workspace/cpg.bin",
                query="invalid query syntax",
                timeout=30,
            )

            assert result.success is False
            assert "Invalid query syntax" in result.error

    @pytest.mark.asyncio
    async def test_execute_query_no_container(self, query_executor):
        """Test query execution when no container is found"""
        with patch.object(query_executor, "_get_container_id", return_value=None):
            result = await query_executor.execute_query(
                session_id="test-session",
                cpg_path="/workspace/cpg.bin",
                query="cpg.method",
            )

            assert result.success is False
            assert "No container found" in result.error

    @pytest.mark.asyncio
    async def test_execute_query_async_success(self, query_executor):
        """Test successful async query execution"""
        with patch.object(
            query_executor, "_get_container_id", return_value="container-123"
        ), patch.object(query_executor, "_execute_query_background") as mock_background:

            query_id = await query_executor.execute_query_async(
                session_id="test-session",
                query="cpg.method",
                timeout=30,
                limit=10,
                offset=5,
            )

            assert isinstance(query_id, str)
            assert len(query_id) > 0

            # Verify query status was initialized
            assert query_id in query_executor.query_status
            status = query_executor.query_status[query_id]
            assert status["status"] == QueryStatus.PENDING.value
            assert status["session_id"] == "test-session"
            assert status["query"] == "cpg.method"

            # Verify background task was started
            mock_background.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_query_async_invalid_query(self, query_executor):
        """Test async query execution with invalid query"""
        # Mock validation to raise an exception
        with patch(
            "src.services.query_executor.validate_cpgql_query",
            side_effect=ValueError("Invalid query"),
        ):
            with pytest.raises(
                QueryExecutionError, match="Query initialization failed"
            ):
                await query_executor.execute_query_async(
                    session_id="test-session", query="invalid query"
                )

    @pytest.mark.asyncio
    async def test_get_query_status_found(self, query_executor):
        """Test getting status of existing query"""
        query_id = "test-query-id"
        query_executor.query_status[query_id] = {
            "status": QueryStatus.COMPLETED.value,
            "session_id": "test-session",
            "query": "cpg.method",
            "created_at": 1000.0,
            "completed_at": 1001.5,
            "started_at": 1000.5,
            "result": {
                "success": True,
                "data": [],
                "row_count": 0,
                "execution_time": 1.0,
            },
        }

        status = await query_executor.get_query_status(query_id)

        assert status["status"] == QueryStatus.COMPLETED.value
        assert status["execution_time"] == 1.0

    @pytest.mark.asyncio
    async def test_get_query_status_not_found(self, query_executor):
        """Test getting status of non-existent query"""
        with pytest.raises(QueryExecutionError, match="Query test-query-id not found"):
            await query_executor.get_query_status("test-query-id")

    @pytest.mark.asyncio
    async def test_get_query_result_completed(self, query_executor):
        """Test getting result of completed query"""
        query_id = "test-query-id"
        expected_result = QueryResult(
            success=True, data=[{"name": "test"}], row_count=1, execution_time=1.5
        )

        query_executor.query_status[query_id] = {
            "status": QueryStatus.COMPLETED.value,
            "session_id": "test-session",
            "query": "cpg.method",
            "result": expected_result.to_dict(),
        }

        result = await query_executor.get_query_result(query_id)

        assert result.success is True
        assert result.data == [{"name": "test"}]
        assert result.row_count == 1
        assert result.execution_time == 1.5

    @pytest.mark.asyncio
    async def test_get_query_result_failed(self, query_executor):
        """Test getting result of failed query"""
        query_id = "test-query-id"
        query_executor.query_status[query_id] = {
            "status": QueryStatus.FAILED.value,
            "session_id": "test-session",
            "query": "cpg.method",
            "error": "Query execution failed",
        }

        result = await query_executor.get_query_result(query_id)

        assert result.success is False
        assert result.error == "Query execution failed"

    @pytest.mark.asyncio
    async def test_get_query_result_not_completed(self, query_executor):
        """Test getting result of query that is not completed"""
        query_id = "test-query-id"
        query_executor.query_status[query_id] = {
            "status": QueryStatus.RUNNING.value,
            "session_id": "test-session",
            "query": "cpg.method",
        }

        with pytest.raises(
            QueryExecutionError, match="Query test-query-id is not completed yet"
        ):
            await query_executor.get_query_result(query_id)

    @pytest.mark.asyncio
    async def test_list_queries_all(self, query_executor):
        """Test listing all queries"""
        query_executor.query_status = {
            "query1": {"session_id": "session1", "status": "completed"},
            "query2": {"session_id": "session2", "status": "running"},
        }

        result = await query_executor.list_queries()

        assert len(result) == 2
        assert "query1" in result
        assert "query2" in result

    @pytest.mark.asyncio
    async def test_list_queries_by_session(self, query_executor):
        """Test listing queries for specific session"""
        query_executor.query_status = {
            "query1": {"session_id": "session1", "status": "completed"},
            "query2": {"session_id": "session2", "status": "running"},
            "query3": {"session_id": "session1", "status": "failed"},
        }

        result = await query_executor.list_queries("session1")

        assert len(result) == 2
        assert "query1" in result
        assert "query3" in result
        assert "query2" not in result

    @pytest.mark.asyncio
    async def test_cleanup_query_success(self, query_executor):
        """Test successful query cleanup"""
        query_id = "test-query-id"
        query_executor.query_status[query_id] = {
            "session_id": "test-session",
            "output_file": "/tmp/test.json",
            "status": "completed",
        }

        mock_container = MagicMock()
        mock_container.exec_run.return_value = MagicMock(exit_code=0)

        with patch.object(
            query_executor, "_get_container_id", return_value="container-123"
        ), patch.object(
            query_executor.docker_client.containers, "get", return_value=mock_container
        ):

            await query_executor.cleanup_query(query_id)

            # Verify query was removed
            assert query_id not in query_executor.query_status

            # Verify rm command was executed
            mock_container.exec_run.assert_called_once_with("rm -f /tmp/test.json")

    @pytest.mark.asyncio
    async def test_cleanup_old_queries(self, query_executor):
        """Test cleanup of old queries"""
        import time

        current_time = time.time()

        # Create queries with different ages
        query_executor.query_status = {
            "old_completed": {
                "status": QueryStatus.COMPLETED.value,
                "created_at": current_time - 4000,  # Old
                "completed_at": current_time - 3900,
            },
            "old_failed": {
                "status": QueryStatus.FAILED.value,
                "created_at": current_time - 4000,  # Old
                "completed_at": current_time - 3900,
            },
            "recent_running": {
                "status": QueryStatus.RUNNING.value,
                "created_at": current_time - 100,  # Recent
            },
        }

        with patch.object(query_executor, "cleanup_query") as mock_cleanup:
            await query_executor.cleanup_old_queries(max_age_seconds=3600)

            # Only old queries should be cleaned up
            assert mock_cleanup.call_count == 2
            mock_cleanup.assert_any_call("old_completed")
            mock_cleanup.assert_any_call("old_failed")

    @pytest.mark.asyncio
    async def test_close_session(self, query_executor):
        """Test closing session resources"""
        session_id = "test-session"
        query_executor.session_cpgs[session_id] = "/workspace/cpg.bin"
        query_executor.session_containers[session_id] = "container-123"

        await query_executor.close_session(session_id)

        # Verify resources were cleaned up
        assert session_id not in query_executor.session_cpgs
        assert session_id not in query_executor.session_containers

    @pytest.mark.asyncio
    async def test_cleanup_all(self, query_executor):
        """Test cleanup of all sessions and queries"""
        # Setup test data
        query_executor.query_status = {
            "query1": {"session_id": "session1"},
            "query2": {"session_id": "session2"},
        }
        query_executor.session_cpgs = {"session1": "/cpg1", "session2": "/cpg2"}

        with patch.object(
            query_executor, "cleanup_query"
        ) as mock_cleanup_query, patch.object(
            query_executor, "close_session"
        ) as mock_close_session:

            await query_executor.cleanup()

            # Verify all queries and sessions were cleaned up
            assert mock_cleanup_query.call_count == 2
            assert mock_close_session.call_count == 2

    # Test wrong/invalid queries
    @pytest.mark.asyncio
    async def test_execute_query_empty_query(self, query_executor):
        """Test execution with empty query"""
        result = await query_executor.execute_query(
            session_id="test-session", cpg_path="/workspace/cpg.bin", query=""
        )

        assert result.success is False
        assert "Query must be a non-empty string" in result.error

    @pytest.mark.asyncio
    async def test_execute_query_malformed_json_response(self, query_executor):
        """Test handling of malformed JSON response"""
        with patch.object(
            query_executor, "_get_container_id", return_value="container-123"
        ), patch.object(
            query_executor, "_ensure_cpg_loaded"
        ) as mock_ensure, patch.object(
            query_executor, "_execute_query_in_shell"
        ) as mock_execute:

            mock_ensure.return_value = None
            # Mock the execution to return malformed JSON
            mock_execute.return_value = QueryResult(
                success=True,
                data=[{"malformed": "json", "missing": "fields"}],
                row_count=1,
                execution_time=1.0,
            )

            result = await query_executor.execute_query(
                session_id="test-session",
                cpg_path="/workspace/cpg.bin",
                query="cpg.invalid",
            )

            # Should still succeed but with whatever data was parsed
            assert result.success is True
            assert len(result.data) == 1

    @pytest.mark.asyncio
    async def test_execute_query_with_negative_offset(self, query_executor):
        """Test query execution with negative offset"""
        with patch.object(
            query_executor, "_get_container_id", return_value="container-123"
        ), patch.object(
            query_executor, "_ensure_cpg_loaded"
        ) as mock_ensure, patch.object(
            query_executor, "_execute_query_in_shell"
        ) as mock_execute:

            mock_ensure.return_value = None
            mock_execute.return_value = QueryResult(
                success=True, data=[], row_count=0, execution_time=0.5
            )

            result = await query_executor.execute_query(
                session_id="test-session",
                cpg_path="/workspace/cpg.bin",
                query="cpg.method",
                offset=-1,  # Negative offset should be ignored
            )

            assert result.success is True
            # Verify that drop was not added for negative offset
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            normalized_query = call_args[0][1]
            assert "drop(" not in normalized_query

    @pytest.mark.asyncio
    async def test_execute_query_with_zero_offset(self, query_executor):
        """Test query execution with zero offset"""
        with patch.object(
            query_executor, "_get_container_id", return_value="container-123"
        ), patch.object(
            query_executor, "_ensure_cpg_loaded"
        ) as mock_ensure, patch.object(
            query_executor, "_execute_query_in_shell"
        ) as mock_execute:

            mock_ensure.return_value = None
            mock_execute.return_value = QueryResult(
                success=True,
                data=[{"name": "method1"}],
                row_count=1,
                execution_time=0.5,
            )

            result = await query_executor.execute_query(
                session_id="test-session",
                cpg_path="/workspace/cpg.bin",
                query="cpg.method",
                offset=0,  # Zero offset should be ignored
            )

            assert result.success is True
            # Verify that drop was not added for zero offset
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            normalized_query = call_args[0][1]
            assert "drop(" not in normalized_query

    @pytest.mark.asyncio
    async def test_execute_query_with_very_large_limit(self, query_executor):
        """Test query execution with very large limit"""
        with patch.object(
            query_executor, "_get_container_id", return_value="container-123"
        ), patch.object(
            query_executor, "_ensure_cpg_loaded"
        ) as mock_ensure, patch.object(
            query_executor, "_execute_query_in_shell"
        ) as mock_execute:

            mock_ensure.return_value = None
            mock_execute.return_value = QueryResult(
                success=True,
                data=[],  # Assume no results due to large limit
                row_count=0,
                execution_time=2.0,
            )

            result = await query_executor.execute_query(
                session_id="test-session",
                cpg_path="/workspace/cpg.bin",
                query="cpg.method",
                limit=1000000,  # Very large limit
            )

            assert result.success is True
            # Verify that take was added
            mock_execute.assert_called_once()
            call_args = mock_execute.call_args
            normalized_query = call_args[0][1]
            assert "take(1000000)" in normalized_query

    @pytest.mark.asyncio
    async def test_execute_query_timeout_handling(self, query_executor):
        """Test query execution timeout handling"""
        with patch.object(
            query_executor, "_get_container_id", return_value="container-123"
        ), patch.object(
            query_executor, "_ensure_cpg_loaded"
        ) as mock_ensure, patch.object(
            query_executor, "_execute_query_in_shell"
        ) as mock_execute:

            mock_ensure.return_value = None
            mock_execute.return_value = QueryResult(
                success=False,
                error="Query timed out",
                execution_time=35.0,  # Exceeded timeout
            )

            result = await query_executor.execute_query(
                session_id="test-session",
                cpg_path="/workspace/cpg.bin",
                query="cpg.method",
                timeout=30,
            )

            assert result.success is False
            assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_query_with_special_characters(self, query_executor):
        """Test query execution with special characters in query"""
        with patch.object(
            query_executor, "_get_container_id", return_value="container-123"
        ), patch.object(
            query_executor, "_ensure_cpg_loaded"
        ) as mock_ensure, patch.object(
            query_executor, "_execute_query_in_shell"
        ) as mock_execute:

            mock_ensure.return_value = None
            mock_execute.return_value = QueryResult(
                success=False,
                error="Syntax error near special characters",
                execution_time=0.1,
            )

            result = await query_executor.execute_query(
                session_id="test-session",
                cpg_path="/workspace/cpg.bin",
                # SQL injection-like
                query='cpg.method.name("test; DROP TABLE users; --")',
            )

            assert result.success is False
            assert "error" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_query_with_null_bytes(self, query_executor):
        """Test query execution with null bytes (potential security issue)"""
        with patch.object(
            query_executor, "_get_container_id", return_value="container-123"
        ), patch.object(query_executor, "_execute_query_in_shell") as mock_execute:

            mock_execute.return_value = QueryResult(
                success=False, error="Invalid characters in query", execution_time=0.1
            )

            result = await query_executor.execute_query(
                session_id="test-session",
                cpg_path="/workspace/cpg.bin",
                query="cpg.method\x00.name",  # Null byte injection
            )

            assert result.success is False

    @pytest.mark.asyncio
    async def test_execute_query_with_very_long_query(self, query_executor):
        """Test query execution with very long query string"""
        long_query = "cpg.method" + ".name" * 1000  # Very long query

        with patch.object(
            query_executor, "_get_container_id", return_value="container-123"
        ), patch.object(query_executor, "_execute_query_in_shell") as mock_execute:

            mock_execute.return_value = QueryResult(
                success=False, error="Query too long", execution_time=0.1
            )

            result = await query_executor.execute_query(
                session_id="test-session",
                cpg_path="/workspace/cpg.bin",
                query=long_query,
            )

            # Should handle gracefully
            assert isinstance(result, QueryResult)

    @pytest.mark.asyncio
    async def test_execute_query_async_cache_hit(
        self, query_executor, mock_redis_client
    ):
        """Test async query execution with cache hit"""
        # Setup mock to return cached result
        cached_result = {
            "success": True,
            "data": [{"name": "cached_method"}],
            "row_count": 1,
            "execution_time": 0.1,
        }
        mock_redis_client.get_cached_query = AsyncMock(return_value=cached_result)
        mock_redis_client.cache_query_result = AsyncMock()

        with patch.object(
            query_executor, "_get_container_id", return_value="container-123"
        ), patch.object(query_executor, "_execute_query_in_shell") as mock_execute:

            # Start async query
            query_id = await query_executor.execute_query_async(
                session_id="test-session", query="cpg.method", timeout=30
            )

            # Manually run the background task (since create_task is mocked in other tests)
            # Get the query status to find the normalized query
            status = query_executor.query_status[query_id]
            query_normalized = query_executor._normalize_query_for_json("cpg.method")
            query_with_pipe = f'{query_normalized} #> "/tmp/query_{query_id}.json"'

            # Execute background task directly
            await query_executor._execute_query_background(
                query_id, "test-session", query_with_pipe, 30
            )

            # Verify query completed with cached result
            status = await query_executor.get_query_status(query_id)
            assert status["status"] == QueryStatus.COMPLETED.value

            result = await query_executor.get_query_result(query_id)
            assert result.success is True
            assert result.data == [{"name": "cached_method"}]
            assert result.row_count == 1

            # Verify that actual query execution was NOT called
            mock_execute.assert_not_called()

            # Verify cache was checked
            mock_redis_client.get_cached_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_query_async_cache_miss_and_store(
        self, query_executor, mock_redis_client
    ):
        """Test async query execution with cache miss and result storage"""
        # Setup mock to return no cached result initially
        mock_redis_client.get_cached_query = AsyncMock(return_value=None)
        mock_redis_client.cache_query_result = AsyncMock()

        with patch.object(
            query_executor, "_get_container_id", return_value="container-123"
        ), patch.object(query_executor, "_execute_query_in_shell") as mock_execute:

            mock_execute.return_value = QueryResult(
                success=True,
                data=[{"name": "executed_method"}],
                row_count=1,
                execution_time=1.5,
            )

            # Start async query
            query_id = await query_executor.execute_query_async(
                session_id="test-session", query="cpg.method", timeout=30
            )

            # Execute background task directly
            status = query_executor.query_status[query_id]
            query_normalized = query_executor._normalize_query_for_json("cpg.method")
            query_with_pipe = f'{query_normalized} #> "/tmp/query_{query_id}.json"'

            await query_executor._execute_query_background(
                query_id, "test-session", query_with_pipe, 30
            )

            # Verify query completed
            status = await query_executor.get_query_status(query_id)
            assert status["status"] == QueryStatus.COMPLETED.value

            result = await query_executor.get_query_result(query_id)
            assert result.success is True
            assert result.data == [{"name": "executed_method"}]
            assert result.row_count == 1

            # Verify that actual query execution was called
            mock_execute.assert_called_once()

            # Verify cache was checked and result was stored
            mock_redis_client.get_cached_query.assert_called_once()
            mock_redis_client.cache_query_result.assert_called_once()
