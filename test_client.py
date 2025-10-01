#!/usr/bin/env python3
"""
Simple test client for the Joern MCP Server.

This client demonstrates how to interact with the Joern MCP Server programmatically.
"""

import asyncio
import json
import sys
from pathlib import Path

from src.server import JoernMCPServer
from src.config import load_config


async def test_basic_functionality():
    """Test basic server functionality"""
    print("🚀 Starting Joern MCP Server test...")
    print("📝 Note: Ensure Docker image is built with: docker build -t joern:latest .")
    
    # Load configuration
    config = load_config()
    server = JoernMCPServer(config)
    
    try:
        # Initialize Docker
        print("🐳 Initializing Docker...")
        await server.initialize_docker()
        print("✅ Docker initialized")
        
        # Load sample project
        sample_path = Path(__file__).parent / "examples" / "sample.c"
        if not sample_path.exists():
            print(f"❌ Sample file not found: {sample_path}")
            return
        
        print(f"📁 Loading project from: {sample_path.parent}")
        load_result = await server.load_project(str(sample_path.parent))
        
        if not load_result["success"]:
            print(f"❌ Failed to load project: {load_result}")
            return
        
        project_id = load_result["project_id"]
        print(f"✅ Project loaded with ID: {project_id}")
        
        # List projects
        print("📋 Listing projects...")
        projects_result = await server.list_projects()
        print(f"Projects: {len(projects_result['projects'])}")
        
        # Generate CPG
        print("🔧 Generating CPG...")
        cpg_result = await server.generate_cpg(project_id)
        
        if not cpg_result["success"]:
            print(f"❌ Failed to generate CPG: {cpg_result}")
            return
        
        print(f"✅ CPG generated at: {cpg_result['cpg_path']}")
        
        # Run a simple query
        print("🔍 Running query...")
        query = "cpg.method.l"
        query_result = await server.run_query(project_id, query)
        
        if query_result["success"]:
            methods_count = len(query_result["results"])
            print(f"✅ Query executed successfully, found {methods_count} methods")
            
            # Show first few results
            if query_result["results"]:
                print("📊 Sample results:")
                for i, method in enumerate(query_result["results"][:3]):
                    name = method.get("name", "unknown")
                    print(f"  {i+1}. {name}")
        else:
            print(f"❌ Query failed: {query_result['error']}")
        
        # List available queries
        print("📚 Available pre-built queries...")
        queries_result = await server.list_queries("security")
        if queries_result["success"]:
            security_queries = queries_result["queries"]["security"]
            print(f"Security queries available: {len(security_queries)}")
            for name in list(security_queries.keys())[:3]:
                print(f"  - {name}")
        
        # Cleanup
        print("🧹 Cleaning up...")
        cleanup_result = await server.cleanup_project(project_id)
        if cleanup_result["success"]:
            print("✅ Cleanup completed")
        
        print("🎉 Test completed successfully!")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_basic_functionality())