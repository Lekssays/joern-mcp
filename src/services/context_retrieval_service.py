import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from .query_executor import QueryExecutor
from .project_version_service import ProjectVersionService

logger = logging.getLogger(__name__)

class ContextRetrievalService:
    def __init__(self, query_executor: QueryExecutor, version_service: ProjectVersionService):
        self.query_executor = query_executor
        self.version_service = version_service
        
    def get_context(self, version_id: str, query: str, owner_scope: str = "default", max_items: int = 10, max_bytes: int = 50000) -> Dict[str, Any]:
        version = self.version_service.get_version(version_id, owner_scope)
        if not version:
            raise ValueError(f"Version {version_id} not found or unauthorized")
            
        if version.build_status != "ready":
            raise ValueError(f"Version {version_id} is not ready (status: {version.build_status})")
            
        codebase_hash = version.id
        
        # 1. Exact symbol resolution for methods
        method_query = f"""
        cpg.method.name("(?i).*{query}.*").map(m => Map(
            "filename" -> m.filename,
            "lineNumber" -> m.lineNumber,
            "lineNumberEnd" -> m.lineNumberEnd,
            "code" -> m.code,
            "name" -> m.name,
            "signature" -> m.signature,
            "type" -> "method"
        )).l
        """
        
        method_res = self.query_executor.execute_query(
            codebase_hash=codebase_hash,
            cpg_path="", # cpg_path is resolved inside QueryExecutor via codebase_hash
            query=method_query
        )
        
        # 2. Type resolution
        type_query = f"""
        cpg.typeDecl.name("(?i).*{query}.*").map(t => Map(
            "filename" -> t.filename,
            "lineNumber" -> t.lineNumber,
            "lineNumberEnd" -> t.lineNumberEnd,
            "code" -> t.code,
            "name" -> t.name,
            "type" -> "typeDecl"
        )).l
        """
        
        type_res = self.query_executor.execute_query(
            codebase_hash=codebase_hash,
            cpg_path="",
            query=type_query
        )
        
        items = []
        seen = set()
        total_bytes = 0
        truncated = False
        
        for res in [method_res, type_res]:
            if res.success and res.data:
                for item in res.data:
                    # Deterministic deduplication based on location
                    file = item.get("filename")
                    line = item.get("lineNumber")
                    key = f"{file}:{line}"
                    if key in seen:
                        continue
                    seen.add(key)
                    
                    code_len = len(item.get("code", ""))
                    if total_bytes + code_len > max_bytes:
                        truncated = True
                        break
                        
                    if len(items) >= max_items:
                        truncated = True
                        break
                        
                    enriched_item = dict(item)
                    enriched_item["version_digest"] = version.content_digest
                    enriched_item["selection_reason"] = f"Symbol match for '{query}'"
                    
                    items.append(enriched_item)
                    total_bytes += code_len
                    
        return {
            "query": query,
            "version_id": version_id,
            "items": items,
            "budget": {
                "max_items": max_items,
                "max_bytes": max_bytes,
                "used_items": len(items),
                "used_bytes": total_bytes
            },
            "truncated": truncated
        }
