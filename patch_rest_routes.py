import re

with open('src/api/rest_routes.py', 'r') as f:
    content = f.read()

context_route = """
async def get_version_context(request: Request) -> JSONResponse:
    services = request.app.state.services
    context_service = services.get("context_service")
    if not context_service:
        return JSONResponse({"error": "Context service not configured"}, status_code=503)
        
    version_id = request.path_params.get("id")
    query = request.query_params.get("query")
    if not query:
        return JSONResponse({"error": "Missing 'query' parameter"}, status_code=400)
        
    try:
        max_items = int(request.query_params.get("max_items", "10"))
    except ValueError:
        return JSONResponse({"error": "Invalid 'max_items'"}, status_code=400)
        
    try:
        max_bytes = int(request.query_params.get("max_bytes", "50000"))
    except ValueError:
        return JSONResponse({"error": "Invalid 'max_bytes'"}, status_code=400)

    try:
        # Secure: raw CPGQL is not exposed, we only pass a generic string query 
        result = context_service.get_context(version_id, query, max_items=max_items, max_bytes=max_bytes)
        return JSONResponse(result)
    except ValueError as e:
        if "not found" in str(e) or "unauthorized" in str(e):
            return JSONResponse({"error": str(e)}, status_code=404)
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
"""

if "def get_version_context" not in content:
    content = content.replace("def register_rest_routes", context_route + "\ndef register_rest_routes")
    
if "Route(\"/versions/{id}/context\"" not in content:
    content = content.replace("Route(\"/versions/{id}/cancel\", cancel_version, methods=[\"POST\"]),",
                              "Route(\"/versions/{id}/cancel\", cancel_version, methods=[\"POST\"]),\n        Route(\"/versions/{id}/context\", get_version_context, methods=[\"GET\"]),")

with open('src/api/rest_routes.py', 'w') as f:
    f.write(content)
