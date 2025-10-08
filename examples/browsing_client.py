#!/usr/bin/env python3
"""
Code Browsing Tools Demo for Joern MCP Server

This demonstrates how to use the browsing tools to systematically explore
and understand a codebase. These tools help LLMs to:
1. Get a high-level overview of a codebase
2. List and explore files and methods
3. Understand call relationships
4. Find specific code patterns
"""

import asyncio
import logging
import sys

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


async def explore_codebase_workflow(client, session_id):
    """
    Demonstrates a typical workflow for exploring an unknown codebase.
    """
    logger.info("\n" + "="*60)
    logger.info("Workflow 1: Exploring an Unknown Codebase")
    logger.info("="*60)
    
    # Step 1: Get high-level overview
    logger.info("\n📊 Step 1: Getting codebase summary...")
    summary_result = await client.call_tool("get_codebase_summary", {
        "session_id": session_id
    })
    summary_dict = extract_tool_result(summary_result)
    
    if summary_dict.get("success"):
        summary = summary_dict.get("summary", {})
        logger.info(f"  Language: {summary.get('language', 'unknown')}")
        logger.info(f"  Total files: {summary.get('total_files', 0)}")
        logger.info(f"  Total methods: {summary.get('total_methods', 0)}")
        logger.info(f"  User-defined methods: {summary.get('user_defined_methods', 0)}")
        logger.info(f"  External methods: {summary.get('external_methods', 0)}")
        logger.info(f"  Total calls: {summary.get('total_calls', 0)}")
        logger.info(f"  Total literals: {summary.get('total_literals', 0)}")
    else:
        logger.error(f"  ❌ Failed: {summary_dict.get('error')}")
    
    # Step 2: List all files
    logger.info("\n📁 Step 2: Listing all source files...")
    files_result = await client.call_tool("list_files", {
        "session_id": session_id
    })
    files_dict = extract_tool_result(files_result)
    
    if files_dict.get("success"):
        files = files_dict.get("files", [])
        logger.info(f"  ✅ Found {len(files)} files:")
        for f in files[:5]:
            logger.info(f"     - {f['name']} ({f['path']})")
        if len(files) > 5:
            logger.info(f"     ... and {len(files) - 5} more")
    else:
        logger.error(f"  ❌ Failed: {files_dict.get('error')}")
    
    # Step 3: List all user-defined methods
    logger.info("\n🔧 Step 3: Listing user-defined methods...")
    methods_result = await client.call_tool("list_methods", {
        "session_id": session_id,
        "include_external": False,
        "limit": 20
    })
    methods_dict = extract_tool_result(methods_result)
    
    if methods_dict.get("success"):
        methods = methods_dict.get("methods", [])
        logger.info(f"  ✅ Found {len(methods)} user-defined methods:")
        for m in methods[:8]:
            logger.info(f"     - {m['name']} at {m['filename']}:{m['lineNumber']}")
        if len(methods) > 8:
            logger.info(f"     ... and {len(methods) - 8} more")
    else:
        logger.error(f"  ❌ Failed: {methods_dict.get('error')}")
    
    # Step 4: Get source code for a specific method
    logger.info("\n📜 Step 4: Getting source code for 'main' method...")
    source_result = await client.call_tool("get_method_source", {
        "session_id": session_id,
        "method_name": "main"
    })
    source_dict = extract_tool_result(source_result)
    
    if source_dict.get("success"):
        methods = source_dict.get("methods", [])
        if methods:
            m = methods[0]
            logger.info(f"  ✅ Found method: {m['name']} at {m['filename']}:{m['lineNumber']}")
            code = m['code']
            # Show first few lines
            code_lines = code.split('\n')[:10]
            logger.info(f"  Source code (first 10 lines):")
            for line in code_lines:
                logger.info(f"    {line}")
            if len(code.split('\n')) > 10:
                logger.info(f"    ... and {len(code.split('\n')) - 10} more lines")
        else:
            logger.info("  ℹ️  No methods found matching 'main'")
    else:
        logger.error(f"  ❌ Failed: {source_dict.get('error')}")
    
    # Step 5: Get method parameters
    logger.info("\n📋 Step 5: Getting parameters for 'main'...")
    params_result = await client.call_tool("list_parameters", {
        "session_id": session_id,
        "method_name": "main"
    })
    params_dict = extract_tool_result(params_result)
    
    if params_dict.get("success"):
        methods = params_dict.get("methods", [])
        if methods:
            m = methods[0]
            logger.info(f"  ✅ Method: {m['method']}")
            params = m.get('parameters', [])
            if params:
                logger.info(f"  Parameters:")
                for p in params:
                    logger.info(f"     {p['index']}. {p['name']} : {p['type']}")
            else:
                logger.info(f"  No parameters")
        else:
            logger.info("  ℹ️  No methods found")
    else:
        logger.error(f"  ❌ Failed: {params_dict.get('error')}")
    
    # Step 6: Understand what methods 'main' calls
    logger.info("\n🔗 Step 6: Getting call graph for 'main' (outgoing)...")
    callgraph_result = await client.call_tool("get_call_graph", {
        "session_id": session_id,
        "method_name": "main",
        "depth": 2,
        "direction": "outgoing"
    })
    callgraph_dict = extract_tool_result(callgraph_result)
    
    if callgraph_dict.get("success"):
        calls = callgraph_dict.get("calls", [])
        logger.info(f"  ✅ Found {len(calls)} calls:")
        for c in calls[:10]:
            indent = "  " * c['depth']
            logger.info(f"     {indent}[depth {c['depth']}] {c['from']} -> {c['to']}")
        if len(calls) > 10:
            logger.info(f"     ... and {len(calls) - 10} more")
    else:
        logger.error(f"  ❌ Failed: {callgraph_dict.get('error')}")
    
    # Step 7: Find hardcoded strings
    logger.info("\n🔍 Step 7: Finding hardcoded string literals...")
    literals_result = await client.call_tool("find_literals", {
        "session_id": session_id,
        "pattern": ".*",
        "limit": 10
    })
    literals_dict = extract_tool_result(literals_result)
    
    if literals_dict.get("success"):
        literals = literals_dict.get("literals", [])
        logger.info(f"  ✅ Found {len(literals)} literals:")
        for lit in literals[:8]:
            value = lit['value'][:50] if len(lit['value']) > 50 else lit['value']
            logger.info(f"     - {value} (type: {lit['type']}) at {lit['filename']}:{lit['lineNumber']}")
        if len(literals) > 8:
            logger.info(f"     ... and {len(literals) - 8} more")
    else:
        logger.error(f"  ❌ Failed: {literals_dict.get('error')}")


async def security_review_workflow(client, session_id):
    """
    Demonstrates using browsing tools for security review.
    """
    logger.info("\n" + "="*60)
    logger.info("Workflow 2: Security Review")
    logger.info("="*60)
    
    # 1. Find authentication-related methods
    logger.info("\n🔐 Step 1: Finding authentication methods...")
    find_auth_result = await client.call_tool("list_methods", {
        "session_id": session_id,
        "name_pattern": ".*(?i)(auth|login|password|credential).*",
        "include_external": False,
        "limit": 20
    })
    find_auth_dict = extract_tool_result(find_auth_result)
    
    if find_auth_dict.get("success"):
        methods = find_auth_dict.get("methods", [])
        if methods:
            logger.info(f"  ⚠️  Found {len(methods)} authentication-related methods:")
            for m in methods[:5]:
                logger.info(f"     - {m['name']} at {m['filename']}:{m['lineNumber']}")
            if len(methods) > 5:
                logger.info(f"     ... and {len(methods) - 5} more")
        else:
            logger.info("  ✅ No authentication methods found")
    else:
        logger.error(f"  ❌ Failed: {find_auth_dict.get('error')}")
    
    # 2. Find hardcoded secrets
    logger.info("\n🔑 Step 2: Finding potential hardcoded secrets...")
    find_secrets_result = await client.call_tool("find_literals", {
        "session_id": session_id,
        "pattern": "(?i).*(password|secret|api_key|token|credential).*",
        "limit": 20
    })
    find_secrets_dict = extract_tool_result(find_secrets_result)
    
    if find_secrets_dict.get("success"):
        literals = find_secrets_dict.get("literals", [])
        if literals:
            logger.info(f"  ⚠️  Found {len(literals)} potential secrets:")
            for lit in literals[:5]:
                value = lit['value'][:40] if len(lit['value']) > 40 else lit['value']
                logger.info(f"     - {value} at {lit['filename']}:{lit['lineNumber']}")
            if len(literals) > 5:
                logger.info(f"     ... and {len(literals) - 5} more")
        else:
            logger.info("  ✅ No hardcoded secrets found")
    else:
        logger.error(f"  ❌ Failed: {find_secrets_dict.get('error')}")
    
    # 3. Find calls to dangerous functions
    logger.info("\n⚠️  Step 3: Finding calls to potentially dangerous functions...")
    find_dangerous_result = await client.call_tool("list_calls", {
        "session_id": session_id,
        "callee_pattern": ".*(exec|system|strcpy|sprintf|gets).*",
        "limit": 20
    })
    find_dangerous_dict = extract_tool_result(find_dangerous_result)
    
    if find_dangerous_dict.get("success"):
        calls = find_dangerous_dict.get("calls", [])
        if calls:
            logger.info(f"  ⚠️  Found {len(calls)} calls to dangerous functions:")
            for c in calls[:5]:
                logger.info(f"     - {c['caller']} -> {c['callee']} at {c['filename']}:{c['lineNumber']}")
                logger.info(f"       Code: {c['code'][:60]}...")
            if len(calls) > 5:
                logger.info(f"     ... and {len(calls) - 5} more")
        else:
            logger.info("  ✅ No dangerous function calls found")
    else:
        logger.error(f"  ❌ Failed: {find_dangerous_dict.get('error')}")


async def code_review_workflow(client, session_id):
    """
    Demonstrates using browsing tools for code review.
    """
    logger.info("\n" + "="*60)
    logger.info("Workflow 3: Code Review")
    logger.info("="*60)
    
    # 1. Find main entry points
    logger.info("\n🚀 Step 1: Finding main entry points...")
    find_main_result = await client.call_tool("list_methods", {
        "session_id": session_id,
        "name_pattern": "main|Main|start|run",
        "include_external": False,
        "limit": 10
    })
    find_main_dict = extract_tool_result(find_main_result)
    
    if find_main_dict.get("success"):
        methods = find_main_dict.get("methods", [])
        logger.info(f"  ✅ Found {len(methods)} entry points:")
        for m in methods:
            logger.info(f"     - {m['name']} at {m['filename']}:{m['lineNumber']}")
            logger.info(f"       Signature: {m['signature']}")
    else:
        logger.error(f"  ❌ Failed: {find_main_dict.get('error')}")
    
    # 2. List function calls to understand control flow
    logger.info("\n📞 Step 2: Listing function calls...")
    list_calls_result = await client.call_tool("list_calls", {
        "session_id": session_id,
        "limit": 15
    })
    list_calls_dict = extract_tool_result(list_calls_result)
    
    if list_calls_dict.get("success"):
        calls = list_calls_dict.get("calls", [])
        logger.info(f"  ✅ Found {len(calls)} function calls:")
        for c in calls[:10]:
            logger.info(f"     - {c['caller']} calls {c['callee']}")
        if len(calls) > 10:
            logger.info(f"     ... and {len(calls) - 10} more")
    else:
        logger.error(f"  ❌ Failed: {list_calls_dict.get('error')}")


async def demonstrate_browsing_tools():
    """Main demo function that runs all workflows"""
    server_url = "http://localhost:4242/mcp"
    
    async with Client(server_url) as client:
        logger.info("🔌 Connected to Joern MCP Server")
        
        # Test server connectivity
        await client.ping()
        logger.info("✅ Server ping successful")
        
        # Create a CPG session from local source
        logger.info("\n📁 Creating CPG session...")
        session_result = await client.call_tool("create_cpg_session", {
            "source_type": "local",
            "source_path": "playground/codebases/sample",
            "language": "c"
        })
        
        session_dict = extract_tool_result(session_result)
        
        if not session_dict.get("session_id"):
            logger.error(f"❌ Session creation failed: {session_dict}")
            return
            
        session_id = session_dict["session_id"]
        status = session_dict.get("status")
        cached = session_dict.get("cached", False)
        
        if cached:
            logger.info(f"✅ Session created (cached CPG): {session_id}")
        else:
            logger.info(f"✅ Session created: {session_id}")
        
        # Wait for CPG to be ready if not cached
        if status != "ready":
            logger.info("⏳ Waiting for CPG generation...")
            for i in range(60):
                status_result = await client.call_tool("get_session_status", {
                    "session_id": session_id
                })
                
                status_dict = extract_tool_result(status_result)
                current_status = status_dict.get("status")
                
                if i % 3 == 0:  # Log every 3 seconds
                    logger.info(f"  Status: {current_status}")
                
                if current_status == "ready":
                    logger.info("✅ CPG is ready")
                    break
                elif current_status == "error":
                    logger.error(f"❌ CPG generation failed: {status_dict.get('error_message')}")
                    return
                    
                await asyncio.sleep(1)
            else:
                logger.error("❌ Timeout waiting for CPG")
                return
        
        # Run all workflows
        try:
            await explore_codebase_workflow(client, session_id)
            await security_review_workflow(client, session_id)
            await code_review_workflow(client, session_id)
        except Exception as e:
            logger.error(f"❌ Workflow error: {e}", exc_info=True)
        
        # Cleanup
        logger.info("\n🧹 Cleaning up...")
        close_result = await client.call_tool("close_session", {
            "session_id": session_id
        })
        
        close_dict = extract_tool_result(close_result)
        
        if close_dict.get("success"):
            logger.info("✅ Session closed successfully")
        else:
            logger.warning(f"⚠️  Failed to close session: {close_dict}")
        
        logger.info("\n🎉 All browsing tool workflows completed!")


async def main():
    """Main function"""
    logger.info("="*60)
    logger.info("Joern-MCP Code Browsing Tools - Live Demo")
    logger.info("="*60)
    logger.info("")
    logger.info("This demo showcases the browsing tools by:")
    logger.info("  1. Exploring an unknown codebase")
    logger.info("  2. Performing a security review")
    logger.info("  3. Conducting a code review")
    logger.info("")
    
    try:
        await demonstrate_browsing_tools()
    except Exception as e:
        logger.error(f"❌ Demo failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
