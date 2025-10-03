#!/usr/bin/env python3
"""
Joern MCP Server - Main entry point

This is the main entry point for the Joern MCP Server that provides static code analysis
capabilities using Joern's Code Property Graph (CPG) technology.
"""

import asyncio
import sys
from pathlib import Path

from src.server import JoernMCPServer
from src.config import load_config


def main():
    """Main entry point for the Joern MCP Server"""
    config_path = None
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
        if not Path(config_path).exists():
            print(f"Error: Configuration file not found: {config_path}")
            sys.exit(1)
    
    try:
        # Load configuration
        config = load_config(config_path)
        
        # Create and run server
        server = JoernMCPServer(config)
        asyncio.run(server.run())
        
    except KeyboardInterrupt:
        print("\nShutting down Joern MCP Server...")
        sys.exit(0)
    except Exception as e:
        import traceback
        print(f"Error starting server: {e}")
        print("Full traceback:")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()