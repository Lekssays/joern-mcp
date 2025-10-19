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
    async def list_files(
        session_id: str, pattern: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        List all source files in the analyzed codebase as a file tree.

        This tool helps discover the structure of the codebase by listing all files
        that were analyzed. Useful for understanding project layout and finding
        specific files of interest. Directories with more than 20 files will be truncated.

        Args:
            session_id: The session ID from create_cpg_session
            pattern: Optional regex pattern to filter file paths (e.g., ".*\\.java$" for Java files)

        Returns:
            {
                "success": true,
                "tree": {
                    "src": {
                        "main.py": None,
                        "api": { ... }
                    }
                },
                "total": 15
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

            # Query for all file paths
            query = "cpg.file.name.l"
            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=30,
                limit=10000,  # High limit for file listing
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            file_paths = result.data

            # Apply pattern filter if provided
            if pattern:
                file_paths = [p for p in file_paths if re.search(pattern, p)]

            # Build the file tree
            tree = {}
            for path in file_paths:
                parts = path.split("/")
                # Filter out empty parts that can result from leading slashes
                parts = [part for part in parts if part]

                current_level = tree
                for i, part in enumerate(parts):
                    if i == len(parts) - 1:
                        # It's a file
                        current_level[part] = None
                    else:
                        # It's a directory
                        if part not in current_level:
                            current_level[part] = {}
                        current_level = current_level[part]

            # Function to truncate large directories (only truncate subfolders, not
            # base level)
            def truncate_tree(node, is_base_level=True):
                if isinstance(node, dict):
                    if not is_base_level and len(node) > 20:
                        # Only truncate if we're not at the base level
                        keys = sorted(node.keys())
                        truncated_node = {
                            key: truncate_tree(node[key], False) for key in keys[:20]
                        }
                        truncated_node[f"... ({len(node) - 20} more files)"] = None
                        return truncated_node
                    else:
                        # For base level or smaller directories, show all entries
                        return {
                            key: truncate_tree(value, False)
                            for key, value in node.items()
                        }
                return node

            truncated_tree_structure = truncate_tree(tree, True)

            return {
                "success": True,
                "tree": truncated_tree_structure,
                "total": len(file_paths),
            }

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error listing files: {e}")
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
        session_id: str, method_name: str, depth: int = 2, direction: str = "outgoing"
    ) -> Dict[str, Any]:
        """
        Get the call graph for a specific method.

        Understand what functions a method calls (outgoing) or what functions
        call it (incoming). Essential for impact analysis and understanding
        code dependencies.

        Args:
            session_id: The session ID from create_cpg_session
            method_name: Name of the method to analyze (can be regex)
            depth: How many levels deep to traverse (1-3, default: 2)
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

            if depth < 1 or depth > 3:
                raise ValidationError("Depth must be between 1 and 3")

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
            method_escaped = re.escape(method_name)

            if direction == "outgoing":
                # Use depth-independent BFS traversal for call graph expansion
                # Traverse caller -> calls -> callee for arbitrary depth
                query = (
                    f'val rootMethod = cpg.method.name("{method_escaped}").l\n'
                    f"if (rootMethod.nonEmpty) {{\n"
                    f"  val rootName = rootMethod.head.name\n"
                    f"  var allCalls = scala.collection.mutable.ListBuffer[(String, String, Int)]()\n"
                    f"  var toVisit = scala.collection.mutable.Queue[(io.shiftleft.codepropertygraph.generated.nodes.Method, Int)]()\n"
                    f"  var visited = Set[String]()\n"
                    f"  \n"
                    f"  toVisit.enqueue((rootMethod.head, 0))\n"
                    f"  \n"
                    f"  while (toVisit.nonEmpty) {{\n"
                    f"    val (current, currentDepth) = toVisit.dequeue()\n"
                    f"    val currentName = current.name\n"
                    f"    \n"
                    f"    if (!visited.contains(currentName) && currentDepth < {
                        depth}) {{\n"
                    f"      visited = visited + currentName\n"
                    f"      val callees = current.call.callee.l\n"
                    f"      \n"
                    f"      for (callee <- callees) {{\n"
                    f"        val calleeName = callee.name\n"
                    f'        if (!calleeName.startsWith("<operator>")) {{\n'
                    f"          allCalls += ((currentName, calleeName, currentDepth + 1))\n"
                    f"          if (!visited.contains(calleeName)) {{\n"
                    f"            toVisit.enqueue((callee, currentDepth + 1))\n"
                    f"          }}\n"
                    f"        }}\n"
                    f"      }}\n"
                    f"    }}\n"
                    f"  }}\n"
                    f"  \n"
                    f"  allCalls.toList.map(t => (t._1, t._2, t._3)).toJsonPretty\n"
                    f"}} else List[(String, String, Int)]().toJsonPretty"
                )
            else:  # incoming
                # For incoming calls, find all methods that call the target using BFS
                # This finds methods that call the target at any depth
                query = (
                    f'val targetMethod = cpg.method.name("{method_escaped}").l\n'
                    f"if (targetMethod.nonEmpty) {{\n"
                    f"  val targetName = targetMethod.head.name\n"
                    f"  var allCallers = scala.collection.mutable.ListBuffer[(String, String, Int)]()\n"
                    f"  var toVisit = scala.collection.mutable.Queue[(io.shiftleft.codepropertygraph.generated.nodes.Method, Int)]()\n"
                    f"  var visited = Set[String]()\n"
                    f"  \n"
                    f"  // Start with direct callers\n"
                    f"  val directCallers = targetMethod.head.caller.l\n"
                    f"  for (caller <- directCallers) {{\n"
                    f"    allCallers += ((caller.name, targetName, 1))\n"
                    f"    toVisit.enqueue((caller, 1))\n"
                    f"  }}\n"
                    f"  \n"
                    f"  // BFS to find indirect callers\n"
                    f"  while (toVisit.nonEmpty) {{\n"
                    f"    val (current, currentDepth) = toVisit.dequeue()\n"
                    f"    val currentName = current.name\n"
                    f"    \n"
                    f"    if (!visited.contains(currentName) && currentDepth < {
                        depth}) {{\n"
                    f"      visited = visited + currentName\n"
                    f"      val incomingCallers = current.caller.l\n"
                    f"      \n"
                    f"      for (caller <- incomingCallers) {{\n"
                    f"        val callerName = caller.name\n"
                    f'        if (!callerName.startsWith("<operator>")) {{\n'
                    f"          allCallers += ((callerName, targetName, currentDepth + 1))\n"
                    f"          if (!visited.contains(callerName)) {{\n"
                    f"            toVisit.enqueue((caller, currentDepth + 1))\n"
                    f"          }}\n"
                    f"        }}\n"
                    f"      }}\n"
                    f"    }}\n"
                    f"  }}\n"
                    f"  \n"
                    f"  allCallers.toList.map(t => (t._1, t._2, t._3)).toJsonPretty\n"
                    f"}} else List[(String, String, Int)]().toJsonPretty"
                )

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=60,
                limit=200,
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