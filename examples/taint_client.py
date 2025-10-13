#!/usr/bin/env python3
"""
Comprehensive Taint Analysis MCP Client

This client demonstrates all taint analysis and security tools:
- find_taint_sources: Find external input points (malloc, getenv, etc.)
- find_taint_sinks: Find dange        # Detailed program slice for specific call
        logger.info("\n[10] Building program slice for malloc call in main (line 119)...")
        slice_res = await client.call_tool("get_program_slice", {
            "session_id": session_id,
            "filename": "core.c",
            "line_number": 119,
            "call_name": "malloc",
            "include_dataflow": True,
            "include_control_flow": True,
            "max_depth": 3,
            "timeout": 60
        })ons (free, system, etc.)
- find_taint_flows: Find dataflow paths from sources to sinks
- list_taint_paths: Get detailed node-by-node flow paths
- get_program_slice: Build backward slices from specific calls
- check_method_reachability: Check if methods can reach each other
- list_methods: Find all methods with specific patterns
- get_call_graph: Build call graphs for methods

Targets the core.c sample in playground/codebases/core which contains:
- Memory allocation functions (malloc)
- Memory deallocation functions (free)
- Complex control flow with iovec structures
- Nested function calls for dataflow analysis
"""

import asyncio
import logging
import sys
import os
import json

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

try:
    from fastmcp import Client
except ImportError:
    logger.error("FastMCP not found. Install with: pip install fastmcp")
    sys.exit(1)


def extract_tool_result(result):
    """Extract JSON result from tool response"""
    if hasattr(result, 'content') and result.content:
        content_text = result.content[0].text
        try:
            return json.loads(content_text)
        except Exception:
            return {"error": content_text}
    return {}


async def run_taint_analysis():
    """Run comprehensive taint analysis demonstration"""
    server_url = "http://localhost:4242/mcp"

    async with Client(server_url) as client:
        logger.info("="*80)
        logger.info("Connected to Joern MCP Server")
        logger.info("="*80)

        # Create session for the core C sample
        logger.info("\n[1] Creating CPG session for core.c...")
        session_res = await client.call_tool("create_cpg_session", {
            "source_type": "local",
            "source_path": os.path.abspath("playground/codebases/core"),
            "language": "c"
        })

        session_dict = extract_tool_result(session_res)
        if not session_dict.get("session_id"):
            logger.error(f"Session creation failed: {session_dict}")
            return

        session_id = session_dict["session_id"]
        logger.info(f"✓ Session created: {session_id}")

        # Wait for CPG generation
        logger.info("\n[2] Waiting for CPG generation...")
        for i in range(30):
            st = await client.call_tool("get_session_status", {"session_id": session_id})
            st_dict = extract_tool_result(st)
            status = st_dict.get("status")
            logger.info(f"  Status: {status}")
            if status == "ready":
                logger.info("✓ CPG ready for analysis")
                break
            elif status == "error":
                logger.error(f"✗ CPG generation error: {st_dict.get('error_message')}")
                return
            await asyncio.sleep(2)

        # List all methods in the codebase
        logger.info("\n[3] Listing all methods in core.c...")
        methods_res = await client.call_tool("list_methods", {
            "session_id": session_id,
            "include_external": False,
            "limit": 50
        })
        
        methods_dict = extract_tool_result(methods_res)
        if methods_dict.get("success"):
            methods = methods_dict.get("methods", [])
            logger.info(f"✓ Found {len(methods)} methods:")
            for m in methods:
                logger.info(f"  - {m.get('name')} @ line {m.get('lineNumber')}")
        else:
            logger.error(f"✗ Error listing methods: {methods_dict.get('error')}")

        # Find taint sources (memory allocation in this case)
        logger.info("\n[4] Finding taint sources (malloc, calloc, etc.)...")
        src_res = await client.call_tool("find_taint_sources", {
            "session_id": session_id,
            "source_patterns": ["malloc", "calloc", "realloc"],
            "limit": 100
        })

        src_dict = extract_tool_result(src_res)
        if src_dict.get("success"):
            sources = src_dict.get("sources", [])
            logger.info(f"✓ Found {len(sources)} memory allocation sources:")
            for s in sources[:15]:
                logger.info(f"  - {s.get('name')} @ {s.get('filename')}:{s.get('lineNumber')}")
                logger.info(f"    Code: {s.get('code')}")
                logger.info(f"    Method: {s.get('method')}")
        else:
            logger.error(f"✗ Error finding sources: {src_dict.get('error')}")

        # Find taint sinks (memory deallocation, dangerous functions)
        logger.info("\n[5] Finding taint sinks (free, printf, etc.)...")
        snk_res = await client.call_tool("find_taint_sinks", {
            "session_id": session_id,
            "sink_patterns": ["free", "printf", "fprintf", "memcpy"],
            "limit": 100
        })

        snk_dict = extract_tool_result(snk_res)
        if snk_dict.get("success"):
            sinks = snk_dict.get("sinks", [])
            logger.info(f"✓ Found {len(sinks)} potential sinks:")
            for s in sinks[:15]:
                logger.info(f"  - {s.get('name')} @ {s.get('filename')}:{s.get('lineNumber')}")
                logger.info(f"    Code: {s.get('code')}")
                logger.info(f"    Method: {s.get('method')}")
        else:
            logger.error(f"✗ Error finding sinks: {snk_dict.get('error')}")

        # Find dataflow paths from malloc to free
        logger.info("\n[6] Finding dataflow paths (malloc -> free)...")
        flows_res = await client.call_tool("find_taint_flows", {
            "session_id": session_id,
            "source_patterns": ["malloc"],
            "sink_patterns": ["free"],
            "max_path_length": 20,
            "timeout": 60,
            "limit": 50
        })

        flows_dict = extract_tool_result(flows_res)
        if flows_dict.get("success"):
            flows = flows_dict.get("flows", [])
            logger.info(f"✓ Found {len(flows)} dataflow paths:")
            for i, f in enumerate(flows[:10], 1):
                logger.info(f"\n  Path {i}:")
                logger.info(f"    Source: {f.get('source_code')} @ line {f.get('source_line')}")
                logger.info(f"    Sink: {f.get('sink_code')} @ line {f.get('sink_line')}")
                logger.info(f"    Path length: {f.get('path_length')} nodes")
        else:
            logger.error(f"✗ Error finding flows: {flows_dict.get('error')}")

        # Get detailed taint paths with node-by-node breakdown
        logger.info("\n[7] Getting detailed taint paths (malloc -> free)...")
        paths_res = await client.call_tool("list_taint_paths", {
            "session_id": session_id,
            "source_pattern": "malloc",
            "sink_pattern": "free",
            "max_paths": 5,
            "max_path_length": 20,
            "timeout": 60
        })

        paths_dict = extract_tool_result(paths_res)
        if paths_dict.get("success"):
            paths = paths_dict.get("paths", [])
            logger.info(f"✓ Found {len(paths)} detailed paths:")
            for path in paths[:3]:
                logger.info(f"\n  {path.get('path_id')}:")
                logger.info(f"    Source: {path['source'].get('code')} @ line {path['source'].get('lineNumber')}")
                logger.info(f"    Sink: {path['sink'].get('code')} @ line {path['sink'].get('lineNumber')}")
                logger.info(f"    Path length: {path.get('path_length')} nodes")
                logger.info(f"    Nodes in flow:")
                for node in path.get('nodes', [])[:8]:
                    logger.info(f"      [{node.get('step')}] {node.get('code')} @ line {node.get('lineNumber')} ({node.get('node_type')})")
                if len(path.get('nodes', [])) > 8:
                    logger.info(f"      ... ({len(path.get('nodes', [])) - 8} more nodes)")
        else:
            logger.error(f"✗ Error listing paths: {paths_dict.get('error')}")

        # Check method reachability
        logger.info("\n[8] Checking method reachability (main -> safe_copy_data)...")
        reach_res = await client.call_tool("check_method_reachability", {
            "session_id": session_id,
            "source_method": "main",
            "target_method": "safe_copy_data"
        })

        reach_dict = extract_tool_result(reach_res)
        if reach_dict.get("success"):
            logger.info(f"✓ Reachability result:")
            logger.info(f"  {reach_dict.get('message')}")
            logger.info(f"  Reachable: {reach_dict.get('reachable')}")
        else:
            logger.error(f"✗ Error checking reachability: {reach_dict.get('error')}")

        # Get call graph for main function
        logger.info("\n[9] Building call graph for 'main' function...")
        cg_res = await client.call_tool("get_call_graph", {
            "session_id": session_id,
            "method_name": "main",
            "depth": 2,
            "direction": "outgoing"
        })

        cg_dict = extract_tool_result(cg_res)
        if cg_dict.get("success"):
            calls = cg_dict.get("calls", [])
            logger.info(f"✓ Found {len(calls)} calls:")
            depth_1 = [c for c in calls if c.get('depth') == 1]
            depth_2 = [c for c in calls if c.get('depth') == 2]
            logger.info(f"  Depth 1 calls: {len(depth_1)}")
            for c in depth_1[:10]:
                logger.info(f"    {c.get('from')} -> {c.get('to')}")
            logger.info(f"  Depth 2 calls: {len(depth_2)}")
            for c in depth_2[:10]:
                logger.info(f"    {c.get('from')} -> {c.get('to')}")
        else:
            logger.error(f"✗ Error getting call graph: {cg_dict.get('error')}")

        # Build program slice for a malloc call in main
        logger.info("\n[10] Building program slice for malloc call in main (line 119)...")
        slice_res = await client.call_tool("get_program_slice", {
            "session_id": session_id,
            "filename": "core.c",
            "line_number": 119,
            "call_name": "malloc",
            "include_dataflow": True,
            "include_control_flow": True,
            "max_depth": 3,
            "timeout": 60
        })

        slice_dict = extract_tool_result(slice_res)
        if slice_dict.get("success"):
            slice_data = slice_dict.get("slice", {})
            target = slice_data.get("target_call", {})
            logger.info(f"✓ Program slice generated:")
            logger.info(f"  Target: {target.get('code')} @ line {target.get('lineNumber')}")
            logger.info(f"  Method: {target.get('method')}")
            logger.info(f"  Arguments: {', '.join(target.get('arguments', []))}")
            
            dataflow = slice_data.get("dataflow", [])
            logger.info(f"\n  Dataflow nodes: {len(dataflow)}")
            for df in dataflow[:5]:
                logger.info(f"    Variable '{df.get('variable')}': {df.get('definition')} @ line {df.get('lineNumber')}")
            
            control = slice_data.get("control_dependencies", [])
            logger.info(f"\n  Control dependencies: {len(control)}")
            for cd in control[:5]:
                logger.info(f"    {cd.get('condition')} @ line {cd.get('lineNumber')}")
            
            callgraph = slice_data.get("call_graph", [])
            logger.info(f"\n  Call graph nodes: {len(callgraph)}")
            for cg in callgraph[:5]:
                logger.info(f"    {cg.get('from')} -> {cg.get('to')}")
            
            logger.info(f"\n  Total slice size: {slice_dict.get('total_nodes')} nodes")
        else:
            logger.error(f"✗ Error building slice: {slice_dict.get('error')}")

        # List methods that call malloc
        logger.info("\n[11] Finding methods that call malloc...")
        malloc_methods = await client.call_tool("list_methods", {
            "session_id": session_id,
            "callee_pattern": "malloc",
            "include_external": False,
            "limit": 50
        })

        malloc_dict = extract_tool_result(malloc_methods)
        if malloc_dict.get("success"):
            methods = malloc_dict.get("methods", [])
            logger.info(f"✓ Found {len(methods)} methods calling malloc:")
            for m in methods:
                logger.info(f"  - {m.get('name')} @ line {m.get('lineNumber')}")
        else:
            logger.error(f"✗ Error finding malloc callers: {malloc_dict.get('error')}")

        # Summary
        logger.info("\n" + "="*80)
        logger.info("ANALYSIS SUMMARY")
        logger.info("="*80)
        logger.info(f"Total sources found: {len(src_dict.get('sources', []))}")
        logger.info(f"Total sinks found: {len(snk_dict.get('sinks', []))}")
        logger.info(f"Total dataflow paths: {len(flows_dict.get('flows', []))}")
        logger.info(f"Total detailed paths: {len(paths_dict.get('paths', []))}")
        logger.info(f"Methods in codebase: {len(methods_dict.get('methods', []))}")
        logger.info("="*80)

        # Close session
        logger.info(f"\n[12] Closing session {session_id}...")
        close_res = await client.call_tool("close_session", {"session_id": session_id})
        close_dict = extract_tool_result(close_res)
        if close_dict.get("success"):
            logger.info("✓ Session closed successfully")
        else:
            logger.error(f"✗ Failed to close session: {close_dict}")


async def main():
    """Main entry point"""
    try:
        await run_taint_analysis()
    except Exception as e:
        logger.error(f"✗ Taint analysis failed: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    asyncio.run(main())
