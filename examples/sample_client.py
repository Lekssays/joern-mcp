#!/usr/bin/env python3
"""
Sample MCP Client for Joern MCP Server

This demonstrates how to use all the tools available in the joern-mcp server.
"""

import asyncio
import logging
import sys
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

try:
    from fastmcp import Client
except ImportError:
    logger.error("FastMCP not found. Install with: pip install fastmcp")
    sys.exit(1)


def extract_tool_result(result):
    """Extract dictionary data from CallToolResult"""
    if hasattr(result, 'content') and result.content:
        content_text = result.content[0].text
        try:
            import json
            return json.loads(content_text)
        except:
            return {"error": content_text}
    return {}


async def demonstrate_joern_mcp():
    """Demonstrate all Joern MCP tools"""
    server_url = "http://localhost:4242/mcp"
    
    async with Client(server_url) as client:
        logger.info("🔌 Connected to Joern MCP Server")
        
        # 1. Test server connectivity
        await client.ping()
        logger.info("✅ Server ping successful")
        
        # 2. List available tools
        tools = await client.list_tools()
        logger.info(f"📋 Available tools: {[tool.name for tool in tools]}")
        
        # 3. Create a CPG session from local source
        logger.info("\n📁 Creating CPG session...")
        session_result = await client.call_tool("create_cpg_session", {
            "source_type": "local",
            "source_path": os.path.abspath("playground/codebases/core"),
            "language": "c"
        })
        
        session_dict = extract_tool_result(session_result)
        
        if not session_dict.get("session_id"):
            logger.error(f"❌ Session creation failed: {session_dict}")
            return
            
        session_id = session_dict["session_id"]
        logger.info(f"✅ Session created: {session_id}")
        
        # 4. Wait for CPG to be ready
        logger.info("⏳ Waiting for CPG generation...")
        for i in range(30):
            status_result = await client.call_tool("get_session_status", {
                "session_id": session_id
            })
            
            status_dict = extract_tool_result(status_result)
            status = status_dict.get("status")
            logger.info(f"  Status: {status}")
            
            if status == "ready":
                logger.info("✅ CPG is ready")
                break
            elif status == "error":
                logger.error(f"❌ CPG generation failed: {status_dict.get('error_message')}")
                return
                
            await asyncio.sleep(10)
        else:
            logger.error("❌ Timeout waiting for CPG")
            return
        
        # 5.5. Test node_id query directly
        logger.info("\n🔍 Testing node_id query directly...")
        test_result = await client.call_tool("run_cpgql_query", {
            "session_id": session_id,
            "query": "cpg.method.take(3).map(m => (m.id, m.name)).l",
            "timeout": 30
        })
        
        test_dict = extract_tool_result(test_result)
        
        if test_dict.get("success"):
            logger.info("  ✅ Direct query successful")
            if test_dict.get("data"):
                logger.info(f"     Raw data: {test_dict['data'][:3]}")
        else:
            logger.error(f"  ❌ Direct query failed: {test_dict.get('error')}")
        
        # 5.6. List methods using the dedicated tool
        logger.info("\n� Listing methods using list_methods tool...")
        methods_result = await client.call_tool("list_methods", {
            "session_id": session_id,
            "limit": 10
        })
        
        methods_dict = extract_tool_result(methods_result)
        
        if methods_dict.get("success"):
            total_methods = methods_dict.get("total", 0)
            logger.info(f"  ✅ Found {total_methods} methods")
            
            # Show sample methods with node_id
            if methods_dict.get("methods") and len(methods_dict["methods"]) > 0:
                methods = methods_dict["methods"]
                logger.info("     Sample methods:")
                for i, method in enumerate(methods[:5]):
                    node_id = method.get("node_id", "N/A")
                    name = method.get("name", "N/A")
                    filename = method.get("filename", "N/A")
                    line = method.get("lineNumber", "N/A")
                    logger.info(f"       {i+1}. [{node_id}] {name} in {filename}:{line}")
                if total_methods > 5:
                    logger.info(f"       ... and {total_methods - 5} more methods")
        else:
            logger.error(f"  ❌ Failed to list methods: {methods_dict.get('error')}")
        
        # 6. Run asynchronous CPGQL queries
        logger.info("\n⚡ Running asynchronous query...")
        async_result = await client.call_tool("run_cpgql_query_async", {
            "session_id": session_id,
            "query": "cpg.method.parameter.name",
            "timeout": 60
        })
        
        async_dict = extract_tool_result(async_result)
        
        if async_dict.get("success"):
            query_id = async_dict["query_id"]
            logger.info(f"  ✅ Async query started: {query_id}")
            
            # Monitor query status
            for i in range(10):
                status_result = await client.call_tool("get_query_status", {
                    "query_id": query_id
                })
                
                status_dict = extract_tool_result(status_result)
                query_status = status_dict.get("status")
                logger.info(f"    Status: {query_status}")
                
                if query_status == "completed":
                    # Get results
                    result = await client.call_tool("get_query_result", {
                        "query_id": query_id
                    })
                    
                    result_dict = extract_tool_result(result)
                    
                    if result_dict.get("success"):
                        count = result_dict.get("row_count", 0)
                        logger.info(f"  ✅ Async query completed: {count} results")
                        
                        # Show sample parameter names
                        if result_dict.get("data") and len(result_dict["data"]) > 0:
                            data = result_dict["data"]
                            logger.info(f"     Sample parameter names:")
                            for i, item in enumerate(data[:8]):
                                if isinstance(item, dict) and "value" in item:
                                    logger.info(f"       {i+1}. {item['value']}")
                                else:
                                    logger.info(f"       {i+1}. {str(item)[:50]}...")
                            if count > 8:
                                logger.info(f"       ... and {count - 8} more")
                    break
                elif query_status == "failed":
                    logger.error(f"  ❌ Async query failed: {status_dict.get('error')}")
                    break
                    
                await asyncio.sleep(5)
        
        # 6.5. Get code snippet
        logger.info("\n📄 Getting code snippet...")
        snippet_result = await client.call_tool("get_code_snippet", {
            "session_id": session_id,
            "filename": "core.c",
            "start_line": 1,
            "end_line": 20
        })
        
        snippet_dict = extract_tool_result(snippet_result)
        
        if snippet_dict.get("success"):
            filename = snippet_dict.get("filename")
            start_line = snippet_dict.get("start_line")
            end_line = snippet_dict.get("end_line")
            code = snippet_dict.get("code")
            
            logger.info(f"  ✅ Retrieved code snippet from {filename} (lines {start_line}-{end_line})")
            logger.info("     Code snippet:")
            # Show first few lines of the code
            lines = code.split('\n')[:5]  # Show first 5 lines
            for i, line in enumerate(lines, start=start_line):
                logger.info(f"       {i}: {line}")
            if len(code.split('\n')) > 5:
                logger.info(f"       ... and {len(code.split('\n')) - 5} more lines")
        else:
            logger.error(f"  ❌ Failed to get code snippet: {snippet_dict.get('error')}")
        
        # 6.6. Test find_argument_flows
        logger.info("\n🔗 Testing find_argument_flows...")
        
        # Test 1: A case that SHOULD work - src_count passed to multiple functions
        logger.info("\n  Test 1: Finding src_count argument flow (should work)")
        logger.info("    Looking for: validate_iovec_lengths -> safe_copy_data")
        flow_result1 = await client.call_tool("find_argument_flows", {
            "session_id": session_id,
            "source_name": "validate_iovec_lengths",
            "sink_name": "safe_copy_data",
            "arg_index": 1  # src_count is at index 1
        })
        
        flow_dict1 = extract_tool_result(flow_result1)
        
        if flow_dict1.get("success"):
            total = flow_dict1.get("total", 0)
            logger.info(f"  ✅ Found {total} argument flow(s)")
            
            if flow_dict1.get("flows"):
                for i, flow in enumerate(flow_dict1["flows"][:3], 1):
                    src = flow.get("source", {})
                    sink = flow.get("sink", {})
                    matched_arg = src.get("matched_arg", "N/A")
                    
                    logger.info(f"\n    Flow {i}:")
                    logger.info(f"      Matched argument: '{matched_arg}'")
                    logger.info(f"      Source: {src.get('name')} at line {src.get('lineNumber')}")
                    logger.info(f"        Code: {src.get('code', 'N/A')}")
                    logger.info(f"      Sink: {sink.get('name')} at line {sink.get('lineNumber')}")
                    logger.info(f"        Code: {sink.get('code', 'N/A')}")
                
                if total > 3:
                    logger.info(f"      ... and {total - 3} more flows")
            
            if flow_dict1.get("note"):
                logger.info(f"\n  ℹ️  Note: {flow_dict1['note']}")
        else:
            logger.error(f"  ❌ Test 1 failed: {flow_dict1.get('error')}")
        
        # Test 2: A case that WON'T work - malloc -> free (return value vs variable)
        logger.info("\n  Test 2: Finding malloc -> free flow (demonstrates limitation)")
        logger.info("    This should find 0 matches (different expressions)")
        flow_result2 = await client.call_tool("find_argument_flows", {
            "session_id": session_id,
            "source_name": "malloc",
            "sink_name": "free",
            "arg_index": 0
        })
        
        flow_dict2 = extract_tool_result(flow_result2)
        
        if flow_dict2.get("success"):
            total = flow_dict2.get("total", 0)
            if total == 0:
                logger.info(f"  ✅ Correctly found 0 flows (as expected)")
                logger.info(f"     Reason: malloc returns a value, free takes a variable name")
                logger.info(f"     Tip: Use find_taint_flows for this kind of analysis")
            else:
                logger.info(f"  ⚠️  Unexpectedly found {total} flow(s)")
        else:
            logger.error(f"  ❌ Test 2 failed: {flow_dict2.get('error')}")
        
        # Test 3: Another working case - dst_count
        logger.info("\n  Test 3: Finding dst_count argument flow")
        logger.info("    Looking for: validate_iovec_lengths -> safe_copy_data")
        flow_result3 = await client.call_tool("find_argument_flows", {
            "session_id": session_id,
            "source_name": "validate_iovec_lengths",
            "sink_name": "safe_copy_data",
            "arg_index": 1  # For the second call, dst_count is at index 1
        })
        
        flow_dict3 = extract_tool_result(flow_result3)
        
        if flow_dict3.get("success"):
            total = flow_dict3.get("total", 0)
            logger.info(f"  ✅ Found {total} argument flow(s) for dst_count")
        else:
            logger.error(f"  ❌ Test 3 failed: {flow_dict3.get('error')}")
        
        # Testing find_taint_flows
        logger.info("\n" + "="*80)
        logger.info("🔍 Testing find_taint_flows (identifier-based dataflow tracking)")
        logger.info("="*80)
        
        # First, find some taint sources and sinks
        logger.info("\n  Finding taint sources (malloc calls)...")
        sources_result = await client.call_tool("find_taint_sources", {
            "session_id": session_id,
            "source_patterns": ["malloc"],
            "limit": 10
        })
        sources_dict = extract_tool_result(sources_result)
        
        malloc_sources = []
        if sources_dict.get("success") and sources_dict.get("sources"):
            malloc_sources = sources_dict["sources"]
            logger.info(f"  ✅ Found {len(malloc_sources)} malloc calls")
            for i, src in enumerate(malloc_sources[:3], 1):
                logger.info(f"    {i}. {src.get('code')} at line {src.get('lineNumber')} (ID: {src.get('node_id')})")
        
        logger.info("\n  Finding taint sinks (free calls)...")
        sinks_result = await client.call_tool("find_taint_sinks", {
            "session_id": session_id,
            "sink_patterns": ["free"],
            "limit": 10
        })
        sinks_dict = extract_tool_result(sinks_result)
        
        free_sinks = []
        if sinks_dict.get("success") and sinks_dict.get("sinks"):
            free_sinks = sinks_dict["sinks"]
            logger.info(f"  ✅ Found {len(free_sinks)} free calls")
            for i, sink in enumerate(free_sinks[:3], 1):
                logger.info(f"    {i}. {sink.get('code')} at line {sink.get('lineNumber')} (ID: {sink.get('node_id')})")
        
        # Test 1: malloc -> free flow using node IDs
        if malloc_sources and free_sinks:
            logger.info("\n  Test 1: malloc -> free flow using node IDs")
            logger.info(f"    Source: {malloc_sources[0].get('code')} (ID: {malloc_sources[0].get('node_id')})")
            logger.info(f"    Sink: {free_sinks[0].get('code')} (ID: {free_sinks[0].get('node_id')})")
            
            taint_result1 = await client.call_tool("find_taint_flows", {
                "session_id": session_id,
                "source_node_id": str(malloc_sources[0].get('node_id')),
                "sink_node_id": str(free_sinks[0].get('node_id')),
                "timeout": 30
            })
            
            taint_dict1 = extract_tool_result(taint_result1)
            
            if taint_dict1.get("success"):
                flow_found = taint_dict1.get("flow_found", False)
                if flow_found:
                    logger.info(f"  ✅ Flow detected!")
                    logger.info(f"     Flow type: {taint_dict1.get('flow_type')}")
                    logger.info(f"     Intermediate variable: '{taint_dict1.get('intermediate_variable')}'")
                    
                    details = taint_dict1.get("details", {})
                    if details:
                        logger.info(f"     Assignment: {details.get('assignment')}")
                        logger.info(f"     Assignment line: {details.get('assignment_line')}")
                        logger.info(f"     Variable uses: {details.get('variable_uses')}")
                        logger.info(f"     Explanation: {details.get('explanation')}")
                else:
                    logger.info(f"  ℹ️  No flow found between these specific malloc and free calls")
                    logger.info(f"     (This is expected if they use different variables)")
            else:
                logger.error(f"  ❌ Test 1 failed: {taint_dict1.get('error')}")
        
        # Test 2: Try with location-based specification
        if malloc_sources and free_sinks:
            logger.info("\n  Test 2: malloc -> free flow using location specification")
            src_file = malloc_sources[0].get('filename', 'core.c').split('/')[-1]
            src_line = malloc_sources[0].get('lineNumber')
            sink_file = free_sinks[0].get('filename', 'core.c').split('/')[-1]
            sink_line = free_sinks[0].get('lineNumber')
            
            logger.info(f"    Source location: {src_file}:{src_line}")
            logger.info(f"    Sink location: {sink_file}:{sink_line}")
            
            taint_result2 = await client.call_tool("find_taint_flows", {
                "session_id": session_id,
                "source_location": f"{src_file}:{src_line}",
                "sink_location": f"{sink_file}:{sink_line}",
                "timeout": 30
            })
            
            taint_dict2 = extract_tool_result(taint_result2)
            
            if taint_dict2.get("success"):
                flow_found = taint_dict2.get("flow_found", False)
                if flow_found:
                    logger.info(f"  ✅ Flow detected!")
                    logger.info(f"     Variable: '{taint_dict2.get('intermediate_variable')}'")
                else:
                    logger.info(f"  ℹ️  No flow (expected if different variables)")
            else:
                logger.error(f"  ❌ Test 2 failed: {taint_dict2.get('error')}")
        
        # Test 3: Try multiple pairs to find a matching flow
        logger.info("\n  Test 3: Searching for matching malloc->free flows...")
        flows_found = 0
        for i, src in enumerate(malloc_sources[:3]):
            for j, sink in enumerate(free_sinks[:3]):
                logger.info(f"    Testing pair {i*3+j+1}/9: {src.get('code')} -> {sink.get('code')}")
                taint_result = await client.call_tool("find_taint_flows", {
                    "session_id": session_id,
                    "source_node_id": str(src.get('node_id')),
                    "sink_node_id": str(sink.get('node_id')),
                    "timeout": 15
                })
                
                taint_dict = extract_tool_result(taint_result)
                
                if taint_dict.get("success") and taint_dict.get("flow_found"):
                    flows_found += 1
                    var = taint_dict.get('intermediate_variable', 'N/A')
                    logger.info(f"    ✓ Flow {flows_found}: {src.get('code')} -> '{var}' -> {sink.get('code')}")
                else:
                    details = taint_dict.get('details')
                    if details and isinstance(details, dict):
                        reason = details.get('explanation', 'unknown')
                    else:
                        reason = 'no flow detected'
                    logger.info(f"       No flow. Reason: {reason}")
        
        if flows_found > 0:
            logger.info(f"  ✅ Found {flows_found} matching dataflow(s)")
        else:
            logger.info(f"  ℹ️  No matching flows found in sample (may need to test more pairs)")
        
        logger.info("\n  💡 Note: find_taint_flows tracks identifier-based flows within functions")
        logger.info("     For interprocedural flows, use get_call_graph and manual analysis")
        
        # 7. List all sessions
        logger.info("\n📋 Listing sessions...")
        sessions_result = await client.call_tool("list_sessions")
        sessions_dict = extract_tool_result(sessions_result)
        if sessions_dict.get("sessions"):
            total = sessions_dict.get("total", 0)
            logger.info(f"  Total sessions: {total}")
            
            for session in sessions_dict["sessions"]:
                logger.info(f"    {session['session_id']}: {session['status']} ({session['language']})")
        
        # 8. Filter sessions by status
        logger.info("\n🔎 Filtering sessions...")
        ready_sessions_result = await client.call_tool("list_sessions", {"status": "ready"})
        ready_sessions_dict = extract_tool_result(ready_sessions_result)
        if ready_sessions_dict.get("sessions"):
            count = len(ready_sessions_dict["sessions"])
            logger.info(f"  Ready sessions: {count}")
        
        # 9. GitHub session example (commented out to avoid actual cloning)
        """
        logger.info("\n🐙 Creating GitHub session...")
        github_result = await client.call_tool("create_cpg_session", {
            "source_type": "github",
            "source_path": "https://github.com/joernio/sample-repo",
            "language": "java",
            "branch": "main"
        })
        logger.info(f"GitHub session: {github_result}")
        """
        
        # 10. Cleanup queries
        logger.info("\n🧹 Cleaning up queries...")
        cleanup_result = await client.call_tool("cleanup_queries", {
            "max_age_hours": 0  # Clean all
        })
        
        cleanup_dict = extract_tool_result(cleanup_result)
        
        if cleanup_dict.get("success"):
            cleaned = cleanup_dict.get("cleaned_up", 0)
            logger.info(f"  ✅ Cleaned up {cleaned} queries")
        
        # 10.5 Test find_bounds_checks
        logger.info("\n" + "="*80)
        logger.info("🛡️  Testing find_bounds_checks (buffer overflow detection)")
        logger.info("="*80)
        
        # Test 1: Buffer access with check BEFORE (safe)
        logger.info("\n  Test 1: Buffer access with bounds check BEFORE access (safe)")
        logger.info("    Function: process_buffer_with_check at line 112")
        
        bounds_result1 = await client.call_tool("find_bounds_checks", {
            "session_id": session_id,
            "buffer_access_location": "core.c:112"
        })
        
        bounds_dict1 = extract_tool_result(bounds_result1)
        
        if bounds_dict1.get("success"):
            buffer_access = bounds_dict1.get("buffer_access", {})
            bounds_checks = bounds_dict1.get("bounds_checks", [])
            check_before = bounds_dict1.get("check_before_access", False)
            check_after = bounds_dict1.get("check_after_access", False)
            
            logger.info(f"  ✅ Analysis complete")
            logger.info(f"     Buffer access: {buffer_access.get('code')} at line {buffer_access.get('line')}")
            logger.info(f"     Buffer: '{buffer_access.get('buffer')}' Index: '{buffer_access.get('index')}'")
            logger.info(f"     Bounds checks found: {len(bounds_checks)}")
            
            for check in bounds_checks:
                position = check.get('position')
                logger.info(f"\n     Check at line {check.get('line')} ({position}):")
                logger.info(f"       Condition: {check.get('code')}")
                logger.info(f"       Checked: {check.get('checked_variable')} {check.get('operator')} {check.get('bound')}")
            
            logger.info(f"\n     ✓ Check before access: {check_before}")
            logger.info(f"     ✓ Check after access: {check_after}")
            
            if check_before:
                logger.info("     ✅ SAFE: Bounds checked before buffer access")
            elif check_after:
                logger.info("     ⚠️  UNSAFE: Bounds checked AFTER buffer access (too late!)")
            else:
                logger.info("     ❌ VULNERABLE: No bounds check found")
        else:
            logger.error(f"  ❌ Test 1 failed: {bounds_dict1.get('error')}")
        
        # Test 2: Buffer access with check AFTER (unsafe)
        logger.info("\n  Test 2: Buffer access with bounds check AFTER access (unsafe)")
        logger.info("    Function: process_buffer_no_check at line 118")
        
        bounds_result2 = await client.call_tool("find_bounds_checks", {
            "session_id": session_id,
            "buffer_access_location": "core.c:118"
        })
        
        bounds_dict2 = extract_tool_result(bounds_result2)
        
        if bounds_dict2.get("success"):
            buffer_access = bounds_dict2.get("buffer_access", {})
            bounds_checks = bounds_dict2.get("bounds_checks", [])
            check_before = bounds_dict2.get("check_before_access", False)
            check_after = bounds_dict2.get("check_after_access", False)
            
            logger.info(f"  ✅ Analysis complete")
            logger.info(f"     Buffer access: {buffer_access.get('code')} at line {buffer_access.get('line')}")
            logger.info(f"     Buffer: '{buffer_access.get('buffer')}' Index: '{buffer_access.get('index')}'")
            logger.info(f"     Bounds checks found: {len(bounds_checks)}")
            
            for check in bounds_checks:
                position = check.get('position')
                logger.info(f"\n     Check at line {check.get('line')} ({position}):")
                logger.info(f"       Condition: {check.get('code')}")
                logger.info(f"       Checked: {check.get('checked_variable')} {check.get('operator')} {check.get('bound')}")
            
            logger.info(f"\n     ✓ Check before access: {check_before}")
            logger.info(f"     ✓ Check after access: {check_after}")
            
            if check_before:
                logger.info("     ✅ SAFE: Bounds checked before buffer access")
            elif check_after:
                logger.info("     ⚠️  UNSAFE: Bounds checked AFTER buffer access (too late!)")
            else:
                logger.info("     ❌ VULNERABLE: No bounds check found")
        else:
            logger.error(f"  ❌ Test 2 failed: {bounds_dict2.get('error')}")
        
        logger.info("\n  💡 Note: find_bounds_checks helps identify buffer overflow vulnerabilities")
        logger.info("     by verifying if array accesses have corresponding bounds checks")
        logger.info("     and whether those checks happen BEFORE or AFTER the access.")
        
        # 11. Close session
        logger.info(f"\n🔒 Closing session {session_id}...")
        close_result = await client.call_tool("close_session", {
            "session_id": session_id
        })
        
        close_dict = extract_tool_result(close_result)
        
        if close_dict.get("success"):
            logger.info("  ✅ Session closed successfully")
        else:
            logger.error(f"  ❌ Failed to close session: {close_dict}")
        
        logger.info("\n🎉 All Joern MCP tools demonstrated successfully!")


async def main():
    """Main function"""
    try:
        await demonstrate_joern_mcp()
    except Exception as e:
        logger.error(f"❌ Demo failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())