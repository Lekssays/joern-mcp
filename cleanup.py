#!/usr/bin/env python3
"""
Cleanup script for Joern MCP Server

This script helps clean up various resources:
- Redis data (sessions, query cache)
- Session files and directories
- CPG files (with optional flag)
- Docker containers

Usage:
    python cleanup.py --all                    # Clean everything except CPGs
    python cleanup.py --redis                  # Clean only Redis data
    python cleanup.py --sessions               # Clean only session files
    python cleanup.py --cpgs                   # Clean only CPG files
    python cleanup.py --docker                 # Clean only Docker containers
    python cleanup.py --redis --sessions       # Clean Redis and sessions
    python cleanup.py --all --include-cpgs     # Clean everything including CPGs
"""

import argparse
import asyncio
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import List

# Add src to path so we can import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    import docker
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from src.config import load_config
from src.utils.logging import setup_logging

logger = logging.getLogger(__name__)


class JoernMCPCleaner:
    """Cleanup utility for Joern MCP Server resources"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config = load_config(config_path)
        self.redis_client = None
        self.docker_client = None
        
    async def initialize(self):
        """Initialize clients"""
        # Initialize Redis client
        if REDIS_AVAILABLE:
            try:
                self.redis_client = redis.Redis(
                    host=self.config.redis.host,
                    port=self.config.redis.port,
                    password=self.config.redis.password,
                    db=self.config.redis.db,
                    decode_responses=self.config.redis.decode_responses
                )
                await self.redis_client.ping()
                logger.info("Redis client connected")
            except Exception as e:
                logger.warning(f"Could not connect to Redis: {e}")
                self.redis_client = None
        
        # Initialize Docker client
        if DOCKER_AVAILABLE:
            try:
                self.docker_client = docker.from_env()
                self.docker_client.ping()
                logger.info("Docker client connected")
            except Exception as e:
                logger.warning(f"Could not connect to Docker: {e}")
                self.docker_client = None
    
    async def cleanup_redis(self) -> bool:
        """Clean up Redis data"""
        if not self.redis_client:
            logger.error("Redis client not available")
            return False
            
        try:
            logger.info("🧹 Cleaning up Redis data...")
            
            # Get all keys
            all_keys = await self.redis_client.keys("*")
            
            if not all_keys:
                logger.info("  No Redis keys found")
                return True
                
            # Delete keys by pattern
            patterns = [
                "session:*",      # Session data
                "sessions:*",     # Session sets (like sessions:active)
                "query:*",        # Query cache
                "container:*",    # Container mappings
                "joern:*"         # Any joern-specific data
            ]
            
            deleted_count = 0
            for pattern in patterns:
                keys = await self.redis_client.keys(pattern)
                if keys:
                    deleted = await self.redis_client.delete(*keys)
                    deleted_count += deleted
                    logger.info(f"    Deleted {deleted} keys matching '{pattern}'")
            
            logger.info(f"  ✅ Deleted {deleted_count} Redis keys total")
            return True
            
        except Exception as e:
            logger.error(f"  ❌ Failed to cleanup Redis: {e}")
            return False
    
    async def cleanup_sessions(self) -> bool:
        """Clean up session files and directories"""
        try:
            logger.info("🧹 Cleaning up session files...")
            
            workspace_root = Path(self.config.storage.workspace_root)
            
            if not workspace_root.exists():
                logger.info("  No workspace directory found")
                return True
            
            deleted_dirs = 0
            deleted_files = 0
            
            # Clean up workspace directories
            if workspace_root.exists():
                for item in workspace_root.iterdir():
                    if item.is_dir():
                        try:
                            shutil.rmtree(item)
                            deleted_dirs += 1
                            logger.info(f"    Deleted directory: {item.name}")
                        except Exception as e:
                            logger.error(f"    Failed to delete {item}: {e}")
                    elif item.is_file():
                        try:
                            item.unlink()
                            deleted_files += 1
                            logger.info(f"    Deleted file: {item.name}")
                        except Exception as e:
                            logger.error(f"    Failed to delete {item}: {e}")
            
            # Clean up playground session directories
            playground_path = Path("playground/codebases")
            if playground_path.exists():
                for item in playground_path.iterdir():
                    # Skip the sample directory
                    if item.name == "sample":
                        continue
                        
                    if item.is_dir():
                        try:
                            shutil.rmtree(item)
                            deleted_dirs += 1
                            logger.info(f"    Deleted playground directory: {item.name}")
                        except Exception as e:
                            logger.error(f"    Failed to delete playground {item}: {e}")
            
            logger.info(f"  ✅ Deleted {deleted_dirs} directories and {deleted_files} files")
            return True
            
        except Exception as e:
            logger.error(f"  ❌ Failed to cleanup sessions: {e}")
            return False
    
    async def cleanup_cpgs(self) -> bool:
        """Clean up CPG files"""
        try:
            logger.info("🧹 Cleaning up CPG files...")
            
            # Clean CPGs from playground
            playground_cpgs = Path("playground/cpgs")
            deleted_count = 0
            
            if playground_cpgs.exists():
                for cpg_file in playground_cpgs.glob("*.bin"):
                    try:
                        file_size = cpg_file.stat().st_size / (1024 * 1024)  # MB
                        cpg_file.unlink()
                        deleted_count += 1
                        logger.info(f"    Deleted CPG: {cpg_file.name} ({file_size:.2f} MB)")
                    except Exception as e:
                        logger.error(f"    Failed to delete {cpg_file}: {e}")
            
            # Clean CPGs from workspace
            workspace_root = Path(self.config.storage.workspace_root)
            if workspace_root.exists():
                for cpg_file in workspace_root.rglob("*.bin"):
                    try:
                        file_size = cpg_file.stat().st_size / (1024 * 1024)  # MB
                        cpg_file.unlink()
                        deleted_count += 1
                        logger.info(f"    Deleted workspace CPG: {cpg_file.name} ({file_size:.2f} MB)")
                    except Exception as e:
                        logger.error(f"    Failed to delete {cpg_file}: {e}")
            
            logger.info(f"  ✅ Deleted {deleted_count} CPG files")
            return True
            
        except Exception as e:
            logger.error(f"  ❌ Failed to cleanup CPGs: {e}")
            return False
    
    async def cleanup_docker(self) -> bool:
        """Clean up Docker containers"""
        if not self.docker_client:
            logger.error("Docker client not available")
            return False
            
        try:
            logger.info("🧹 Cleaning up Docker containers...")
            
            # Find all joern-session containers
            containers = self.docker_client.containers.list(
                all=True,  # Include stopped containers
                filters={"name": "joern-session-"}
            )
            
            if not containers:
                logger.info("  No Joern session containers found")
                return True
            
            cleaned_count = 0
            for container in containers:
                try:
                    # Stop if running
                    if container.status == "running":
                        container.stop(timeout=5)
                        logger.info(f"    Stopped container: {container.name}")
                    
                    # Remove container
                    container.remove()
                    cleaned_count += 1
                    logger.info(f"    Removed container: {container.name}")
                    
                except Exception as e:
                    logger.error(f"    Failed to cleanup container {container.name}: {e}")
            
            logger.info(f"  ✅ Cleaned up {cleaned_count} Docker containers")
            return True
            
        except Exception as e:
            logger.error(f"  ❌ Failed to cleanup Docker: {e}")
            return False
    
    async def cleanup_all(self, include_cpgs: bool = False) -> bool:
        """Clean up all resources"""
        logger.info("🧹 Starting full cleanup...")
        
        results = []
        
        # Clean Redis
        results.append(await self.cleanup_redis())
        
        # Clean sessions
        results.append(await self.cleanup_sessions())
        
        # Clean CPGs if requested
        if include_cpgs:
            results.append(await self.cleanup_cpgs())
        
        # Clean Docker
        results.append(await self.cleanup_docker())
        
        success = all(results)
        
        if success:
            logger.info("🎉 Full cleanup completed successfully!")
        else:
            logger.warning("⚠️  Some cleanup operations failed")
            
        return success
    
    async def close(self):
        """Close connections"""
        if self.redis_client:
            await self.redis_client.aclose()
        
        if self.docker_client:
            self.docker_client.close()


async def main():
    """Main cleanup function"""
    parser = argparse.ArgumentParser(
        description="Cleanup Joern MCP Server resources",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cleanup.py --all                    # Clean everything except CPGs
  python cleanup.py --redis --sessions       # Clean Redis and sessions only
  python cleanup.py --all --include-cpgs     # Clean everything including CPGs
  python cleanup.py --cpgs                   # Clean only CPG files
  python cleanup.py --docker                 # Clean only Docker containers
        """
    )
    
    parser.add_argument("--redis", action="store_true", help="Clean Redis data")
    parser.add_argument("--sessions", action="store_true", help="Clean session files")
    parser.add_argument("--cpgs", action="store_true", help="Clean CPG files")
    parser.add_argument("--docker", action="store_true", help="Clean Docker containers")
    parser.add_argument("--all", action="store_true", help="Clean all resources (except CPGs unless --include-cpgs)")
    parser.add_argument("--include-cpgs", action="store_true", help="Include CPG files when using --all")
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be cleaned without doing it")
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(log_level)
    
    # Check if any cleanup option is specified
    if not any([args.redis, args.sessions, args.cpgs, args.docker, args.all]):
        parser.print_help()
        print("\nError: At least one cleanup option must be specified")
        sys.exit(1)
    
    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - No changes will be made")
        # In a real implementation, you'd add dry-run logic
        logger.warning("Dry-run mode not fully implemented yet")
        return
    
    # Confirm destructive operations
    if args.all or args.cpgs:
        print("\n⚠️  WARNING: This will permanently delete data!")
        if args.all:
            print("   - Redis data (sessions, query cache)")
            print("   - Session files and directories")
            print("   - Docker containers")
        if args.cpgs or (args.all and args.include_cpgs):
            print("   - CPG files (can be large and take time to regenerate)")
        
        confirm = input("\nContinue? [y/N]: ")
        if confirm.lower() != 'y':
            print("Cleanup cancelled")
            return
    
    try:
        # Initialize cleaner
        cleaner = JoernMCPCleaner(args.config)
        await cleaner.initialize()
        
        success = True
        
        # Perform requested cleanups
        if args.all:
            success = await cleaner.cleanup_all(include_cpgs=args.include_cpgs)
        else:
            if args.redis:
                success &= await cleaner.cleanup_redis()
            
            if args.sessions:
                success &= await cleaner.cleanup_sessions()
            
            if args.cpgs:
                success &= await cleaner.cleanup_cpgs()
            
            if args.docker:
                success &= await cleaner.cleanup_docker()
        
        await cleaner.close()
        
        if success:
            logger.info("✅ Cleanup completed successfully")
        else:
            logger.error("❌ Some cleanup operations failed")
            sys.exit(1)
            
    except KeyboardInterrupt:
        logger.info("\n🛑 Cleanup interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"❌ Cleanup failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())