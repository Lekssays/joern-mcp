#!/usr/bin/env python3
"""
Joern MCP Server - A Model Context Protocol server for static code analysis using Joern

This server provides AI assistants with the ability to perform static code analysis
using Joern's Code Property Graph (CPG) technology in isolated Docker environments.
"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import hashlib

import docker
from docker.errors import DockerException, ContainerError, ImageNotFound
import git
from git.exc import GitError
from pydantic import BaseModel, Field
from mcp.server.models import InitializationOptions
from mcp.server import Server
from mcp.types import Tool, TextContent

from .models import (
    ServerConfig, ProjectInfo, QueryResult, 
    JoernMCPError, ProjectLoadError, CPGGenerationError, QueryExecutionError
)
from .utils import detect_project_language, calculate_loc


class JoernMCPServer:
    """Main Joern MCP Server implementation"""
    
    def __init__(self, config: Optional[ServerConfig] = None):
        self.config = config or ServerConfig()
        self.docker_client = None
        self.projects: Dict[str, ProjectInfo] = {}
        self.server = Server("joern-mcp-server")
        self.logger = self._setup_logging()
        self.cache_dir = Path(self.config.cache.directory)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._setup_handlers()
        
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logging.basicConfig(
            level=getattr(logging, self.config.log_level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        return logging.getLogger(__name__)
    
    def _setup_handlers(self):
        """Setup MCP server handlers"""
        
        @self.server.list_tools()
        async def handle_list_tools() -> List[Tool]:
            """List available tools"""
            return [
                Tool(
                    name="load_project",
                    description="Load a project from GitHub URL or local path",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "source": {
                                "type": "string",
                                "description": "GitHub URL or local file path"
                            },
                            "branch": {
                                "type": "string",
                                "description": "Git branch/tag/commit (for GitHub sources)"
                            }
                        },
                        "required": ["source"]
                    }
                ),
                Tool(
                    name="generate_cpg",
                    description="Generate Code Property Graph for a loaded project",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project_id": {
                                "type": "string",
                                "description": "ID of the loaded project"
                            },
                            "language": {
                                "type": "string",
                                "description": "Override auto-detected language"
                            }
                        },
                        "required": ["project_id"]
                    }
                ),
                Tool(
                    name="run_query",
                    description="Execute a Joern query against a project's CPG",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project_id": {
                                "type": "string",
                                "description": "ID of the project with generated CPG"
                            },
                            "query": {
                                "type": "string",
                                "description": "Joern query to execute"
                            },
                            "format": {
                                "type": "string",
                                "enum": ["json", "csv", "table"],
                                "default": "json",
                                "description": "Output format for results"
                            }
                        },
                        "required": ["project_id", "query"]
                    }
                ),
                Tool(
                    name="list_projects",
                    description="List all loaded projects",
                    inputSchema={
                        "type": "object",
                        "properties": {}
                    }
                ),
                Tool(
                    name="project_info",
                    description="Get detailed information about a project",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project_id": {
                                "type": "string",
                                "description": "ID of the project"
                            }
                        },
                        "required": ["project_id"]
                    }
                ),
                Tool(
                    name="list_queries",
                    description="List available pre-built security and quality queries",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "category": {
                                "type": "string",
                                "enum": ["security", "quality", "metrics", "all"],
                                "default": "all"
                            }
                        }
                    }
                ),
                Tool(
                    name="cleanup_project",
                    description="Clean up project resources and remove from memory",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "project_id": {
                                "type": "string",
                                "description": "ID of the project to cleanup"
                            }
                        },
                        "required": ["project_id"]
                    }
                )
            ]

        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
            """Handle tool calls"""
            try:
                if name == "load_project":
                    result = await self.load_project(**arguments)
                elif name == "generate_cpg":
                    result = await self.generate_cpg(**arguments)
                elif name == "run_query":
                    result = await self.run_query(**arguments)
                elif name == "list_projects":
                    result = await self.list_projects()
                elif name == "project_info":
                    result = await self.project_info(**arguments)
                elif name == "list_queries":
                    result = await self.list_queries(**arguments)
                elif name == "cleanup_project":
                    result = await self.cleanup_project(**arguments)
                else:
                    raise ValueError(f"Unknown tool: {name}")
                
                return [TextContent(type="text", text=json.dumps(result, indent=2))]
                
            except Exception as e:
                self.logger.error(f"Error in tool {name}: {str(e)}", exc_info=True)
                error_result = {
                    "success": False,
                    "error": str(e),
                    "tool": name,
                    "arguments": arguments
                }
                return [TextContent(type="text", text=json.dumps(error_result, indent=2))]

    async def initialize_docker(self):
        """Initialize Docker client"""
        try:
            self.docker_client = docker.from_env()
            # Test connection
            self.docker_client.ping()
            self.logger.info("Docker client initialized successfully")
            
            # Ensure Joern image is available
            await self._ensure_joern_image()
            
        except DockerException as e:
            self.logger.error(f"Failed to initialize Docker client: {e}")
            raise JoernMCPError(f"Docker initialization failed: {e}")
    
    async def _ensure_joern_image(self):
        """Ensure Joern Docker image is available"""
        try:
            self.docker_client.images.get(self.config.docker.image)
            self.logger.info(f"Joern image {self.config.docker.image} found")
        except ImageNotFound:
            self.logger.info(f"Pulling Joern image {self.config.docker.image}...")
            self.docker_client.images.pull(self.config.docker.image)
            self.logger.info("Joern image pulled successfully")

    def _generate_project_id(self, source: str) -> str:
        """Generate unique project ID from source"""
        return hashlib.md5(source.encode()).hexdigest()[:8]
    
    async def load_project(self, source: str, branch: Optional[str] = None) -> Dict[str, Any]:
        """Load project from GitHub or local path"""
        self.logger.info(f"Loading project from: {source}")
        
        project_id = self._generate_project_id(source)
        temp_dir = None
        
        try:
            # Determine source type
            if source.startswith(('http://', 'https://')) and 'github.com' in source:
                # GitHub source
                temp_dir = await self._clone_github_repo(source, branch)
                source_type = "github"
            else:
                # Local source
                source_path = Path(source).resolve()
                if not source_path.exists():
                    raise ProjectLoadError(f"Local path does not exist: {source}")
                temp_dir = source_path
                source_type = "local"
            
            # Detect languages
            languages = detect_project_language(temp_dir)
            if not any(lang in self.config.supported_languages for lang in languages):
                raise ProjectLoadError(f"Unsupported languages detected: {languages}")
            
            # Calculate LOC
            loc = calculate_loc(temp_dir, languages)
            
            # Create project info
            project_info = ProjectInfo(
                id=project_id,
                source_type=source_type,
                source_path=str(temp_dir),
                languages=languages,
                size_loc=loc
            )
            
            self.projects[project_id] = project_info
            
            self.logger.info(f"Project loaded successfully: {project_id}")
            return {
                "success": True,
                "project_id": project_id,
                "project_info": project_info.dict()
            }
            
        except Exception as e:
            if temp_dir and source_type == "github":
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise ProjectLoadError(f"Failed to load project: {str(e)}")
    
    async def _clone_github_repo(self, url: str, branch: Optional[str] = None) -> Path:
        """Clone GitHub repository to temporary directory"""
        temp_dir = Path(tempfile.mkdtemp(prefix="joern_project_"))
        
        try:
            clone_kwargs = {
                'depth': 1,  # Shallow clone by default
                'single_branch': True
            }
            
            if branch:
                clone_kwargs['branch'] = branch
            
            # Add authentication if available
            if self.config.github_token:
                parsed = urlparse(url)
                auth_url = f"https://{self.config.github_token}@{parsed.netloc}{parsed.path}"
                git.Repo.clone_from(auth_url, temp_dir, **clone_kwargs)
            else:
                git.Repo.clone_from(url, temp_dir, **clone_kwargs)
            
            return temp_dir
            
        except GitError as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise ProjectLoadError(f"Failed to clone repository: {str(e)}")
    
    async def generate_cpg(self, project_id: str, language: Optional[str] = None) -> Dict[str, Any]:
        """Generate Code Property Graph for project"""
        if project_id not in self.projects:
            raise CPGGenerationError(f"Project not found: {project_id}")
        
        project = self.projects[project_id]
        project.last_accessed = time.time()
        
        self.logger.info(f"Generating CPG for project: {project_id}")
        
        # Check cache first
        cache_key = f"{project_id}_{language or 'auto'}"
        cached_cpg = await self._get_cached_cpg(cache_key)
        if cached_cpg:
            project.cpg_generated = True
            project.cpg_path = cached_cpg
            return {
                "success": True,
                "project_id": project_id,
                "cpg_path": cached_cpg,
                "from_cache": True
            }
        
        try:
            # Determine language
            target_language = language or project.languages[0]
            if target_language not in self.config.supported_languages:
                raise CPGGenerationError(f"Unsupported language: {target_language}")
            
            # Generate CPG using Docker
            cpg_path = await self._run_cpg_generation(project, target_language)
            
            # Cache the CPG
            await self._cache_cpg(cache_key, cpg_path)
            
            project.cpg_generated = True
            project.cpg_path = cpg_path
            
            return {
                "success": True,
                "project_id": project_id,
                "cpg_path": cpg_path,
                "language": target_language,
                "from_cache": False
            }
            
        except Exception as e:
            raise CPGGenerationError(f"CPG generation failed: {str(e)}")
    
    async def _run_cpg_generation(self, project: ProjectInfo, language: str) -> str:
        """Run CPG generation in Docker container"""
        if not self.docker_client:
            await self.initialize_docker()
        
        # Create output directory
        output_dir = self.cache_dir / f"cpg_{project.id}"
        output_dir.mkdir(exist_ok=True)
        
        try:
            # If C or C++ project, prefer the c2cpg frontend which produces a cpg directly
            if language in ("c", "cpp"):
                self.logger.info("Using c2cpg frontend for C/C++ project")

                container = self.docker_client.containers.run(
                    self.config.docker.image,
                    command=f"/opt/joern/joern-cli/c2cpg.sh /app/input -o /app/output/cpg.bin",
                    volumes={
                        str(Path(project.source_path)): {'bind': '/app/input', 'mode': 'ro'},
                        str(output_dir): {'bind': '/app/output', 'mode': 'rw'}
                    },
                    working_dir='/app',
                    environment={
                        "JAVA_OPTS": "-Xmx4g",
                        "PATH": "/opt/joern:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
                    },
                    network_mode=self.config.docker.network_mode,
                    mem_limit=self.config.docker.memory_limit,
                    detach=True,
                    remove=False
                )

                try:
                    result = container.wait(timeout=self.config.docker.timeout)
                    logs = container.logs().decode('utf-8')

                    if result['StatusCode'] != 0:
                        raise CPGGenerationError(f"CPG generation failed (code {result['StatusCode']}): {logs}")

                    cpg_path = output_dir / "cpg.bin"
                    if not cpg_path.exists():
                        raise CPGGenerationError("CPG file not generated. Logs:\n" + logs)

                    self.logger.info(f"Successfully generated CPG at {cpg_path}")
                    return str(cpg_path)

                except Exception as e:
                    self.logger.error(f"Error during CPG generation: {str(e)}")
                    try:
                        container.kill()
                    except:
                        pass
                    raise CPGGenerationError(f"Failed to generate CPG: {str(e)}")

            # Fallback: try the Joern REPL scripting approach for other languages
            else:
                # Create the Joern script
                script_dir = Path(tempfile.mkdtemp(prefix="joern_script_"))
                script_path = script_dir / "query.sc"

                script = """
workspace.reset
val cpg = importCode("/app/input")
println("CPG generation completed")
System.exit(0)
"""
                with open(script_path, 'w') as f:
                    f.write(script)

                container = self.docker_client.containers.run(
                    self.config.docker.image,
                    command="/opt/joern/joern-cli/joern --script /app/script/query.sc",
                    volumes={
                        str(Path(project.source_path)): {'bind': '/app/input', 'mode': 'ro'},
                        str(output_dir): {'bind': '/app/output', 'mode': 'rw'},
                        str(script_dir): {'bind': '/app/script', 'mode': 'ro'}
                    },
                    working_dir='/app',
                    environment={
                        "JAVA_OPTS": "-Xmx4g",
                        "PATH": "/opt/joern:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
                    },
                    network_mode=self.config.docker.network_mode,
                    mem_limit=self.config.docker.memory_limit,
                    detach=True,
                    remove=False
                )

                # Wait for completion with timeout and capture logs
                try:
                    result = container.wait(timeout=self.config.docker.timeout)
                    logs = container.logs().decode('utf-8')

                    if result['StatusCode'] != 0:
                        raise CPGGenerationError(f"CPG generation failed (code {result['StatusCode']}): {logs}")

                    # Verify CPG was created
                    cpg_path = output_dir / "cpg.bin"
                    if not cpg_path.exists():
                        raise CPGGenerationError("CPG file not generated. Logs:\n" + logs)

                    self.logger.info(f"Successfully generated CPG at {cpg_path}")
                    return str(cpg_path)

                except Exception as e:
                    self.logger.error(f"Error during CPG generation: {str(e)}")
                    try:
                        container.kill()
                    except:
                        pass
                    raise CPGGenerationError(f"Failed to generate CPG: {str(e)}")
                finally:
                    try:
                        shutil.rmtree(script_dir)
                    except:
                        pass

        except ContainerError as e:
            raise CPGGenerationError(f"Docker container error: {str(e)}")

    async def run_query(self, project_id: str, query: str, format: str = "json") -> Dict[str, Any]:
        """Execute Joern query against project CPG"""
        if project_id not in self.projects:
            raise QueryExecutionError(f"Project not found: {project_id}")
        
        project = self.projects[project_id]
        if not project.cpg_generated or not project.cpg_path:
            raise QueryExecutionError(f"CPG not generated for project: {project_id}")
        
        project.last_accessed = time.time()
        
        self.logger.info(f"Running query on project {project_id}: {query[:100]}...")
        
        start_time = time.time()
        
        try:
            results = await self._execute_joern_query(project, query, format)
            execution_time = time.time() - start_time
            
            query_result = QueryResult(
                query=query,
                success=True,
                results=results,
                execution_time=execution_time
            )
            
            return query_result.dict()
            
        except Exception as e:
            execution_time = time.time() - start_time
            query_result = QueryResult(
                query=query,
                success=False,
                error=str(e),
                execution_time=execution_time
            )
            return query_result.dict()
    
    async def _execute_joern_query(self, project: ProjectInfo, query: str, format: str) -> List[Dict[str, Any]]:
        """Execute query in Docker container"""
        if not self.docker_client:
            await self.initialize_docker()
        
        # Create temporary directory for query execution
        temp_dir = Path(tempfile.mkdtemp(prefix="joern_query_"))

        try:
            # Sanitize the incoming query: ensure loadCpg(...) yields a Cpg (not Option[Cpg])
            sanitized_query = query.replace('loadCpg("/app/cpg/cpg.bin")', 'loadCpg("/app/cpg/cpg.bin").get')
            sanitized_query = sanitized_query.replace('val cpg = loadCpg("/app/cpg/cpg.bin")', 'val cpg = loadCpg("/app/cpg/cpg.bin").get')
            # Normalize accidental double .get from repeated replacements
            sanitized_query = sanitized_query.replace('.get.get', '.get')

            # Use Joern's built-in JSON execution directives for proper serialization
            if format == "json":
                template = r"""
workspace.reset
val cpg = loadCpg("/app/cpg/cpg.bin").get
val result = {
%QUERY%
}

// Use Joern's toJsonPretty directive for proper serialization
import java.nio.file.Files
import java.nio.file.Paths
val jsonOutput = result.toJsonPretty
Files.write(Paths.get("/app/output/results.json"), jsonOutput.getBytes("utf-8"))
"""

                joern_script = template.replace("%QUERY%", sanitized_query)
            else:
                # For non-json formats, just print the selected output
                template = r"""
workspace.reset
val cpg = loadCpg("/app/cpg/cpg.bin").get
val result = {
%QUERY%
}
println(result.toList)
"""

                joern_script = template.replace("%QUERY%", sanitized_query)

            script_path = temp_dir / "query.sc"
            with open(script_path, 'w') as f:
                f.write(joern_script)

            # Run query in container
            container = self.docker_client.containers.run(
                self.config.docker.image,
                command="/opt/joern/joern-cli/joern --script /app/output/query.sc",
                volumes={
                    str(temp_dir): {'bind': '/app/output', 'mode': 'rw'},
                    str(Path(project.cpg_path).parent): {'bind': '/app/cpg', 'mode': 'ro'}
                },
                working_dir='/app',
                environment={
                    "JAVA_OPTS": "-Xmx4g",
                    "PATH": "/opt/joern:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
                },
                network_mode=self.config.docker.network_mode,
                mem_limit=self.config.docker.memory_limit,
                detach=True,
                remove=False
            )

            # Wait for completion
            try:
                result = container.wait(timeout=self.config.docker.timeout)
                logs = container.logs().decode('utf-8')

                if result['StatusCode'] != 0:
                    raise QueryExecutionError(f"Query execution failed: {logs}")

                # Read results from results.json if created by script
                results_path = temp_dir / "results.json"
                if results_path.exists():
                    with open(results_path, 'r') as f:
                        # Joern's toJsonPretty returns a valid JSON string that we can parse directly
                        raw = json.loads(f.read())
                        return self._normalize_results(raw)

                # If no JSON could be extracted, return empty results
                return []

            except Exception as e:
                try:
                    container.kill()
                except:
                    pass
                raise e

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    
    async def list_projects(self) -> Dict[str, Any]:
        """List all loaded projects"""
        return {
            "success": True,
            "projects": [proj.dict() for proj in self.projects.values()]
        }
    
    async def project_info(self, project_id: str) -> Dict[str, Any]:
        """Get detailed project information"""
        if project_id not in self.projects:
            return {
                "success": False,
                "error": f"Project not found: {project_id}"
            }
        
        project = self.projects[project_id]
        project.last_accessed = time.time()
        
        return {
            "success": True,
            "project": project.dict()
        }
    
    async def list_queries(self, category: str = "all") -> Dict[str, Any]:
        """List pre-built queries"""
        queries = {
            "security": {
                "sql_injection": "cpg.call.name(\".*exec.*\").code",
                "xss_sinks": "cpg.call.name(\".*print.*\").argument",
                "hardcoded_secrets": "cpg.literal.code(\".*password.*|.*key.*|.*secret.*\")",
                "unsafe_deserialization": "cpg.call.name(\".*deserialize.*|.*pickle.*\")"
            },
            "quality": {
                "complex_methods": "cpg.method.filter(_.cyclomaticComplexity > 10)",
                "long_methods": "cpg.method.filter(_.numberOfLines > 50)",
                "duplicate_code": "cpg.method.filter(_.similarTo(_, 0.8))",
                "unused_variables": "cpg.identifier.filter(_.referencedIn.isEmpty)"
            },
            "metrics": {
                "total_methods": "cpg.method.size",
                "total_classes": "cpg.typeDecl.size",
                "total_files": "cpg.file.size",
                "average_complexity": "cpg.method.cyclomaticComplexity.mean"
            }
        }
        
        if category == "all":
            result_queries = queries
        elif category in queries:
            result_queries = {category: queries[category]}
        else:
            return {
                "success": False,
                "error": f"Unknown category: {category}"
            }
        
        return {
            "success": True,
            "queries": result_queries
        }
    
    async def cleanup_project(self, project_id: str) -> Dict[str, Any]:
        """Clean up project resources"""
        if project_id not in self.projects:
            return {
                "success": False,
                "error": f"Project not found: {project_id}"
            }
        
        project = self.projects[project_id]
        
        try:
            # Remove temporary files
            if project.source_type == "github" and os.path.exists(project.source_path):
                shutil.rmtree(project.source_path, ignore_errors=True)
            
            # Remove CPG files
            if project.cpg_path and os.path.exists(project.cpg_path):
                cpg_dir = Path(project.cpg_path).parent
                shutil.rmtree(cpg_dir, ignore_errors=True)
            
            # Remove from memory
            del self.projects[project_id]
            
            return {
                "success": True,
                "message": f"Project {project_id} cleaned up successfully"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Cleanup failed: {str(e)}"
            }
    
    async def _get_cached_cpg(self, cache_key: str) -> Optional[str]:
        """Get CPG from cache if available"""
        if not self.config.cache.enabled:
            return None
        
        cache_path = self.cache_dir / f"{cache_key}.bin"
        if cache_path.exists():
            # Check if cache is still valid
            age = time.time() - cache_path.stat().st_mtime
            if age < (self.config.cache.ttl_hours * 3600):
                return str(cache_path)
        
        return None
    
    async def _cache_cpg(self, cache_key: str, cpg_path: str):
        """Cache generated CPG"""
        if not self.config.cache.enabled:
            return
        
        cache_path = self.cache_dir / f"{cache_key}.bin"
        shutil.copy2(cpg_path, cache_path)
    
    async def run(self):
        """Run the MCP server"""
        await self.initialize_docker()
        
        # Import the MCP server runner
        from mcp.server.stdio import stdio_server
        
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                InitializationOptions(
                    server_name="joern-mcp-server",
                    server_version="1.0.0",
                    capabilities={
                        "tools": {},
                        "logging": {}
                    }
                )
            )

    def _normalize_results(self, raw):
        """Normalize raw JSON results into a list of dictionaries for QueryResult.

        Since we're now using Joern's native toJsonPretty directive, the results
        should already be properly serialized. We just need to handle the structure.
        """
        if isinstance(raw, list):
            # If it's a list of objects with properties, return as-is
            if all(isinstance(x, dict) for x in raw):
                return raw
            # If it's a list of primitives, wrap each as {"value": primitive}
            else:
                return [{"value": x} for x in raw]
        elif isinstance(raw, dict):
            return [raw]
        else:
            # Single primitive value
            return [{"value": raw}]