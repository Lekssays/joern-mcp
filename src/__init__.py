"""Joern MCP Server - A Model Context Protocol server for static code analysis using Joern."""

__version__ = "1.0.0"
__author__ = "Joern MCP Team"
__email__ = "contact@joern-mcp.dev"

from .server import JoernMCPServer

__all__ = ["JoernMCPServer"]