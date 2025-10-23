"""
Code Browsing MCP Tools for Joern MCP Server
Tools for exploring and navigating codebase structure
"""

import logging
import os
import re
from typing import Any, Dict, Optional

from ..exceptions import (
    SessionNotFoundError,
    SessionNotReadyError,
    ValidationError,
)
from ..models import SessionStatus
from ..utils.validators import validate_session_id

logger = logging.getLogger(__name__)


def register_code_browsing_tools(mcp, services: dict):
    """Register code browsing MCP tools with the FastMCP server"""


    @mcp.tool()
    async def list_methods(
        session_id: str,
        name_pattern: Optional[str] = None,
        file_pattern: Optional[str] = None,
        callee_pattern: Optional[str] = None,
        include_external: bool = False,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        List methods/functions in the codebase.

        Discover all methods and functions defined in the analyzed code. This is
        essential for understanding the codebase structure and finding specific
        functions to analyze.

        Args:
            session_id: The session ID from create_cpg_session
            name_pattern: Optional regex to filter method names (e.g., ".*authenticate.*")
            file_pattern: Optional regex to filter by file path
            callee_pattern: Optional regex to filter for methods that call a specific function
                (e.g., "memcpy|free|malloc")
            include_external: Include external/library methods (default: false)
            limit: Maximum number of results to return. This can be overridden. Default is 100.

        Returns:
            {
                "success": true,
                "methods": [
                    {
                        "node_id": "12345",
                        "name": "main",
                    }
                ],
                "total": 1
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Build query with filters
            query_parts = ["cpg.method"]

            if not include_external:
                query_parts.append(".isExternal(false)")

            if name_pattern:
                query_parts.append(f'.name("{name_pattern}")')

            if file_pattern:
                query_parts.append(f'.where(_.file.name("{file_pattern}"))')

            if callee_pattern:
                query_parts.append(f'.where(_.callOut.name("{callee_pattern}"))')

            query_parts.append(
                ".map(m => (m.name, m.id, m.fullName, m.signature, m.filename, m.lineNumber.getOrElse(-1), m.isExternal))"
            )

            query = "".join(query_parts) + f".dedup.take({limit}).l"

            logger.info(f"list_methods query: {query}")

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=limit,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            methods = []
            logger.info(f"Raw result data: {result.data[:3]}")  # Debug logging
            for item in result.data:
                # Map tuple fields: _1=id, _2=name, _3=fullName, _4=signature,
                # _5=filename, _6=lineNumber, _7=isExternal
                if isinstance(item, dict):
                    methods.append(
                        {
                            "node_id": str(item.get("_1", "")),
                            "name": item.get("_2", ""),
                            "fullName": item.get("_3", ""),
                            "signature": item.get("_4", ""),
                            "filename": item.get("_5", ""),
                            "lineNumber": item.get("_6", -1),
                            "isExternal": item.get("_7", False),
                        }
                    )

            return {"success": True, "methods": methods, "total": len(methods)}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error listing methods: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def get_method_source(
        session_id: str, method_name: str, filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get the source code of a specific method.

        Retrieve the actual source code for a method to understand its implementation.
        Useful when you need to examine the details of a specific function.

        Args:
            session_id: The session ID from create_cpg_session
            method_name: Name of the method (can be regex pattern)
            filename: Optional filename to disambiguate methods with same name

        Returns:
            {
                "success": true,
                "methods": [
                    {
                        "name": "main",
                        "filename": "main.c",
                        "lineNumber": 10,
                        "lineNumberEnd": 20,
                        "code": "int main() {\n    printf(\"Hello\");\n    return 0;\n}"
                    }
                ],
                "total": 1
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Build query to get method metadata
            query_parts = [f'cpg.method.name("{method_name}")']

            if filename:
                query_parts.append(f'.filename(".*{filename}.*")')

            query_parts.append(
                ".map(m => (m.name, m.filename, m.lineNumber.getOrElse(-1), m.lineNumberEnd.getOrElse(-1)))"
            )
            query = "".join(query_parts) + ".toJsonPretty"

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=10,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            methods = []
            method_name_result = ""
            method_filename = ""
            line_number = -1
            line_number_end = -1

            for item in result.data:
                if isinstance(item, dict):
                    method_name_result = item.get("_1", "")
                    method_filename = item.get("_2", "")
                    line_number = item.get("_3", -1)
                    line_number_end = item.get("_4", -1)

            # Get the full source code using file reading logic
            if method_filename and line_number > 0 and line_number_end > 0:
                try:
                    # Get playground path
                    playground_path = os.path.abspath(
                        os.path.join(
                            os.path.dirname(__file__), "..", "..", "playground"
                        )
                    )

                    # Get source directory from session
                    if session.source_type == "github":
                        # For GitHub repos, use the cached directory
                        from .core_tools import get_cpg_cache_key
                        cpg_cache_key = get_cpg_cache_key(
                            session.source_type, session.source_path, session.language
                        )
                        source_dir = os.path.join(
                            playground_path, "codebases", cpg_cache_key
                        )
                    else:
                        # For local paths, use the session source path directly
                        source_path = session.source_path
                        if not os.path.isabs(source_path):
                            source_path = os.path.abspath(source_path)
                        source_dir = source_path

                    # Construct full file path
                    file_path = os.path.join(source_dir, method_filename)

                    # Check if file exists and read it
                    if os.path.exists(file_path) and os.path.isfile(file_path):
                        with open(
                            file_path, "r", encoding="utf-8", errors="replace"
                        ) as f:
                            lines = f.readlines()

                        # Validate line numbers
                        total_lines = len(lines)
                        if (
                            line_number <= total_lines
                            and line_number_end >= line_number
                        ):
                            # Extract the code snippet (lines are 0-indexed in the list)
                            actual_end_line = min(line_number_end, total_lines)
                            code_lines = lines[line_number - 1: actual_end_line]
                            full_code = "".join(code_lines)
                        else:
                            full_code = f"// Invalid line range: {line_number}-{
                                line_number_end}, file has {total_lines} lines"
                    else:
                        full_code = f"// Source file not found: {method_filename}"
                except Exception as e:
                    full_code = f"// Error reading source file: {str(e)}"
            else:
                full_code = "// Unable to determine line range for method"

            methods.append(
                {
                    "name": method_name_result,
                    "filename": method_filename,
                    "lineNumber": line_number,
                    "lineNumberEnd": line_number_end,
                    "code": full_code,
                }
            )

            return {"success": True, "methods": methods, "total": len(methods)}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error getting method source: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def list_calls(
        session_id: str,
        caller_pattern: Optional[str] = None,
        callee_pattern: Optional[str] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        List function/method calls in the codebase.

        Discover call relationships between functions. Essential for understanding
        control flow and dependencies in the code.

        Args:
            session_id: The session ID from create_cpg_session
            caller_pattern: Optional regex to filter caller method names
            callee_pattern: Optional regex to filter callee method names
            limit: Maximum number of results (default: 100)

        Returns:
            {
                "success": true,
                "calls": [
                    {
                        "caller": "main",
                        "callee": "helper",
                        "code": "helper(x)",
                        "filename": "main.c",
                        "lineNumber": 15
                    }
                ],
                "total": 1
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Build query
            query_parts = ["cpg.call"]

            if callee_pattern:
                query_parts.append(f'.name("{callee_pattern}")')

            if caller_pattern:
                query_parts.append(f'.where(_.method.name("{caller_pattern}"))')

            query_parts.append(
                ".map(c => (c.method.name, c.name, c.code, c.method.filename, c.lineNumber.getOrElse(-1)))"
            )

            query = "".join(query_parts) + f".dedup.take({limit}).toJsonPretty"

            logger.info(f"list_calls query: {query}")

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=limit,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            calls = []
            for item in result.data:
                if isinstance(item, dict):
                    calls.append(
                        {
                            "caller": item.get("_1", ""),
                            "callee": item.get("_2", ""),
                            "code": item.get("_3", ""),
                            "filename": item.get("_4", ""),
                            "lineNumber": item.get("_5", -1),
                        }
                    )

            return {"success": True, "calls": calls, "total": len(calls)}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error listing calls: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def get_call_graph(
        session_id: str, method_name: str, depth: int = 5, direction: str = "outgoing"
    ) -> Dict[str, Any]:
        """
        Get the call graph for a specific method.

        Understand what functions a method calls (outgoing) or what functions
        call it (incoming). Essential for impact analysis and understanding
        code dependencies.

        Args:
            session_id: The session ID from create_cpg_session
            method_name: Name of the method to analyze (can be regex)
            depth: How many levels deep to traverse (default: 5, max recommended: 10)
            direction: "outgoing" (callees) or "incoming" (callers)

        Returns:
            {
                "success": true,
                "root_method": "authenticate",
                "direction": "outgoing",
                "calls": [
                    {"from": "authenticate", "to": "validate_password", "depth": 1},
                    {"from": "validate_password", "to": "hash_password", "depth": 2}
                ],
                "total": 2
            }
        """
        try:
            validate_session_id(session_id)

            if depth < 1 and depth > 15:
                raise ValidationError("Depth must be at least 1")

            if direction not in ["outgoing", "incoming"]:
                raise ValidationError("Direction must be 'outgoing' or 'incoming'")

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Build query based on direction
            # Escape the method name for regex matching
            method_escaped = method_name.replace("\\", "\\\\").replace("\"", "\\\"")

            if direction == "outgoing":
                # Simpler one-liner approach for outgoing calls (what method calls)
                # For depth 1: direct callees
                # For depth 2: direct callees + their callees (avoiding cycles)
                if depth == 1:
                    query = (
                        f'cpg.method.name("{method_escaped}").headOption.map(m => '
                        f'm.call.callee.filterNot(_.name.startsWith("<operator>")).map(c => (m.name, c.name, 1)).l).getOrElse(List()).toJsonPretty'
                    )
                else:
                    # For depth > 1, use inline BFS with braces to ensure proper parsing
                    query = f"""{{
val rootMethod = cpg.method.name("{method_escaped}").l
if (rootMethod.nonEmpty) {{
  val rootName = rootMethod.head.name
  var allCalls = scala.collection.mutable.ListBuffer[(String, String, Int)]()
  var toVisit = scala.collection.mutable.Queue[(io.shiftleft.codepropertygraph.generated.nodes.Method, Int)]()
  var visited = Set[String]()
  toVisit.enqueue((rootMethod.head, 0))
  while (toVisit.nonEmpty) {{
    val (current, currentDepth) = toVisit.dequeue()
    val currentName = current.name
    if (!visited.contains(currentName) && currentDepth < {depth}) {{
      visited = visited + currentName
      val callees = current.call.callee.l
      for (callee <- callees) {{
        val calleeName = callee.name
        if (!calleeName.startsWith("<operator>")) {{
          allCalls += ((currentName, calleeName, currentDepth + 1))
          if (!visited.contains(calleeName)) {{
            toVisit.enqueue((callee, currentDepth + 1))
          }}
        }}
      }}
    }}
  }}
  allCalls.toList
}} else List[(String, String, Int)]()
}}.toJsonPretty"""
            else:  # incoming
                # Simpler one-liner approach for incoming calls (what calls this method)
                # For depth 1: direct callers
                # For depth 2: direct callers + their callers (avoiding cycles)
                if depth == 1:
                    query = (
                        f'cpg.method.name("{method_escaped}").headOption.map(m => '
                        f'm.caller.filterNot(_.name.startsWith("<operator>")).map(c => (c.name, m.name, 1)).l).getOrElse(List()).toJsonPretty'
                    )
                else:
                    # For depth > 1, use inline BFS with braces to ensure proper parsing
                    query = f"""{{
val targetMethod = cpg.method.name("{method_escaped}").l
if (targetMethod.nonEmpty) {{
  val targetName = targetMethod.head.name
  var allCallers = scala.collection.mutable.ListBuffer[(String, String, Int)]()
  var toVisit = scala.collection.mutable.Queue[(io.shiftleft.codepropertygraph.generated.nodes.Method, Int)]()
  var visited = Set[String]()
  val directCallers = targetMethod.head.caller.l
  for (caller <- directCallers) {{
    allCallers += ((caller.name, targetName, 1))
    toVisit.enqueue((caller, 1))
  }}
  while (toVisit.nonEmpty) {{
    val (current, currentDepth) = toVisit.dequeue()
    val currentName = current.name
    if (!visited.contains(currentName) && currentDepth < {depth}) {{
      visited = visited + currentName
      val incomingCallers = current.caller.l
      for (caller <- incomingCallers) {{
        val callerName = caller.name
        if (!callerName.startsWith("<operator>")) {{
          allCallers += ((callerName, targetName, currentDepth + 1))
          if (!visited.contains(callerName)) {{
            toVisit.enqueue((caller, currentDepth + 1))
          }}
        }}
      }}
    }}
  }}
  allCallers.toList
}} else List[(String, String, Int)]()
}}.toJsonPretty"""

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=120,
                limit=500,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            calls = []
            for item in result.data:
                if isinstance(item, dict):
                    calls.append(
                        {
                            "from": item.get("_1", ""),
                            "to": item.get("_2", ""),
                            "depth": item.get("_3", 1),
                        }
                    )

            return {
                "success": True,
                "root_method": method_name,
                "direction": direction,
                "calls": calls,
                "total": len(calls),
            }

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error getting call graph: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def list_parameters(session_id: str, method_name: str) -> Dict[str, Any]:
        """
        List parameters of a specific method.

        Get detailed information about method parameters including their names,
        types, and order. Useful for understanding function signatures.

        Args:
            session_id: The session ID from create_cpg_session
            method_name: Name of the method (can be regex pattern)

        Returns:
            {
                "success": true,
                "methods": [
                    {
                        "method": "authenticate",
                        "parameters": [
                            {"name": "username", "type": "string", "index": 1},
                            {"name": "password", "type": "string", "index": 2}
                        ]
                    }
                ],
                "total": 1
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            query = (
                f'cpg.method.name("{
                    method_name}").map(m => (m.name, m.parameter.map(p => '
                f"(p.name, p.typeFullName, p.index)).l)).toJsonPretty"
            )

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=10,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            methods = []
            for item in result.data:
                if isinstance(item, dict) and "_1" in item and "_2" in item:
                    params = []
                    param_list = item.get("_2", [])

                    for param_data in param_list:
                        if isinstance(param_data, dict):
                            params.append(
                                {
                                    "name": param_data.get("_1", ""),
                                    "type": param_data.get("_2", ""),
                                    "index": param_data.get("_3", -1),
                                }
                            )

                    methods.append({"method": item.get("_1", ""), "parameters": params})

            return {"success": True, "methods": methods, "total": len(methods)}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error listing parameters: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def find_literals(
        session_id: str,
        pattern: Optional[str] = None,
        literal_type: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Find literal values in the code (strings, numbers, etc).

        Search for hardcoded values like strings, numbers, or constants.
        Useful for finding configuration values, API keys, URLs, or
        magic numbers in the code.

        Args:
            session_id: The session ID from create_cpg_session
            pattern: Optional regex to filter literal values (e.g., ".*password.*")
            literal_type: Optional type filter (e.g., "string", "int")
            limit: Maximum number of results (default: 50)

        Returns:
            {
                "success": true,
                "literals": [
                    {
                        "value": "admin_password",
                        "type": "string",
                        "filename": "config.c",
                        "lineNumber": 42,
                        "method": "init_config"
                    }
                ],
                "total": 1
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Build query
            query_parts = ["cpg.literal"]

            if pattern:
                query_parts.append(f'.code("{pattern}")')

            if literal_type:
                query_parts.append(f'.typeFullName(".*{literal_type}.*")')

            query_parts.append(
                ".map(lit => (lit.code, lit.typeFullName, lit.filename, lit.lineNumber.getOrElse(-1), lit.method.name))"
            )
            query = "".join(query_parts) + f".take({limit})"

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=limit,  # Use the limit parameter
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            literals = []
            for item in result.data:
                if isinstance(item, dict):
                    literals.append(
                        {
                            "value": item.get("_1", ""),
                            "type": item.get("_2", ""),
                            "filename": item.get("_3", ""),
                            "lineNumber": item.get("_4", -1),
                            "method": item.get("_5", ""),
                        }
                    )

            return {"success": True, "literals": literals, "total": len(literals)}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error finding literals: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def get_codebase_summary(session_id: str) -> Dict[str, Any]:
        """
        Get a high-level summary of the codebase structure.

        Provides an overview including file count, method count, language,
        and other metadata. Useful as a first step when exploring a new codebase.

        Args:
            session_id: The session ID from create_cpg_session

        Returns:
            {
                "success": true,
                "summary": {
                    "language": "C",
                    "total_files": 15,
                    "total_methods": 127,
                    "total_calls": 456,
                    "external_methods": 89,
                    "lines_of_code": 5432
                }
            }
        """
        try:
            validate_session_id(session_id)

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Get metadata
            meta_query = "cpg.metaData.map(m => (m.language, m.version)).toJsonPretty"
            meta_result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=meta_query,
                timeout=10,
                limit=1,
            )

            language = "unknown"
            if meta_result.success and meta_result.data:
                item = meta_result.data[0]
                if isinstance(item, dict):
                    language = item.get("_1", "unknown")

            # Get counts
            stats_query = """
            cpg.metaData.map(_ => (
                cpg.file.size,
                cpg.method.size,
                cpg.method.isExternal(false).size,
                cpg.call.size,
                cpg.literal.size
            )).toJsonPretty
            """

            stats_result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=stats_query,
                timeout=30,
                limit=1,
            )

            summary = {
                "language": language,
                "total_files": 0,
                "total_methods": 0,
                "user_defined_methods": 0,
                "total_calls": 0,
                "total_literals": 0,
            }

            if stats_result.success and stats_result.data:
                item = stats_result.data[0]
                if isinstance(item, dict):
                    summary["total_files"] = item.get("_1", 0)
                    summary["total_methods"] = item.get("_2", 0)
                    summary["user_defined_methods"] = item.get("_3", 0)
                    summary["total_calls"] = item.get("_4", 0)
                    summary["total_literals"] = item.get("_5", 0)
                    summary["external_methods"] = (
                        summary["total_methods"] - summary["user_defined_methods"]
                    )

            return {"success": True, "summary": summary}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error getting codebase summary: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def get_code_snippet(
        session_id: str, filename: str, start_line: int, end_line: int
    ) -> Dict[str, Any]:
        """
        Retrieve a code snippet from a specific file with line range.

        Get the source code from a file between specified start and end line numbers.
        Useful for examining specific parts of the codebase.

        Args:
            session_id: The session ID from create_cpg_session
            filename: Name of the file to retrieve code from (relative to source root)
            start_line: Starting line number (1-indexed)
            end_line: Ending line number (1-indexed, inclusive)

        Returns:
            {
                "success": true,
                "filename": "main.c",
                "start_line": 10,
                "end_line": 20,
                "code": "example code here"
            }
        """
        try:
            validate_session_id(session_id)

            if start_line < 1 or end_line < start_line:
                raise ValidationError(
                    "Invalid line range: start_line must be >= 1 and end_line >= start_line"
                )

            session_manager = services["session_manager"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Get playground path
            playground_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "..", "playground")
            )

            # Get source directory from session
            if session.source_type == "github":
                # For GitHub repos, use the cached directory
                from .core_tools import get_cpg_cache_key
                cpg_cache_key = get_cpg_cache_key(
                    session.source_type, session.source_path, session.language
                )
                source_dir = os.path.join(playground_path, "codebases", cpg_cache_key)
            else:
                # For local paths, use the session source path directly
                source_path = session.source_path
                if not os.path.isabs(source_path):
                    source_path = os.path.abspath(source_path)
                source_dir = source_path

            # Construct full file path
            file_path = os.path.join(source_dir, filename)

            # Check if file exists
            if not os.path.exists(file_path):
                raise ValidationError(
                    f"File '{filename}' not found in source directory"
                )

            if not os.path.isfile(file_path):
                raise ValidationError(f"'{filename}' is not a file")

            # Read the file
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            # Validate line numbers
            total_lines = len(lines)
            if start_line > total_lines:
                raise ValidationError(
                    f"start_line {start_line} exceeds file length {total_lines}"
                )

            if end_line > total_lines:
                end_line = total_lines

            # Extract the code snippet (lines are 0-indexed in the list)
            code_lines = lines[start_line - 1: end_line]
            code = "".join(code_lines)

            return {
                "success": True,
                "filename": filename,
                "start_line": start_line,
                "end_line": end_line,
                "code": code,
            }

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error getting code snippet: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }
    @mcp.tool()
    async def find_bounds_checks(
        session_id: str, buffer_access_location: str
    ) -> Dict[str, Any]:
        """
        Find bounds checks near buffer access.

        Verify if buffer accesses have corresponding bounds checks by analyzing
        comparison operations involving the index variable. This helps identify
        potential buffer overflow vulnerabilities where bounds checks are missing
        or happen after the access.

        Args:
            session_id: The session ID from create_cpg_session
            buffer_access_location: Location of buffer access in format "filename:line"
                                  (e.g., "parser.c:3393")

        Returns:
            {
                "success": true,
                "buffer_access": {
                    "line": 3393,
                    "code": "buf[len++] = c",
                    "buffer": "buf",
                    "index": "len++"
                },
                "bounds_checks": [
                    {
                        "line": 3396,
                        "code": "if (len >= XML_MAX_NAMELEN)",
                        "checked_variable": "len",
                        "bound": "XML_MAX_NAMELEN",
                        "operator": ">=",
                        "position": "AFTER_ACCESS"
                    }
                ],
                "check_before_access": false,
                "check_after_access": true
            }
        """
        try:
            validate_session_id(session_id)

            # Parse the buffer access location
            if ":" not in buffer_access_location:
                raise ValidationError(
                    "buffer_access_location must be in format 'filename:line'"
                )

            filename, line_str = buffer_access_location.rsplit(":", 1)
            try:
                line_num = int(line_str)
            except ValueError:
                raise ValidationError(f"Invalid line number: {line_str}")

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Build the Joern query to find buffer access and bounds checks
            # Use raw string to avoid escaping issues
            # Wrap in braces to avoid REPL line-by-line interpretation issues
            query_template = r"""{
def escapeJson(s: String): String = {
s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
}
val bufferAccessOpt = cpg.call.name("<operator>.indirectIndexAccess").where(_.file.name(".*FILENAME_PLACEHOLDER")).lineNumber(LINE_NUM_PLACEHOLDER).headOption
bufferAccessOpt match {
case Some(bufferAccess) =>
val accessLine = bufferAccess.lineNumber.getOrElse(0)
val args = bufferAccess.argument.l
val bufferName = if (args.nonEmpty) args.head.code else "unknown"
val indexExpr = if (args.size > 1) args.last.code else "unknown"
val indexVar = indexExpr.replaceAll("[^a-zA-Z0-9_].*", "")
val method = bufferAccess.method
val comparisons = method.call.name("<operator>.(lessThan|greaterThan|lessEqualsThan|greaterEqualsThan)").filter { cmp => val args = cmp.argument.code.l; args.exists(_.contains(indexVar)) }.l
val boundsChecksJson = comparisons.map { cmp =>
val cmpLine = cmp.lineNumber.getOrElse(0)
val position = if (cmpLine < accessLine) "BEFORE_ACCESS" else if (cmpLine > accessLine) "AFTER_ACCESS" else "SAME_LINE"
val args = cmp.argument.l
val leftArg = if (args.nonEmpty) args.head.code else "?"
val rightArg = if (args.size > 1) args.last.code else "?"
val operator = cmp.name match { case "<operator>.lessThan" => "<"; case "<operator>.greaterThan" => ">"; case "<operator>.lessEqualsThan" => "<="; case "<operator>.greaterEqualsThan" => ">="; case _ => "?" }
"{\"line\":" + cmpLine + ",\"code\":\"" + escapeJson(cmp.code) + "\",\"checked_variable\":\"" + escapeJson(leftArg) + "\",\"bound\":\"" + escapeJson(rightArg) + "\",\"operator\":\"" + operator + "\",\"position\":\"" + position + "\"}"
}.mkString(",")
val checkBefore = comparisons.exists { cmp => val cmpLine = cmp.lineNumber.getOrElse(0); cmpLine < accessLine }
val checkAfter = comparisons.exists { cmp => val cmpLine = cmp.lineNumber.getOrElse(0); cmpLine > accessLine }
"{\"success\":true,\"buffer_access\":{\"line\":" + accessLine + ",\"code\":\"" + escapeJson(bufferAccess.code) + "\",\"buffer\":\"" + escapeJson(bufferName) + "\",\"index\":\"" + escapeJson(indexExpr) + "\"},\"bounds_checks\":[" + boundsChecksJson + "],\"check_before_access\":" + checkBefore + ",\"check_after_access\":" + checkAfter + "}"
case None =>
"{\"success\":false,\"error\":{\"code\":\"NOT_FOUND\",\"message\":\"No buffer access found at FILENAME_PLACEHOLDER:LINE_NUM_PLACEHOLDER\"}}"
}
}"""
            
            query = query_template.replace("FILENAME_PLACEHOLDER", filename).replace("LINE_NUM_PLACEHOLDER", str(line_num))

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            # Parse the JSON result
            import json

            if isinstance(result.data, list) and len(result.data) > 0:
                result_data = result.data[0]
                
                # Handle JSON string response from upickle.write
                if isinstance(result_data, str):
                    return json.loads(result_data)
                else:
                    return result_data
            else:
                return {
                    "success": False,
                    "error": {
                        "code": "NO_RESULT",
                        "message": "Query returned no results",
                    },
                }

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error finding bounds checks: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }
