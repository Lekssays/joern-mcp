"""
MCP Tool Definitions for Joern MCP Server

Main entry point that registers all tools from separate modules
"""

from .core_tools import register_core_tools
from .code_browsing_tools import register_code_browsing_tools
from .taint_analysis_tools import register_taint_analysis_tools


def register_tools(mcp, services: dict):
    """Register all MCP tools with the FastMCP server"""

    # Register core tools (session management and queries)
    register_core_tools(mcp, services)

    # Register code browsing tools (exploring codebase structure)
    register_code_browsing_tools(mcp, services)

    # Register taint analysis tools (security-focused analysis)
    register_taint_analysis_tools(mcp, services)
