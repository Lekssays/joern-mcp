import pytest
from starlette.testclient import TestClient
from starlette.applications import Starlette
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
from src.api.rest_routes import register_rest_routes
from src.services.context_retrieval_service import ContextRetrievalService
from unittest.mock import MagicMock

def test_context_retrieval_api():
    app = Starlette()
    
    # Mock services
    services = {
        "version_service": MagicMock(),
        "context_service": MagicMock()
    }
    app.state.services = services
    
    app.state.services["context_service"].get_context.return_value = {
        "items": [], "budget": {}, "truncated": False
    }
    
    register_rest_routes(app, services)
    client = TestClient(app)
    
    # Public endpoint exposes validated parameters, not raw CPGQL
    response = client.get("/versions/v1/context?query=myMethod&max_items=10")
    
    assert response.status_code == 200
    app.state.services["context_service"].get_context.assert_called_with(
        "v1", "myMethod", max_items=10, max_bytes=50000
    )
