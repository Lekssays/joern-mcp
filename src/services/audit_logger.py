"""
Structured Audit Logging Service (Phase 8 - API-04)

Emits standard structured JSON audit records for security and lifecycle mutations.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..api.correlation_middleware import get_current_correlation_id

logger = logging.getLogger("codebadger.audit")


class AuditLogger:
    """Service producing structured JSON audit logs for tracking security events and resource mutations."""

    def __init__(self, in_memory_buffer: bool = False):
        self.in_memory_buffer = in_memory_buffer
        self.events: List[Dict[str, Any]] = []

    def log_event(
        self,
        action: str,
        resource_id: Optional[str] = None,
        status_code: int = 200,
        actor: Optional[str] = None,
        tenant_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record an audit event formatted as JSON."""
        cid = correlation_id or get_current_correlation_id()
        now = datetime.now(timezone.utc).isoformat()

        event = {
            "timestamp": now,
            "correlation_id": cid,
            "actor": actor or "anonymous",
            "tenant_id": tenant_id or "default",
            "action": action,
            "resource_id": resource_id or "",
            "status_code": status_code,
            "metadata": metadata or {},
        }

        # Structured JSON log line
        logger.info(json.dumps(event))

        if self.in_memory_buffer:
            self.events.append(event)

        return event
