"""Integration tests for the Joern MCP Server."""

import pytest
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.server import JoernMCPServer
from src.models import ProjectLoadError, CPGGenerationError


class TestJoernMCPServer:
    """Test cases for JoernMCPServer"""
    
    def test_server_initialization(self, test_config):
        """Test server initialization with config"""
        server = JoernMCPServer(test_config)
        assert server.config == test_config
        assert server.projects == {}
        assert server.logger is not None
        assert server.cache_dir.exists()
    
    def test_generate_project_id(self, server):
        """Test project ID generation"""
        source1 = "https://github.com/user/repo1"
        source2 = "https://github.com/user/repo2"
        
        id1 = server._generate_project_id(source1)
        id2 = server._generate_project_id(source2)
        
        assert len(id1) == 8
        assert len(id2) == 8
        assert id1 != id2
        
        # Same source should produce same ID
        id1_repeat = server._generate_project_id(source1)
        assert id1 == id1_repeat
    
    @pytest.mark.asyncio
    async def test_load_local_project(self, server, sample_c_project):
        """Test loading a local project"""
        result = await server.load_project(str(sample_c_project))
        
        assert result["success"] is True
        assert "project_id" in result
        assert "project_info" in result
        
        project_id = result["project_id"]
        assert project_id in server.projects
        
        project = server.projects[project_id]
        assert project.source_type == "local"
        assert "c" in project.languages
        assert project.size_loc > 0
    
    @pytest.mark.asyncio
    async def test_load_nonexistent_local_project(self, server):
        """Test loading a non-existent local project"""
        with pytest.raises(ProjectLoadError):
            await server.load_project("/nonexistent/path")
    
    @pytest.mark.asyncio
    async def test_list_projects_empty(self, server):
        """Test listing projects when none are loaded"""
        result = await server.list_projects()
        
        assert result["success"] is True
        assert result["projects"] == []
    
    @pytest.mark.asyncio
    async def test_list_projects_with_projects(self, server, sample_c_project):
        """Test listing projects when some are loaded"""
        # Load a project first
        await server.load_project(str(sample_c_project))
        
        result = await server.list_projects()
        
        assert result["success"] is True
        assert len(result["projects"]) == 1
        assert result["projects"][0]["source_type"] == "local"
    
    @pytest.mark.asyncio
    async def test_project_info_existing(self, server, sample_c_project):
        """Test getting info for existing project"""
        # Load a project first
        load_result = await server.load_project(str(sample_c_project))
        project_id = load_result["project_id"]
        
        result = await server.project_info(project_id)
        
        assert result["success"] is True
        assert result["project"]["id"] == project_id
        assert result["project"]["source_type"] == "local"
    
    @pytest.mark.asyncio
    async def test_project_info_nonexistent(self, server):
        """Test getting info for non-existent project"""
        result = await server.project_info("nonexistent")
        
        assert result["success"] is False
        assert "error" in result
    
    @pytest.mark.asyncio
    async def test_list_queries_all(self, server):
        """Test listing all available queries"""
        result = await server.list_queries("all")
        
        assert result["success"] is True
        assert "queries" in result
        assert "security" in result["queries"]
        assert "quality" in result["queries"]
        assert "metrics" in result["queries"]
    
    @pytest.mark.asyncio
    async def test_list_queries_category(self, server):
        """Test listing queries by category"""
        result = await server.list_queries("security")
        
        assert result["success"] is True
        assert "queries" in result
        assert "security" in result["queries"]
        assert "quality" not in result["queries"]
    
    @pytest.mark.asyncio
    async def test_list_queries_invalid_category(self, server):
        """Test listing queries with invalid category"""
        result = await server.list_queries("invalid")
        
        assert result["success"] is False
        assert "error" in result
    
    @pytest.mark.asyncio
    async def test_cleanup_project_existing(self, server, sample_c_project):
        """Test cleaning up an existing project"""
        # Load a project first
        load_result = await server.load_project(str(sample_c_project))
        project_id = load_result["project_id"]
        
        # Verify project exists
        assert project_id in server.projects
        
        # Cleanup
        result = await server.cleanup_project(project_id)
        
        assert result["success"] is True
        assert project_id not in server.projects
    
    @pytest.mark.asyncio
    async def test_cleanup_project_nonexistent(self, server):
        """Test cleaning up a non-existent project"""
        result = await server.cleanup_project("nonexistent")
        
        assert result["success"] is False
        assert "error" in result
    
    def test_normalize_results_list_of_dicts(self, server):
        """Test normalizing list of dictionaries"""
        raw = [{"name": "func1", "id": 1}, {"name": "func2", "id": 2}]
        result = server._normalize_results(raw)
        
        assert result == raw
    
    def test_normalize_results_list_of_primitives(self, server):
        """Test normalizing list of primitives"""
        raw = ["func1", "func2", "func3"]
        result = server._normalize_results(raw)
        
        expected = [{"value": "func1"}, {"value": "func2"}, {"value": "func3"}]
        assert result == expected
    
    def test_normalize_results_single_dict(self, server):
        """Test normalizing single dictionary"""
        raw = {"name": "func1", "id": 1}
        result = server._normalize_results(raw)
        
        assert result == [raw]
    
    def test_normalize_results_single_primitive(self, server):
        """Test normalizing single primitive value"""
        raw = "single_value"
        result = server._normalize_results(raw)
        
        assert result == [{"value": "single_value"}]


class TestDockerIntegration:
    """Test cases that require Docker (should be marked for optional execution)"""
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_docker_initialization(self, server):
        """Test Docker client initialization"""
        # This test requires Docker to be running
        await server.initialize_docker()
        assert server.docker_client is not None
    
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_cpg_generation_c_project(self, server, sample_c_project):
        """Test CPG generation for C project"""
        # Load project first
        load_result = await server.load_project(str(sample_c_project))
        project_id = load_result["project_id"]
        
        # Generate CPG
        result = await server.generate_cpg(project_id)
        
        assert result["success"] is True
        assert result["project_id"] == project_id
        assert "cpg_path" in result
        
        # Verify project state
        project = server.projects[project_id]
        assert project.cpg_generated is True
        assert project.cpg_path is not None