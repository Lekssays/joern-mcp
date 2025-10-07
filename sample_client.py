#!/usr/bin/env python3
"""
Sample MCP Client for Joern MCP Server

This demonstrates how to use all the tools available in the joern-mcp server.
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
            "source_path": "playground/codebases/sample",
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
        
        # 5. Run synchronous CPGQL queries
        logger.info("\n🔍 Running synchronous queries...")
        queries = [
            "cpg.method.name",
            "cpg.call.name", 
            "cpg.file.name"
        ]
        
        for query in queries:
            result = await client.call_tool("run_cpgql_query", {
                "session_id": session_id,
                "query": query,
                "timeout": 30
            })
            
            result_dict = extract_tool_result(result)
            
            if result_dict.get("success"):
                count = result_dict.get("row_count", 0)
                time_taken = result_dict.get("execution_time", 0)
                logger.info(f"  ✅ {query}: {count} results in {time_taken:.2f}s")
                
                # Show sample data
                if result_dict.get("data") and len(result_dict["data"]) > 0:
                    data = result_dict["data"]
                    logger.info(f"     First 5 results:")
                    for i, item in enumerate(data[:5]):
                        if isinstance(item, dict) and "value" in item:
                            logger.info(f"       {i+1}. {item['value']}")
                        else:
                            logger.info(f"       {i+1}. {str(item)[:80]}...")
                    if count > 5:
                        logger.info(f"       ... and {count - 5} more")
            else:
                logger.error(f"  ❌ {query}: {result_dict.get('error')}")
        
        # 6. Run asynchronous query
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
        
        # 7. List all queries
        logger.info("\n📊 Listing queries...")
        queries_result = await client.call_tool("list_queries")
        queries_dict = extract_tool_result(queries_result)
        if queries_dict.get("success"):
            total = queries_dict.get("total", 0)
            logger.info(f"  Total queries: {total}")
        
        # 8. List all sessions
        logger.info("\n📋 Listing sessions...")
        sessions_result = await client.call_tool("list_sessions")
        sessions_dict = extract_tool_result(sessions_result)
        if sessions_dict.get("sessions"):
            total = sessions_dict.get("total", 0)
            logger.info(f"  Total sessions: {total}")
            
            for session in sessions_dict["sessions"]:
                logger.info(f"    {session['session_id']}: {session['status']} ({session['language']})")
        
        # 9. Filter sessions by status
        logger.info("\n🔎 Filtering sessions...")
        ready_sessions_result = await client.call_tool("list_sessions", {"status": "ready"})
        ready_sessions_dict = extract_tool_result(ready_sessions_result)
        if ready_sessions_dict.get("sessions"):
            count = len(ready_sessions_dict["sessions"])
            logger.info(f"  Ready sessions: {count}")
        
        # 10. GitHub session example (commented out to avoid actual cloning)
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
        
        # 11. Cleanup queries
        logger.info("\n🧹 Cleaning up queries...")
        cleanup_result = await client.call_tool("cleanup_queries", {
            "max_age_hours": 0  # Clean all
        })
        
        cleanup_dict = extract_tool_result(cleanup_result)
        
        if cleanup_dict.get("success"):
            cleaned = cleanup_dict.get("cleaned_up", 0)
            logger.info(f"  ✅ Cleaned up {cleaned} queries")
        
        # 12. Close session
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