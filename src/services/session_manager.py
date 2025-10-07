"""
Session manager for CPG session lifecycle management
"""
import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

from ..models import Session, SessionStatus, SessionConfig
from ..utils.redis_client import RedisClient
from ..exceptions import SessionNotFoundError, ResourceLimitError

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages CPG session lifecycle and metadata"""

    def __init__(self, redis_client: RedisClient, config: SessionConfig):
        self.redis = redis_client
        self.config = config
        self.docker_cleanup_callback = None  # Will be set by the service that has Docker access

    def set_docker_cleanup_callback(self, callback):
        """Set the callback function for Docker container cleanup"""
        self.docker_cleanup_callback = callback

    async def create_session(
        self,
        source_type: str,
        source_path: str,
        language: str,
        options: Dict[str, Any]
    ) -> Session:
        """Create a new CPG session"""
        try:
            # Check concurrent session limit and auto-cleanup if needed
            active_sessions = await self.redis.list_sessions()
            if len(active_sessions) >= self.config.max_concurrent:
                logger.info(f"Session limit reached ({len(active_sessions)}/{self.config.max_concurrent}), cleaning up oldest sessions")
                await self._cleanup_oldest_sessions(10)  # Clean up 10 oldest sessions
            
            # Create session
            session = Session(
                id=str(uuid.uuid4()),
                source_type=source_type,
                source_path=source_path,
                language=language,
                status=SessionStatus.INITIALIZING.value,
                metadata=options
            )
            
            # Save to Redis
            await self.redis.save_session(session, self.config.ttl)
            
            logger.info(f"Created session {session.id}")
            return session
            
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            raise

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID"""
        try:
            session = await self.redis.get_session(session_id)
            if not session:
                return None
            return session
        except Exception as e:
            logger.error(f"Failed to get session {session_id}: {e}")
            return None

    async def update_session(
        self,
        session_id: str,
        **updates
    ):
        """Update session fields"""
        try:
            # Update last_accessed
            updates['last_accessed'] = datetime.utcnow()
            await self.redis.update_session(session_id, updates, self.config.ttl)
            logger.debug(f"Updated session {session_id}")
        except Exception as e:
            logger.error(f"Failed to update session {session_id}: {e}")
            raise

    async def update_status(
        self,
        session_id: str,
        status: str,
        error_message: Optional[str] = None
    ):
        """Update session status"""
        updates = {
            'status': status,
            'last_accessed': datetime.utcnow()
        }
        
        if error_message:
            updates['error_message'] = error_message
        
        await self.redis.update_session(session_id, updates, self.config.ttl)
        logger.info(f"Session {session_id} status: {status}")

    async def list_sessions(self, filters: Optional[Dict[str, str]] = None) -> List[Session]:
        """List all sessions with optional filtering"""
        try:
            session_ids = await self.redis.list_sessions()
            sessions = []
            
            for session_id in session_ids:
                session = await self.get_session(session_id)
                if session:
                    # Apply filters
                    if filters:
                        match = True
                        for key, value in filters.items():
                            if getattr(session, key, None) != value:
                                match = False
                                break
                        if match:
                            sessions.append(session)
                    else:
                        sessions.append(session)
            
            return sessions
            
        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
            return []

    async def touch_session(self, session_id: str):
        """Refresh session TTL"""
        try:
            await self.redis.touch_session(session_id, self.config.ttl)
            await self.update_session(session_id, last_accessed=datetime.utcnow())
        except Exception as e:
            logger.error(f"Failed to touch session {session_id}: {e}")

    async def cleanup_session(self, session_id: str):
        """Clean up session and associated resources"""
        try:
            session = await self.get_session(session_id)
            if not session:
                raise SessionNotFoundError(f"Session {session_id} not found")
            
            # Delete container mapping if exists
            if session.container_id:
                await self.redis.delete_container_mapping(session.container_id)
            
            # Delete session
            await self.redis.delete_session(session_id)
            
            logger.info(f"Cleaned up session {session_id}")
            
        except SessionNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Failed to cleanup session {session_id}: {e}")
            raise

    async def _cleanup_oldest_sessions(self, count: int = 10):
        """Clean up the oldest sessions to make room for new ones"""
        try:
            # Get all sessions sorted by creation time (oldest first)
            sessions = await self.list_sessions()
            if not sessions:
                return
                
            # Sort by created_at timestamp (oldest first)
            sorted_sessions = sorted(sessions, key=lambda s: s.created_at)
            
            # Clean up the oldest 'count' sessions
            sessions_to_cleanup = sorted_sessions[:count]
            
            logger.info(f"Auto-cleaning up {len(sessions_to_cleanup)} oldest sessions")
            
            for session in sessions_to_cleanup:
                try:
                    # Stop Docker container if it exists and we have a cleanup callback
                    if session.container_id and self.docker_cleanup_callback:
                        await self.docker_cleanup_callback(session.container_id)
                    
                    # Clean up session data
                    await self.cleanup_session(session.id)
                    logger.info(f"Auto-cleaned up old session {session.id}")
                except Exception as e:
                    logger.error(f"Failed to auto-cleanup session {session.id}: {e}")
                    
        except Exception as e:
            logger.error(f"Failed to cleanup oldest sessions: {e}")

    async def cleanup_idle_sessions(self):
        """Clean up sessions that have been idle too long"""
        try:
            sessions = await self.list_sessions()
            now = datetime.utcnow()
            
            for session in sessions:
                idle_time = (now - session.last_accessed).total_seconds()
                
                if idle_time > self.config.idle_timeout:
                    logger.info(
                        f"Cleaning up idle session {session.id} "
                        f"(idle for {idle_time:.0f} seconds)"
                    )
                    await self.cleanup_session(session.id)
                    
        except Exception as e:
            logger.error(f"Failed to cleanup idle sessions: {e}")
