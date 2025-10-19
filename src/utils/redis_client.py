"""
Redis client wrapper for session management
"""

import json
import logging
from typing import Any, Dict, List, Optional

import redis.asyncio as redis

from ..models import RedisConfig, Session

logger = logging.getLogger(__name__)


class RedisClient:
    """Async Redis client for session storage"""

    def __init__(self, config: RedisConfig):
        self.config = config
        self.client: Optional[redis.Redis] = None

    async def connect(self):
        """Establish Redis connection"""
        try:
            self.client = redis.from_url(
                f"redis://{self.config.host}:{self.config.port}/{self.config.db}",
                password=self.config.password,
                decode_responses=self.config.decode_responses,
            )
            await self.client.ping()
            logger.info("Connected to Redis successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def close(self):
        """Close Redis connection"""
        if self.client:
            await self.client.close()
            logger.info("Closed Redis connection")

    async def save_session(self, session: Session, ttl: int = 3600):
        """Save session to Redis"""
        key = f"session:{session.id}"
        data = json.dumps(session.to_dict())
        await self.client.set(key, data, ex=ttl)
        await self.client.sadd("sessions:active", session.id)
        logger.debug(f"Saved session {session.id}")

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Retrieve session from Redis"""
        key = f"session:{session_id}"
        data = await self.client.get(key)
        if data:
            session_dict = json.loads(data)
            return Session.from_dict(session_dict)
        return None

    async def update_session(
        self, session_id: str, updates: Dict[str, Any], ttl: int = 3600
    ):
        """Update session fields"""
        session = await self.get_session(session_id)
        if session:
            for key, value in updates.items():
                setattr(session, key, value)
            await self.save_session(session, ttl)

    async def delete_session(self, session_id: str):
        """Delete session from Redis"""
        key = f"session:{session_id}"
        await self.client.delete(key)
        await self.client.srem("sessions:active", session_id)
        logger.debug(f"Deleted session {session_id}")

    async def list_sessions(self) -> List[str]:
        """List all active session IDs"""
        return list(await self.client.smembers("sessions:active"))

    async def touch_session(self, session_id: str, ttl: int = 3600):
        """Refresh session TTL"""
        key = f"session:{session_id}"
        await self.client.expire(key, ttl)

    async def set_container_mapping(
        self, container_id: str, session_id: str, ttl: int = 3600
    ):
        """Map container ID to session ID"""
        key = f"container:{container_id}"
        await self.client.set(key, session_id, ex=ttl)

    async def get_session_by_container(self, container_id: str) -> Optional[str]:
        """Get session ID by container ID"""
        key = f"container:{container_id}"
        return await self.client.get(key)

    async def delete_container_mapping(self, container_id: str):
        """Delete container mapping"""
        key = f"container:{container_id}"
        await self.client.delete(key)

    async def cache_query_result(
        self, session_id: str, query_hash: str, result: Dict[str, Any], ttl: int = 300
    ):
        """Cache query result"""
        key = f"query:{session_id}:{query_hash}"
        data = json.dumps(result)
        await self.client.set(key, data, ex=ttl)

    async def get_cached_query(
        self, session_id: str, query_hash: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached query result"""
        key = f"query:{session_id}:{query_hash}"
        data = await self.client.get(key)
        if data:
            return json.loads(data)
        return None
