#!/usr/bin/env python3
"""
joern-mcp Server - Main entry point using FastMCP

This is the main entry point for the joern-mcp Server that provides static code analysis
capabilities using Joern's Code Property Graph (CPG) technology with interactive shells.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from src.config import load_config
from src.services import (
    SessionManager,
    GitManager,
    CPGGenerator,
    QueryExecutor,
    DockerOrchestrator
)
from src.utils import RedisClient, setup_logging
from src.tools import register_tools

# Global service instances
services = {}

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(mcp: FastMCP):
    """Startup and shutdown logic for the FastMCP server"""
    # Load configuration
    config = load_config("config.yaml")
    setup_logging(config.server.log_level)
    logger.info("Starting joern-mcp Server")
    
    # Ensure required directories exist
    import os
    os.makedirs(config.storage.workspace_root, exist_ok=True)
    os.makedirs("playground/cpgs", exist_ok=True)
    logger.info("Created required directories")
    
    try:
        # Initialize Redis
        redis_client = RedisClient(config.redis)
        await redis_client.connect()
        logger.info("Redis client connected")
        
        # Initialize services
        services['config'] = config
        services['redis'] = redis_client
        services['session_manager'] = SessionManager(redis_client, config.sessions)
        services['git_manager'] = GitManager(config.storage.workspace_root)
        services['cpg_generator'] = CPGGenerator(config.cpg, services['session_manager'])
        
        # Initialize Docker orchestrator
        services['docker'] = DockerOrchestrator()
        await services['docker'].initialize()
        
        # Set up Docker cleanup callback for session manager
        services['session_manager'].set_docker_cleanup_callback(
            services['docker'].stop_container
        )
        
        # Initialize CPG generator
        await services['cpg_generator'].initialize()
        
        # Initialize query executor with reference to CPG generator
        services['query_executor'] = QueryExecutor(
            config.query,
            config.joern,
            redis_client,
            services['cpg_generator']
        )
        
        # Initialize query executor
        await services['query_executor'].initialize()
        
        logger.info("All services initialized")
        logger.info("joern-mcp Server is ready")
        
        yield
        
        # Shutdown
        logger.info("Shutting down joern-mcp Server")
        
        # Cleanup query executor sessions
        await services['query_executor'].cleanup()
        
        # Cleanup Docker containers
        await services['docker'].cleanup()
        
        # Close connections
        await redis_client.close()
        
        logger.info("joern-mcp Server shutdown complete")
        
    except Exception as e:
        logger.error(f"Error during server lifecycle: {e}", exc_info=True)
        raise


# Initialize FastMCP server
mcp = FastMCP(
    "joern-mcp Server",
    lifespan=lifespan
)

# Register MCP tools
register_tools(mcp, services)


if __name__ == "__main__":
    # Run the server with HTTP transport (Streamable HTTP)
    # Get configuration
    config_data = load_config("config.yaml")
    host = config_data.server.host
    port = config_data.server.port
    
    logger.info(f"Starting joern-mcp Server with HTTP transport on {host}:{port}")
    
    # Use HTTP transport (Streamable HTTP) for production deployment
    # This enables network accessibility, multiple concurrent clients,
    # and integration with web infrastructure
    mcp.run(transport="http", host=host, port=port)