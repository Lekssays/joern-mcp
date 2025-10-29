"""
Taint Analysis MCP Tools for Joern MCP Server
Security-focused tools for analyzing data flows and vulnerabilities
"""

import logging
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


def register_taint_analysis_tools(mcp, services: dict):
    """Register taint analysis MCP tools with the FastMCP server"""

    @mcp.tool()
    async def find_taint_sources(
        session_id: str,
        language: Optional[str] = None,
        source_patterns: Optional[list] = None,
        filename: Optional[str] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """
        Locate likely external input points (taint sources).

        Search for function calls that could be entry points for untrusted data,
        such as user input, environment variables, or network data. Useful for
        identifying where external data enters the program.

        Args:
            session_id: The session ID from create_cpg_session
            language: Programming language to use for default patterns (e.g., "c", "java")
                If not provided, uses the session's language
            source_patterns: Optional list of regex patterns to match source function names
                (e.g., ["getenv", "fgets", "scanf"]). If not provided, uses default patterns
            filename: Optional filename to filter results (e.g., "shell.c", "main.c")
                Uses regex matching, so partial names work (e.g., "shell" matches "shell.c")
            limit: Maximum number of results to return (default: 200)

        Returns:
            {
                "success": true,
                "sources": [
                    {
                        "node_id": "12345",
                        "name": "getenv",
                        "code": "getenv(\"PATH\")",
                        "filename": "main.c",
                        "lineNumber": 42,
                        "method": "main"
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

            # Determine language and patterns
            lang = language or session.language or "c"
            cfg = services["config"]
            taint_cfg = (
                getattr(cfg.cpg, "taint_sources", {})
                if hasattr(cfg.cpg, "taint_sources")
                else {}
            )

            patterns = source_patterns or taint_cfg.get(lang, [])
            if not patterns:
                # Fallback to common C patterns
                patterns = [
                    "getenv",
                    "fgets",
                    "scanf",
                    "read",
                    "recv",
                    "accept",
                    "fopen",
                ]

            # Build Joern query searching for call names matching any pattern
            # Remove trailing parens from patterns for proper regex matching
            cleaned_patterns = [p.rstrip("(") for p in patterns]
            joined = "|".join([re.escape(p) for p in cleaned_patterns])
            
            # Build query with optional file filter
            if filename:
                # Use regex to match filename - handles both full and partial matches
                query = f'cpg.call.name("{joined}").where(_.file.name(".*{filename}.*")).map(c => (c.id, c.name, c.code, c.file.name.headOption.getOrElse("unknown"), c.lineNumber.getOrElse(-1), c.method.fullName)).take({limit})'
            else:
                query = f'cpg.call.name("{joined}").map(c => (c.id, c.name, c.code, c.file.name.headOption.getOrElse("unknown"), c.lineNumber.getOrElse(-1), c.method.fullName)).take({limit})'

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

            sources = []
            for item in result.data:
                if isinstance(item, dict):
                    sources.append(
                        {
                            "node_id": item.get("_1"),
                            "name": item.get("_2"),
                            "code": item.get("_3"),
                            "filename": item.get("_4"),
                            "lineNumber": item.get("_5"),
                            "method": item.get("_6"),
                        }
                    )

            return {"success": True, "sources": sources, "total": len(sources)}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error finding taint sources: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error finding taint sources: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def find_taint_sinks(
        session_id: str,
        language: Optional[str] = None,
        sink_patterns: Optional[list] = None,
        filename: Optional[str] = None,
        limit: int = 200,
    ) -> Dict[str, Any]:
        """
        Locate dangerous sinks where tainted data could cause vulnerabilities.

        Search for function calls that could be security-sensitive destinations
        for data, such as system execution, file operations, or format strings.
        Useful for identifying where untrusted data could cause harm.

        Args:
            session_id: The session ID from create_cpg_session
            language: Programming language to use for default patterns (e.g., "c", "java")
                If not provided, uses the session's language
            sink_patterns: Optional list of regex patterns to match sink function names
                (e.g., ["system", "popen", "sprintf"]). If not provided, uses default patterns
            filename: Optional filename to filter results (e.g., "shell.c", "main.c")
                Uses regex matching, so partial names work (e.g., "shell" matches "shell.c")
            limit: Maximum number of results to return (default: 200)

        Returns:
            {
                "success": true,
                "sinks": [
                    {
                        "node_id": "67890",
                        "name": "system",
                        "code": "system(cmd)",
                        "filename": "main.c",
                        "lineNumber": 100,
                        "method": "execute_command"
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

            lang = language or session.language or "c"
            cfg = services["config"]
            taint_cfg = (
                getattr(cfg.cpg, "taint_sinks", {})
                if hasattr(cfg.cpg, "taint_sinks")
                else {}
            )

            patterns = sink_patterns or taint_cfg.get(lang, [])
            if not patterns:
                patterns = ["system", "popen", "execl", "execv", "sprintf", "fprintf"]

            # Remove trailing parens from patterns for proper regex matching
            cleaned_patterns = [p.rstrip("(") for p in patterns]
            joined = "|".join([re.escape(p) for p in cleaned_patterns])
            
            # Build query with optional file filter
            if filename:
                # Use regex to match filename - handles both full and partial matches
                query = f'cpg.call.name("{joined}").where(_.file.name(".*{filename}.*")).map(c => (c.id, c.name, c.code, c.file.name.headOption.getOrElse("unknown"), c.lineNumber.getOrElse(-1), c.method.fullName)).take({limit})'
            else:
                query = f'cpg.call.name("{joined}").map(c => (c.id, c.name, c.code, c.file.name.headOption.getOrElse("unknown"), c.lineNumber.getOrElse(-1), c.method.fullName)).take({limit})'

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

            sinks = []
            for item in result.data:
                if isinstance(item, dict):
                    sinks.append(
                        {
                            "node_id": item.get("_1"),
                            "name": item.get("_2"),
                            "code": item.get("_3"),
                            "filename": item.get("_4"),
                            "lineNumber": item.get("_5"),
                            "method": item.get("_6"),
                        }
                    )

            return {"success": True, "sinks": sinks, "total": len(sinks)}

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error finding taint sinks: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error finding taint sinks: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def find_taint_flows(
        session_id: str,
        source_node_id: Optional[str] = None,
        sink_node_id: Optional[str] = None,
        source_location: Optional[str] = None,
        sink_location: Optional[str] = None,
        max_path_length: int = 20,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """
        Find dataflow paths from source to sink by tracking through assignments and identifiers.

        This tool traces how data flows from a source call (e.g., malloc, getenv) to a sink call
        (e.g., free, system) by following the intermediate variables, assignments, and identifiers.

        ✅ WHAT IT CAN DO:
        - Track return value flows: allocate() → variable → deallocate(variable)
          Example: ptr = allocate_memory(size); ... deallocate_memory(ptr);
        - Trace variable assignments across statements in the same function
          Example: input = get_user_data(); ... temp = input; ... process(temp);
        - Find direct identifier matches between source output and sink input
        - Work within intra-procedural scope (same function/method)

        ❌ WHAT IT CANNOT DO:
        - Interprocedural dataflow (across function boundaries)
          Example: Can't track: main() calls helper(x) which passes x to worker(y)
          Reason: Requires alias analysis and parameter tracking
        - Complex transformations or computations on data
          Example: Can't track: ptr = allocate(10); ptr2 = ptr + offset; deallocate(ptr2);
          Reason: Doesn't understand pointer arithmetic
        - Array element or struct field flows
          Example: Limited for: arr[i].field = allocate(); ... deallocate(arr[j].field);
          Reason: Needs field-sensitive analysis
        - Control-flow dependent paths
          Example: May miss: if(cond) ptr = allocate(); ... if(cond) deallocate(ptr);
          Reason: Doesn't analyze conditions

        💡 HOW IT WORKS:
        1. Locates the source call (e.g., allocate_memory at line 42)
        2. Finds what variable receives the result (e.g., buffer = allocate_memory())
        3. Searches for that identifier in sink call arguments (e.g., deallocate_memory(buffer))
        4. Reports if there's a direct match

        🔧 USE THIS TOOL WHEN:
        - Checking for resource leaks: allocate/acquire → deallocate/release
        - Finding use-after-free: deallocate → subsequent use
        - Tracing user input: get_input/read_data → dangerous_function
        - Simple variable flow within one function

        ⚠️ LIMITATIONS TO UNDERSTAND:
        - This is a SIMPLE identifier-based flow tracker, not full taint analysis
        - It finds DIRECT identifier matches, not semantic dataflow
        - For complex analysis, combine with get_call_graph and manual inspection
        - Best used as a starting point for deeper investigation

        Args:
            session_id: The session ID from create_cpg_session
            source_node_id: Node ID of source call (from find_taint_sources)
                Example: "12345"
            sink_node_id: Node ID of sink call (from find_taint_sinks)
                Example: "67890"
            source_location: Alternative: "filename:line" or "filename:line:method"
                Example: "main.c:42" or "main.c:42:process_data"
            sink_location: Alternative: "filename:line" or "filename:line:method"
                Example: "main.c:58" or "main.c:58:process_data"
            max_path_length: Maximum length of dataflow paths to consider in elements (default: 20)
                Paths with more elements will be filtered out to avoid extremely long chains
            timeout: Maximum execution time in seconds (default: 60)

        Returns:
            When source AND sink are provided:
            {
                "success": true,
                "source": {
                    "node_id": "12345",
                    "code": "allocate_memory(100)",
                    "filename": "main.c",
                    "lineNumber": 42,
                    "method": "process_data"
                },
                "sink": {
                    "node_id": "67890",
                    "code": "deallocate_memory(buffer)",
                    "filename": "main.c",
                    "lineNumber": 58,
                    "method": "process_data"
                },
                "flow_found": true,
                "flow_type": "direct_identifier_match",
                "intermediate_variable": "buffer",
                "details": {
                    "assignment": "buffer = allocate_memory(100)",
                    "assignment_line": 42,
                    "variable_uses": 3,
                    "explanation": "allocate_memory() returns value assigned to 'buffer', which is used as argument to deallocate_memory()"
                }
            }

            When ONLY source is provided:
            {
                "success": true,
                "source": {
                    "node_id": "12345",
                    "code": "allocate_memory(100)",
                    "filename": "main.c",
                    "lineNumber": 42,
                    "method": "process_data"
                },
                "flows": [
                    {
                        "path_id": 0,
                        "path_length": 3,
                        "nodes": [
                            ["allocate_memory(100)", "main.c", 42, "CALL"],
                            ["buffer", "main.c", 42, "IDENTIFIER"],
                            ["deallocate_memory(buffer)", "main.c", 58, "CALL"]
                        ]
                    }
                ],
                "total_flows": 1,
                "message": "Found 1 flows from source to dangerous sinks"
            }

        Example - Source and Sink provided:
            find_taint_flows(
                session_id="abc-123",
                source_location="main.c:42",   # allocate_memory(100)
                sink_location="main.c:58"      # deallocate_memory(buffer)
            )
            # Result: ✓ Found flow through variable 'buffer'

        Example - Only Source provided:
            find_taint_flows(
                session_id="abc-123",
                source_location="main.c:42"    # allocate_memory(100)
            )
            # Result: ✓ Found flows to all dangerous sinks (free, system, etc.) that use the allocated variable

        Example - Only Sink provided (ERROR):
            find_taint_flows(
                session_id="abc-123",
                sink_location="main.c:58"      # deallocate_memory(buffer)
            )
            # Result: ❌ Validation error - only sink not supported
        """
        try:
            validate_session_id(session_id)

            # Validate that we have proper source and sink specifications
            if not source_node_id and not source_location:
                raise ValidationError(
                    "Either source_node_id or source_location must be provided"
                )
            if not sink_node_id and not sink_location and (source_node_id or source_location):
                # If only source is provided, that's fine - we'll find flows to any sink
                pass
            elif not sink_node_id and not sink_location:
                # If neither source nor sink is provided, that's an error
                raise ValidationError(
                    "Either source_node_id/source_location or sink_node_id/sink_location must be provided"
                )
            elif sink_node_id or sink_location:
                # If only sink is provided, that's an error
                if not source_node_id and not source_location:
                    raise ValidationError(
                        "Only sink provided - not supported. Please provide a source to find flows from."
                    )

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Resolve source and sink nodes
            source_info = None
            sink_info = None
            has_sink = bool(sink_node_id or sink_location)

            # Helper function to resolve node by ID or location
            async def resolve_node(node_id, location, node_type):
                if node_id:
                    try:
                        node_id_long = int(node_id)
                    except ValueError:
                        raise ValidationError(
                            f"{node_type}_node_id must be a valid integer: {node_id}"
                        )
                    query = f'cpg.call.id({
                        node_id_long}L).map(c => (c.id, c.code, c.file.name.headOption.getOrElse("unknown"), c.lineNumber.getOrElse(-1), c.method.fullName)).take(1).l'
                else:
                    parts = location.split(":")
                    if len(parts) < 2:
                        raise ValidationError(
                            f"{node_type}_location must be in format 'filename:line' or 'filename:line:call_name'"
                        )
                    filename = parts[0]
                    try:
                        line_num = int(parts[1])
                    except ValueError:
                        raise ValidationError(
                            f"Line number must be a valid integer: {parts[1]}"
                        )
                    method_name = parts[2] if len(parts) > 2 else None

                    if method_name:
                        query = f'cpg.call.where(_.file.name(".*{filename}$")).lineNumber({line_num}).filter(_.method.fullName.contains("{
                            method_name}")).map(c => (c.id, c.code, c.file.name.headOption.getOrElse("unknown"), c.lineNumber.getOrElse(-1), c.method.fullName)).take(1).l'
                    else:
                        query = f'cpg.call.where(_.file.name(".*{filename}$")).lineNumber({
                            line_num}).map(c => (c.id, c.code, c.file.name.headOption.getOrElse("unknown"), c.lineNumber.getOrElse(-1), c.method.fullName)).take(1).l'

                result = await query_executor.execute_query(
                    session_id=session_id,
                    cpg_path="/workspace/cpg.bin",
                    query=query,
                    timeout=10,
                    limit=1,
                )

                if result.success and result.data and len(result.data) > 0:
                    item = result.data[0]
                    if isinstance(item, dict) and item.get("_1"):
                        return {
                            "node_id": item.get("_1"),
                            "code": item.get("_2"),
                            "filename": item.get("_3"),
                            "lineNumber": item.get("_4"),
                            "method": item.get("_5"),
                        }
                return None

            source_info = await resolve_node(source_node_id, source_location, "source")
            if has_sink:
                sink_info = await resolve_node(sink_node_id, sink_location, "sink")

            # If source not found, return early
            if not source_info:
                return {
                    "success": False,
                    "source": source_info,
                    "sink": sink_info,
                    "flow_found": False,
                    "message": f"Could not resolve source from provided identifiers",
                }

            # If sink is required but not found, return early
            if has_sink and not sink_info:
                return {
                    "success": False,
                    "source": source_info,
                    "sink": sink_info,
                    "flow_found": False,
                    "message": f"Could not resolve sink from provided identifiers",
                }

            # Build dataflow query to find paths from source to sink
            source_id = source_info["node_id"]
            
            if has_sink:
                # Specific sink mode: find flows between source and sink
                sink_id = sink_info["node_id"]
                query = f"""
                {{
                  val source = cpg.call.id({source_id}L).l.headOption
                  val sink = cpg.call.id({sink_id}L).l.headOption

                  val flows = if (source.nonEmpty && sink.nonEmpty) {{
                    // Simple dataflow: source -> identifier -> sink
                    val sourceCall = source.get
                    val sinkCall = sink.get

                    val assignments = sourceCall.inAssignment.l
                    if (assignments.nonEmpty) {{
                      val assign = assignments.head
                      val targetVar = assign.target.code

                      val sinkArgs = sinkCall.argument.code.l
                      val matches = sinkArgs.contains(targetVar)

                      if (matches) {{
                        List(Map(
                          "_1" -> 0,  // flow_idx
                          "_2" -> 3,  // path_length
                          "_3" -> List(  // nodes
                            Map("_1" -> sourceCall.code, "_2" -> sourceCall.file.name.headOption.getOrElse("unknown"), "_3" -> sourceCall.lineNumber.getOrElse(-1), "_4" -> "CALL"),
                            Map("_1" -> targetVar, "_2" -> assign.file.name.headOption.getOrElse("unknown"), "_3" -> assign.lineNumber.getOrElse(-1), "_4" -> "IDENTIFIER"),
                            Map("_1" -> sinkCall.code, "_2" -> sinkCall.file.name.headOption.getOrElse("unknown"), "_3" -> sinkCall.lineNumber.getOrElse(-1), "_4" -> "CALL")
                          )
                        ))
                      }} else {{
                        List()
                      }}
                    }} else {{
                      List()
                    }}
                  }} else {{
                    List()
                  }}

                  flows
                }}.toJsonPretty"""
            else:
                # Source-only mode: find flows from source to any dangerous sink
                query = f"""
                {{
                  val source = cpg.call.id({source_id}L).l.headOption

                  val flows = if (source.nonEmpty) {{
                    val sourceCall = source.get
                    val assignments = sourceCall.inAssignment.l
                    
                    if (assignments.nonEmpty) {{
                      val assign = assignments.head
                      val targetVar = assign.target.code
                      
                      // Find all dangerous sinks that use this variable
                      val dangerousSinks = Set("system", "popen", "execl", "execv", "sprintf", "fprintf", "free", "delete")
                      val sinkCalls = cpg.call.name(dangerousSinks).filter(sink => {{
                        val sinkArgs = sink.argument.code.l
                        sinkArgs.contains(targetVar)
                      }}).l.take(20)  // Limit results
                      
                      sinkCalls.map(sink => Map(
                        "_1" -> 0,  // flow_idx
                        "_2" -> 3,  // path_length
                        "_3" -> List(  // nodes
                          Map("_1" -> sourceCall.code, "_2" -> sourceCall.file.name.headOption.getOrElse("unknown"), "_3" -> sourceCall.lineNumber.getOrElse(-1), "_4" -> "CALL"),
                          Map("_1" -> targetVar, "_2" -> assign.file.name.headOption.getOrElse("unknown"), "_3" -> assign.lineNumber.getOrElse(-1), "_4" -> "IDENTIFIER"),
                          Map("_1" -> sink.code, "_2" -> sink.file.name.headOption.getOrElse("unknown"), "_3" -> sink.lineNumber.getOrElse(-1), "_4" -> "CALL")
                        )
                      ))
                    }} else {{
                      List()
                    }}
                  }} else {{
                    List()
                  }}

                  flows
                }}.toJsonPretty"""

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=timeout,
                limit=1,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            # Parse result
            flows = []
            if result.success and result.data:
                # Result is a list of flow maps
                for item in result.data:
                    if (
                        isinstance(item, dict)
                        and "_1" in item
                        and "_2" in item
                        and "_3" in item
                    ):
                        flows.append(
                            {
                                "path_id": item["_1"],
                                "path_length": item["_2"],
                                "nodes": item["_3"],
                            }
                        )

            if has_sink:
                # Specific sink mode: return single flow result
                flow_found = len(flows) > 0
                return {
                    "success": True,
                    "source": source_info,
                    "sink": sink_info,
                    "flow_found": flow_found,
                    "flow_type": "direct_identifier_match" if flow_found else None,
                    "intermediate_variable": flows[0]["nodes"][1]["_1"] if flow_found else None,
                    "details": {
                        "assignment": flows[0]["nodes"][1]["_1"] if flow_found else None,
                        "assignment_line": flows[0]["nodes"][1]["_3"] if flow_found else None,
                        "variable_uses": 1 if flow_found else 0,
                        "explanation": f"{source_info['code']} result assigned to variable and used in {sink_info['code']}" if flow_found else None,
                    } if flow_found else None,
                }
            else:
                # Source-only mode: return multiple flows
                return {
                    "success": True,
                    "source": source_info,
                    "flows": flows,
                    "total_flows": len(flows),
                    "message": f"Found {len(flows)} flows from source to dangerous sinks" if flows else "No flows found from source to dangerous sinks",
                }

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error finding taint flows: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error finding taint flows: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def check_method_reachability(
        session_id: str, source_method: str, target_method: str
    ) -> Dict[str, Any]:
        """
        Check if one method can reach another through the call graph.

        Determines whether the target method is reachable from the source method
        by following function calls. Useful for understanding code dependencies
        and potential execution paths.

        Args:
            session_id: The session ID from create_cpg_session
            source_method: Name of the source method (can be regex pattern)
            target_method: Name of the target method (can be regex pattern)

        Returns:
            {
                "success": true,
                "reachable": true,
                "source_method": "main",
                "target_method": "helper",
                "message": "Method 'helper' is reachable from 'main'"
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

            # Escape patterns for regex
            source_escaped = re.escape(source_method)
            target_escaped = re.escape(target_method)

            # Query to check reachability using depth-independent BFS traversal.
            # Instead of manually checking levels 1-5, we use a recursive function
            # to traverse the entire call graph regardless of depth.
            query = (
                f'val source = cpg.method.name("{source_escaped}").l\n'
                f'val target = cpg.method.name("{target_escaped}").l\n'
                f"val reachable = if (source.nonEmpty && target.nonEmpty) {{\n"
                f"  val targetName = target.head.name\n"
                f"  // BFS traversal of call graph using recursive method traversal\n"
                f"  var visited = Set[String]()\n"
                f"  var toVisit = scala.collection.mutable.Queue[io.shiftleft.codepropertygraph.generated.nodes.Method]()\n"
                f"  toVisit.enqueue(source.head)\n"
                f"  var found = false\n"
                f"  \n"
                f"  while (toVisit.nonEmpty && !found) {{\n"
                f"    val current = toVisit.dequeue()\n"
                f"    val currentName = current.name\n"
                f"    if (!visited.contains(currentName)) {{\n"
                f"      visited = visited + currentName\n"
                f"      val callees = current.call.callee.l\n"
                f"      for (callee <- callees) {{\n"
                f"        val calleeName = callee.name\n"
                f"        if (calleeName == targetName) {{\n"
                f"          found = true\n"
                f'        }} else if (!visited.contains(calleeName) && !calleeName.startsWith("<operator>")) {{\n'
                f"          toVisit.enqueue(callee)\n"
                f"        }}\n"
                f"      }}\n"
                f"    }}\n"
                f"  }}\n"
                f"  found\n"
                f"}} else false\n"
                f"List(reachable).toJsonPretty"
            )

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=60,
                limit=1,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            reachable = False
            if result.data and len(result.data) > 0:
                # The query returns a boolean result
                reachable = bool(result.data[0])

            message = (
                f"Method '{target_method}' is {
                    'reachable' if reachable else 'not reachable'} "
                f"from '{source_method}'"
            )

            return {
                "success": True,
                "reachable": reachable,
                "source_method": source_method,
                "target_method": target_method,
                "message": message,
            }

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error checking method reachability: {e}")
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
    async def get_program_slice(
        session_id: str,
        node_id: Optional[str] = None,
        location: Optional[str] = None,
        include_dataflow: bool = True,
        include_control_flow: bool = True,
        max_depth: int = 5,
        timeout: int = 60,
    ) -> Dict[str, Any]:
        """
        Build a program slice from a specific call node.

        Creates a backward program slice showing all code that could affect the
        execution at a specific point. This includes:
        - The call itself and its arguments
        - Dataflow: all assignments and operations affecting argument variables
        - Control flow: conditions that determine whether the call executes
        - Call graph: functions called and their data dependencies

        **Important**: Use node IDs (from list_calls) or specify exact locations to
        avoid ambiguity, especially when multiple calls appear on the same line.

        Args:
            session_id: The session ID from create_cpg_session
            node_id: Preferred: Direct CPG node ID of the target call
                (Get from list_calls or other query results)
                Example: "12345"
            location: Alternative: "filename:line_number" or "filename:line_number:call_name"
                Example: "main.c:42" or "main.c:42:memcpy"
            include_dataflow: Include dataflow (variable assignments) in slice (default: true)
            include_control_flow: Include control dependencies (if/while conditions) (default: true)
            max_depth: Maximum depth for dataflow tracking (default: 5)
            timeout: Maximum execution time in seconds (default: 60)

        Returns:
            {
                "success": true,
                "slice": {
                    "target_call": {
                        "node_id": "12345",
                        "name": "memcpy",
                        "code": "memcpy(buf, src, size)",
                        "filename": "main.c",
                        "lineNumber": 42,
                        "method": "process_data",
                        "arguments": ["buf", "src", "size"]
                    },
                    "dataflow": [
                        {
                            "variable": "buf",
                            "code": "char buf[256]",
                            "filename": "main.c",
                            "lineNumber": 10,
                            "method": "process_data"
                        }
                    ],
                    "control_dependencies": [
                        {
                            "code": "if (user_input != NULL)",
                            "filename": "main.c",
                            "lineNumber": 35,
                            "method": "process_data"
                        }
                    ]
                },
                "total_nodes": 15
            }
        """
        try:
            validate_session_id(session_id)

            # Validate that we have proper node identification
            if not node_id and not location:
                raise ValidationError("Either node_id or location must be provided")

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Parse location if provided
            filename = None
            line_num = None
            call_name = None
            
            if location:
                parts = location.split(":")
                if len(parts) < 2:
                    raise ValidationError(
                        "location must be in format 'filename:line' or 'filename:line:callname'"
                    )
                filename = parts[0]
                try:
                    line_num = int(parts[1])
                except ValueError:
                    raise ValidationError(f"Invalid line number in location: {parts[1]}")
                call_name = parts[2] if len(parts) > 2 else ""

            # Build inline Scala query that creates JSON directly
            query_template = r"""{
def escapeJson(s: String): String = {
  s.replace("\\", "\\\\")
   .replace("\"", "\\\"")
   .replace("\n", "\\n")
   .replace("\r", "\\r")
   .replace("\t", "\\t")
}

val useNodeId = USE_NODE_ID_PLACEHOLDER
val targetNodeId = "NODE_ID_PLACEHOLDER"
val targetFilename = "FILENAME_PLACEHOLDER"
val targetLine = LINE_NUM_PLACEHOLDER
val targetCallName = "CALL_NAME_PLACEHOLDER"
val includeDataflow = INCLUDE_DATAFLOW_PLACEHOLDER
val includeControlFlow = INCLUDE_CONTROL_FLOW_PLACEHOLDER

// Step 1: Find the target call
val targetCallOpt = if (useNodeId) {
  cpg.call.id(targetNodeId.toLong).headOption
} else {
  val candidateCalls = cpg.file.name(".*" + targetFilename + ".*")
    .ast.isCall
    .lineNumber(targetLine)
    .l
  
  if (targetCallName.nonEmpty) {
    candidateCalls.name(targetCallName).headOption
  } else {
    candidateCalls.headOption
  }
}

val resultJson = targetCallOpt match {
  case Some(call) =>
    val callNodeId = call.id.toString
    val callName = call.name
    val callCode = escapeJson(call.code)
    val callFilename = escapeJson(call.file.name.headOption.getOrElse("unknown"))
    val callLineNumber = call.lineNumber.getOrElse(-1)
    val callMethod = escapeJson(call.method.name)
    val callArguments = call.argument.code.l
    
    val argsJson = callArguments.map(arg => "\"" + escapeJson(arg) + "\"").mkString(",")
    val targetCallJson = "{\"node_id\":\"" + callNodeId + "\",\"name\":\"" + callName + "\",\"code\":\"" + callCode + "\",\"filename\":\"" + callFilename + "\",\"lineNumber\":" + callLineNumber + ",\"method\":\"" + callMethod + "\",\"arguments\":[" + argsJson + "]}"
    
    // Step 2: Collect dataflow dependencies
    val dataflowList = scala.collection.mutable.ListBuffer[String]()
    
    if (includeDataflow) {
      callArguments.foreach { arg =>
        val cleanArg = arg.trim().replaceAll("\"", "")
        
        if (cleanArg.nonEmpty && 
            !cleanArg.matches("\\d+") && 
            !cleanArg.startsWith("(") && 
            !cleanArg.startsWith("0x")) {
          
          val identifiers = cpg.identifier.name(cleanArg).l.take(10)
          
          identifiers.foreach { id =>
            val idCode = escapeJson(id.code)
            val idFilename = escapeJson(id.file.name.headOption.getOrElse("unknown"))
            val idLineNumber = id.lineNumber.getOrElse(-1)
            val idMethod = escapeJson(id.method.name)
            
            val dataflowJson = "{\"variable\":\"" + cleanArg + "\",\"code\":\"" + idCode + "\",\"filename\":\"" + idFilename + "\",\"lineNumber\":" + idLineNumber + ",\"method\":\"" + idMethod + "\"}"
            dataflowList += dataflowJson
          }
        }
      }
    }
    
    val dataflowJson = dataflowList.take(20).mkString(",")
    
    // Step 3: Collect control dependencies
    val controlDepsList = scala.collection.mutable.ListBuffer[String]()
    
    if (includeControlFlow) {
      val controlDeps = call.controlledBy.dedup.take(20).l
      
      controlDeps.foreach { ctrl =>
        val ctrlCode = escapeJson(ctrl.code)
        val ctrlFilename = escapeJson(ctrl.file.name.headOption.getOrElse("unknown"))
        val ctrlLineNumber = ctrl.lineNumber.getOrElse(-1)
        val ctrlMethod = escapeJson(ctrl.method.name)
        
        val controlJson = "{\"code\":\"" + ctrlCode + "\",\"filename\":\"" + ctrlFilename + "\",\"lineNumber\":" + ctrlLineNumber + ",\"method\":\"" + ctrlMethod + "\"}"
        controlDepsList += controlJson
      }
    }
    
    val controlDepsJson = controlDepsList.mkString(",")
    
    val totalNodes = 1 + dataflowList.size + controlDepsList.size
    
    "{\"success\":true,\"slice\":{\"target_call\":" + targetCallJson + ",\"dataflow\":[" + dataflowJson + "],\"control_dependencies\":[" + controlDepsJson + "]},\"total_nodes\":" + totalNodes + "}"
    
  case None =>
    val errorMsg = if (useNodeId) {
      s"Call not found: node_id=$targetNodeId, location=null"
    } else {
      val locStr = if (targetCallName.nonEmpty) {
        s"$targetFilename:$targetLine:$targetCallName"
      } else {
        s"$targetFilename:$targetLine"
      }
      s"Call not found: node_id=null, location=$locStr"
    }
    "{\"success\":false,\"error\":{\"code\":\"NOT_FOUND\",\"message\":\"" + errorMsg + "\"}}"
}

resultJson
}"""

            # Replace placeholders
            use_node_id = "true" if node_id else "false"
            query = (
                query_template
                .replace("USE_NODE_ID_PLACEHOLDER", use_node_id)
                .replace("NODE_ID_PLACEHOLDER", node_id if node_id else "")
                .replace("FILENAME_PLACEHOLDER", filename if filename else "")
                .replace("LINE_NUM_PLACEHOLDER", str(line_num) if line_num else "-1")
                .replace("CALL_NAME_PLACEHOLDER", call_name if call_name else "")
                .replace("INCLUDE_DATAFLOW_PLACEHOLDER", "true" if include_dataflow else "false")
                .replace("INCLUDE_CONTROL_FLOW_PLACEHOLDER", "true" if include_control_flow else "false")
            )

            # Execute the query
            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=timeout,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            # Parse the JSON result (same as get_data_dependencies)
            import json

            if isinstance(result.data, list) and len(result.data) > 0:
                result_data = result.data[0]

                # Handle JSON string response
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
            logger.error(f"Error getting program slice: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error getting program slice: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def find_argument_flows(
        session_id: str,
        source_name: str,
        sink_name: str,
        arg_index: int = 0,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        Find flows where the EXACT SAME expression is passed as an argument to both source and sink calls.

        This tool matches calls based on argument expression equality. It is useful for finding
        cases where a variable or expression is reused across multiple function calls within
        the same scope or function.

        ✅ WHAT IT CAN DO:
        - Match variables passed to multiple functions with the same name
          Example: count passed to both validate_input(count) and process_data(count)
        - Find constant values used across calls
          Example: BUFFER_SIZE used in allocate_buffer(BUFFER_SIZE) and init_buffer(BUFFER_SIZE)
        - Track simple expressions reused in multiple calls
          Example: offset+4 used in read_data(offset+4) and write_data(offset+4)

        ❌ WHAT IT CANNOT DO:
        - Track variables that change names across function boundaries
          Example: data (in main) → input_data (in helper function)
          Reason: These are different identifiers, requires parameter alias tracking
        - Follow return values assigned to new variables
          Example: ptr = allocate_memory(size) → deallocate_memory(ptr)
          Reason: allocate_memory() returns a value, deallocate_memory() takes "ptr" variable
        - Track array element or struct field accesses
          Example: array[i].field passed through calls
          Reason: Complex expressions don't maintain exact equality
        - Perform interprocedural dataflow analysis
          Reason: Only looks at argument text matching, not semantic flow

        💡 USE THIS TOOL WHEN:
        - Looking for intra-procedural argument reuse patterns
        - Finding variables passed to multiple validation/processing functions
        - Identifying shared constants or configuration values
        - Analyzing argument consistency within the same function scope

        🔧 FOR INTERPROCEDURAL ANALYSIS, USE:
        - find_taint_flows: Full dataflow analysis with source/sink tracking
        - get_call_graph: Understand call relationships
        - list_methods: Find methods that use specific calls (callee_pattern parameter)

        Args:
            session_id: The session ID from create_cpg_session
            source_name: Name of the source function call (where argument originates)
            sink_name: Name of the sink function call (where argument is used)
            arg_index: Argument position to match (0-based indexing, default: 0)
            limit: Maximum number of matching flows to return (default: 100)

        Returns:
            {
                "success": true,
                "flows": [
                    {
                        "source": {
                            "name": "validate_input",
                            "filename": "main.c",
                            "lineNumber": 42,
                            "code": "validate_input(user_count)",
                            "method": "process_request",
                            "matched_arg": "user_count"
                        },
                        "sink": {
                            "name": "process_data",
                            "filename": "main.c",
                            "lineNumber": 45,
                            "code": "process_data(user_count, buffer)",
                            "method": "process_request",
                            "matched_arg": "user_count"
                        }
                    }
                ],
                "total": 1,
                "note": "Only finds EXACT expression matches, not semantic dataflow"
            }

        Example Usage:
            # Find where user_count is passed to both functions
            find_argument_flows(
                session_id="abc-123",
                source_name="validate_input",
                sink_name="process_data",
                arg_index=0  # user_count is the first argument
            )

            # This WON'T work: malloc -> free (return value vs variable name)
            find_argument_flows(
                session_id="abc-123",
                source_name="malloc",
                sink_name="free",
                arg_index=0  # Won't match: malloc returns pointer, free takes variable
            )
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

            # Single-line CPGQL query for argument-matching flows
            query = (
                f'cpg.call.name("{source_name}").flatMap(src => {{'
                f'  val argExpr = src.argument.l.lift({
                    arg_index}).map(_.code).getOrElse("<no-arg>"); '
                f'  cpg.call.name("{sink_name}").filter(sink => '
                f"    sink.argument.l.size > {
                    arg_index} && sink.argument.l({arg_index}).code == argExpr"
                f"  ).map(sink => Map("
                f'    "source" -> Map('
                f'      "name" -> src.name, '
                f'      "filename" -> src.file.name.headOption.getOrElse("unknown"), '
                f'      "lineNumber" -> src.lineNumber.getOrElse(-1), '
                f'      "code" -> src.code, '
                f'      "method" -> src.methodFullName, '
                f'      "matched_arg" -> argExpr'
                f"    ), "
                f'    "sink" -> Map('
                f'      "name" -> sink.name, '
                f'      "filename" -> sink.file.name.headOption.getOrElse("unknown"), '
                f'      "lineNumber" -> sink.lineNumber.getOrElse(-1), '
                f'      "code" -> sink.code, '
                f'      "method" -> sink.methodFullName, '
                f'      "matched_arg" -> argExpr'
                f"    )"
                f"  ))"
                f"}}).toJsonPretty"
            )

            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=60,
                limit=limit,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            return {
                "success": True,
                "flows": result.data if result.data else [],
                "total": len(result.data) if result.data else 0,
                "note": "Only finds EXACT expression matches, not semantic dataflow",
            }

        except (SessionNotFoundError, SessionNotReadyError, ValidationError) as e:
            logger.error(f"Error finding argument flows: {e}")
            return {
                "success": False,
                "error": {"code": type(e).__name__.upper(), "message": str(e)},
            }
        except Exception as e:
            logger.error(f"Unexpected error finding argument flows: {e}", exc_info=True)
            return {
                "success": False,
                "error": {"code": "INTERNAL_ERROR", "message": str(e)},
            }

    @mcp.tool()
    async def get_data_dependencies(
        session_id: str,
        location: str,
        variable: str,
        direction: str = "backward",
    ) -> Dict[str, Any]:
        """
        Analyze data dependencies for a variable at a specific location.

        Find all code locations that influence (backward) or are influenced by (forward)
        a variable at a specific line of code. Critical for understanding what values
        can affect a potentially vulnerable operation or where tainted data can flow.

        Args:
            session_id: The session ID from create_cpg_session
            location: Location in format "filename:line" (e.g., "parser.c:3393")
            variable: Name of the variable to analyze (e.g., "len", "buffer")
            direction: Analysis direction - "backward" (default) or "forward"
                - "backward": Find what affects this variable (definitions, assignments)
                - "forward": Find what uses this variable (usages, propagations)

        Returns:
            {
                "success": true,
                "target": {
                    "file": "parser.c",
                    "line": 3393,
                    "variable": "len",
                    "method": "xmlParseNmtoken"
                },
                "direction": "backward",
                "dependencies": [
                    {"line": 3383, "code": "int len = 0", "type": "initialization", "filename": "parser.c"},
                    {"line": 3393, "code": "len++", "type": "modification", "filename": "parser.c"},
                    {"line": 3393, "code": "len += xmlCopyCharMultiByte(...)", "type": "modification", "filename": "parser.c"}
                ],
                "total": 3
            }

        Dependency Types (backward):
            - initialization: Variable declaration/initialization
            - assignment: Direct assignments to the variable
            - modification: Increments, decrements, compound assignments (+=, -=, etc.)
            - function_call: Function calls that may modify the variable (pass by reference)

        Dependency Types (forward):
            - usage: Where the variable is used as a function argument
            - propagation: Assignments where the variable appears on the right-hand side

        Example - Backward Analysis (find what sets a variable):
            get_data_dependencies(
                session_id="abc-123",
                location="parser.c:3393",  # The COPY_BUF call
                variable="len",
                direction="backward"
            )
            # Returns all assignments, modifications, and initializations of 'len'
            # before line 3393

        Example - Forward Analysis (find what uses a variable):
            get_data_dependencies(
                session_id="abc-123",
                location="parser.c:3383",  # Where len is initialized
                variable="len",
                direction="forward"
            )
            # Returns all usages and propagations of 'len' after line 3383
        """
        try:
            validate_session_id(session_id)

            # Validate location format
            if ":" not in location:
                raise ValidationError("location must be in format 'filename:line'")

            parts = location.rsplit(":", 1)
            if len(parts) != 2:
                raise ValidationError("location must be in format 'filename:line'")

            filename = parts[0]
            try:
                line_num = int(parts[1])
            except ValueError:
                raise ValidationError(f"Invalid line number: {parts[1]}")

            # Validate direction
            if direction not in ["backward", "forward"]:
                raise ValidationError("direction must be 'backward' or 'forward'")

            session_manager = services["session_manager"]
            query_executor = services["query_executor"]

            session = await session_manager.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")

            if session.status != SessionStatus.READY.value:
                raise SessionNotReadyError(f"Session is in '{session.status}' status")

            await session_manager.touch_session(session_id)

            # Build inline Scala query (like find_bounds_checks)
            # Wrap in braces to avoid REPL line-by-line interpretation issues
            query_template = r"""{
def escapeJson(s: String): String = {
  s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
}

val targetLine = LINE_NUM_PLACEHOLDER
val varName = "VARIABLE_PLACEHOLDER"
val direction = "DIRECTION_PLACEHOLDER"

val targetMethodOpt = cpg.method.filter(m => {
  val filename = m.file.name.headOption.getOrElse("")
  (filename.endsWith("/FILENAME_PLACEHOLDER") || filename == "FILENAME_PLACEHOLDER")
}).filter(m => {
  val start = m.lineNumber.getOrElse(-1)
  val end = m.lineNumberEnd.getOrElse(-1)
  start <= targetLine && end >= targetLine
}).headOption

targetMethodOpt match {
  case Some(method) =>
    val dependencies = scala.collection.mutable.ListBuffer[String]()
    
    if (direction == "backward") {
      val inits = method.local.name(varName).map { local =>
        "{\"line\":" + local.lineNumber.getOrElse(-1) + ",\"code\":\"" + escapeJson(local.typeFullName + " " + local.code) + "\",\"type\":\"initialization\",\"filename\":\"" + escapeJson(local.file.name.headOption.getOrElse("unknown")) + "\"}"
      }.l
      dependencies ++= inits
      
      val assignments = method.assignment.l.filter(assign => {
        val line = assign.lineNumber.getOrElse(-1)
        if (line >= targetLine) false
        else {
          val targetCode = assign.target.code
          targetCode == varName || targetCode.startsWith(varName + "[") || targetCode.startsWith(varName + ".")
        }
      }).map { assign =>
        "{\"line\":" + assign.lineNumber.getOrElse(-1) + ",\"code\":\"" + escapeJson(assign.code) + "\",\"type\":\"assignment\",\"filename\":\"" + escapeJson(assign.file.name.headOption.getOrElse("unknown")) + "\"}"
      }
      dependencies ++= assignments
      
      val modifications = method.call.name("<operator>.(postIncrement|preIncrement|postDecrement|preDecrement|assignmentPlus|assignmentMinus)").l.filter { call =>
        val line = call.lineNumber.getOrElse(-1)
        if (line >= targetLine) false
        else {
          val args = call.argument.code.l
          args.exists(arg => arg == varName || arg.startsWith(varName + "[") || arg.startsWith(varName + "."))
        }
      }.map { call =>
        "{\"line\":" + call.lineNumber.getOrElse(-1) + ",\"code\":\"" + escapeJson(call.code) + "\",\"type\":\"modification\",\"filename\":\"" + escapeJson(call.file.name.headOption.getOrElse("unknown")) + "\"}"
      }
      dependencies ++= modifications
      
      val callModifications = method.call.l.filter { call =>
        val line = call.lineNumber.getOrElse(-1)
        if (line >= targetLine) false
        else {
          val args = call.argument.code.l
          args.exists(arg => arg == "&" + varName || arg == varName)
        }
      }.map { call =>
        "{\"line\":" + call.lineNumber.getOrElse(-1) + ",\"code\":\"" + escapeJson(call.code) + "\",\"type\":\"function_call\",\"filename\":\"" + escapeJson(call.file.name.headOption.getOrElse("unknown")) + "\"}"
      }
      dependencies ++= callModifications
      
    } else if (direction == "forward") {
      val usages = method.call.l.filter { call =>
        val line = call.lineNumber.getOrElse(-1)
        if (line <= targetLine) false
        else {
          val args = call.argument.code.l
          args.exists(arg => arg.contains(varName))
        }
      }.take(20).map { call =>
        "{\"line\":" + call.lineNumber.getOrElse(-1) + ",\"code\":\"" + escapeJson(call.code) + "\",\"type\":\"usage\",\"filename\":\"" + escapeJson(call.file.name.headOption.getOrElse("unknown")) + "\"}"
      }
      dependencies ++= usages
      
      val assignmentsFrom = method.assignment.l.filter { assign =>
        val line = assign.lineNumber.getOrElse(-1)
        if (line <= targetLine) false
        else {
          val sourceCode = assign.source.code
          sourceCode.contains(varName)
        }
      }.map { assign =>
        "{\"line\":" + assign.lineNumber.getOrElse(-1) + ",\"code\":\"" + escapeJson(assign.code) + "\",\"type\":\"propagation\",\"filename\":\"" + escapeJson(assign.file.name.headOption.getOrElse("unknown")) + "\"}"
      }
      dependencies ++= assignmentsFrom
    }
    
    val sortedDeps = dependencies.sortBy(dep => {
      val linePattern = "\"line\":(\\d+)".r
      linePattern.findFirstMatchIn(dep).map(_.group(1).toInt).getOrElse(-1)
    })
    
    val depsJson = sortedDeps.mkString(",")
    
    "{\"success\":true,\"target\":{\"file\":\"" + escapeJson(method.filename) + "\",\"line\":" + targetLine + ",\"variable\":\"" + varName + "\",\"method\":\"" + escapeJson(method.name) + "\"},\"direction\":\"" + direction + "\",\"dependencies\":[" + depsJson + "],\"total\":" + sortedDeps.size + "}"
    
  case None =>
    "{\"success\":false,\"error\":{\"code\":\"NOT_FOUND\",\"message\":\"No method found containing line LINE_NUM_PLACEHOLDER in file FILENAME_PLACEHOLDER\"}}"
}
}"""

            query = (
                query_template.replace("FILENAME_PLACEHOLDER", filename)
                .replace("LINE_NUM_PLACEHOLDER", str(line_num))
                .replace("VARIABLE_PLACEHOLDER", variable)
                .replace("DIRECTION_PLACEHOLDER", direction)
            )

            # Execute the query
            result = await query_executor.execute_query(
                session_id=session_id,
                cpg_path="/workspace/cpg.bin",
                query=query,
                timeout=60,
            )

            if not result.success:
                return {
                    "success": False,
                    "error": {"code": "QUERY_ERROR", "message": result.error},
                }

            # Parse the JSON result (same as find_bounds_checks)
            import json

            if isinstance(result.data, list) and len(result.data) > 0:
                result_data = result.data[0]

                # Handle JSON string response
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
            logger.error(f"Error getting data dependencies: {e}")
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