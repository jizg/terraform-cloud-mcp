"""Session management for Terraform Cloud MCP

This module provides thread-safe in-memory storage for session-specific data,
such as the Terraform Cloud API token. Supports multi-session architecture
with TTL-based expiration for streamable-http mode.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from fastmcp import Context
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def extract_session_id(request_context: Dict[str, Any]) -> str:
    """Extract session ID from HTTP request context.

    This function extracts the session ID from various sources in the HTTP
    request context, with the following priority:
    1. Mcp-Session-Id header (AWS Bedrock AgentCore)
    2. X-Session-ID header (custom/legacy)
    3. Authorization header (generates hash-based session ID)
    4. Default 'default' session

    Args:
        request_context: Dictionary containing request context, typically with
                        a 'headers' key containing HTTP headers

    Returns:
        The extracted or generated session ID
    """
    headers = request_context.get('headers', {})

    # Try AWS Bedrock AgentCore's Mcp-Session-Id header first (case-insensitive)
    session_id = headers.get('Mcp-Session-Id') or headers.get('mcp-session-id')
    if session_id:
        return session_id

    # Fallback to X-Session-ID header (case-insensitive)
    session_id = headers.get('X-Session-ID') or headers.get('x-session-id')
    if session_id:
        return session_id

    # Fallback to Authorization header
    auth_header = headers.get('Authorization') or headers.get('authorization')
    if auth_header and auth_header.startswith('Bearer '):
        # Generate a deterministic session ID from the token
        token = auth_header[7:]  # Remove 'Bearer ' prefix
        # Use SHA256 hash of token, take first 32 characters
        session_id = hashlib.sha256(token.encode()).hexdigest()[:32]
        logger.debug(f"Generated session ID from Authorization header")
        return session_id

    # Default session for backward compatibility
    logger.debug("Using 'default' session ID")
    return 'default'


@dataclass
class SessionData:
    """Per-session data structure."""
    token: str
    created_at: datetime
    ttl_seconds: int
    last_accessed: datetime = field(default_factory=datetime.now)


class MultiSessionStorage:
    """Thread-safe storage for multiple sessions with TTL support."""

    def __init__(self, default_ttl_seconds: int = 1800):
        """Initialize multi-session storage.

        Args:
            default_ttl_seconds: Default TTL for sessions in seconds (default: 30 minutes)
        """
        self._sessions: Dict[str, SessionData] = {}
        self._lock = asyncio.Lock()
        self._default_ttl = default_ttl_seconds

    async def set_token(self, session_id: str, token: str) -> None:
        """Store the Terraform Cloud API token for specific session.

        Args:
            session_id: Unique identifier for the session
            token: The Terraform Cloud API token to store
        """
        async with self._lock:
            self._sessions[session_id] = SessionData(
                token=token,
                created_at=datetime.now(),
                ttl_seconds=self._default_ttl
            )
            masked_token = f"{token[:8]}...{token[-4:]}" if token else "None"
            logger.info(f"Token set for session '{session_id}' (masked: {masked_token})")

    async def get_token(self, session_id: str) -> Optional[str]:
        """Retrieve the stored Terraform Cloud API token for session.

        Args:
            session_id: Unique identifier for the session

        Returns:
            The stored token, or None if session doesn't exist or is expired
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None

            if self._is_expired(session):
                logger.info(f"Session '{session_id}' expired, clearing")
                del self._sessions[session_id]
                return None

            # Update last accessed time
            session.last_accessed = datetime.now()
            return session.token

    async def clear_token(self, session_id: str) -> None:
        """Clear the stored token from session.

        Args:
            session_id: Unique identifier for the session
        """
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.info(f"Token cleared for session '{session_id}'")

    async def get_all_sessions(self) -> Dict[str, SessionData]:
        """Get all active sessions.

        Returns:
            Dictionary mapping session IDs to SessionData objects
        """
        async with self._lock:
            # Clean up expired sessions first
            expired_sessions = [
                sid for sid, session in self._sessions.items()
                if self._is_expired(session)
            ]
            for sid in expired_sessions:
                logger.info(f"Cleaning up expired session '{sid}'")
                del self._sessions[sid]

            return dict(self._sessions)

    def _is_expired(self, session: SessionData) -> bool:
        """Check if session has expired based on TTL.

        Args:
            session: The session data to check

        Returns:
            True if session has expired, False otherwise
        """
        elapsed = (datetime.now() - session.created_at).total_seconds()
        return elapsed > session.ttl_seconds


# Global session storage instance - one per MCP server instance
# Supports multiple concurrent sessions with TTL-based expiration
_session_storage = None


def get_session_storage() -> MultiSessionStorage:
    """Get the global session storage instance.

    Returns:
        The global MultiSessionStorage instance
    """
    global _session_storage
    if _session_storage is None:
        # Read TTL from environment variable
        import os
        ttl_seconds = int(os.getenv("SESSION_TTL_SECONDS", "1800"))
        _session_storage = MultiSessionStorage(default_ttl_seconds=ttl_seconds)
    return _session_storage


def get_current_session_id(ctx: Optional[Context] = None) -> str:
    """Get current session ID from context or use default.

    Based on FastMCP documentation:
    - ctx.session_id: MCP session ID (available after session establishment)
    - ctx.request_id: Current MCP request's unique ID (always available)
    - ctx.client_id: Client ID that initiated the request
    - ctx.transport: Transport protocol ("stdio", "sse", "streamable-http", or None)
    - ctx.session: ServerSession object

    In streamable-http mode with AgentCore Gateway:
    - ctx.session_id is None until session is fully established
    - ctx.request_id changes per request (NOT suitable for session isolation)
    - Need to find the actual transport/session ID (constant for entire session)

    Args:
        ctx: Optional FastMCP Context object

    Returns:
        The current session ID (from context attributes, or 'default' for stdio mode)

    Raises:
        ValueError: If running in streamable-http or sse mode but no unique ID is available
    """
    if not ctx:
        logger.debug("[Get Session ID] No context provided, using 'default' session ID")
        return 'default'

    # Try session_id first (available after session establishment)
    if hasattr(ctx, 'session_id') and ctx.session_id:
        logger.info(f"[Get Session ID] Retrieved from ctx.session_id: '{ctx.session_id}'")
        return ctx.session_id

    # Try to extract from session object or request_context
    # These might contain the transport/session ID
    if hasattr(ctx, 'session') and ctx.session:
        session = ctx.session
        # Check for session ID or transport ID attributes
        for attr_name in ['id', 'session_id', 'transport_id', '_id', '_session_id', '_transport_id']:
            if hasattr(session, attr_name):
                value = getattr(session, attr_name)
                if value:
                    logger.info(f"[Get Session ID] Retrieved from ctx.session.{attr_name}: '{value}'")
                    return str(value)

    if hasattr(ctx, 'request_context') and ctx.request_context:
        request_ctx = ctx.request_context
        # Check for session ID or transport ID in request context
        for attr_name in ['session_id', 'transport_id', 'sessionId', 'transportId']:
            if hasattr(request_ctx, attr_name):
                value = getattr(request_ctx, attr_name)
                if value:
                    logger.info(f"[Get Session ID] Retrieved from ctx.request_context.{attr_name}: '{value}'")
                    return str(value)

    # Try to extract from request headers (AgentCore Gateway sends transport ID here)
    if hasattr(ctx, 'get_http_request'):
        try:
            request = ctx.get_http_request()
            if hasattr(request, 'headers'):
                headers = dict(request.headers)
                # Try various possible header names for transport/session ID
                for header_name in ['Mcp-Session-Id', 'mcp-session-id', 'X-Session-ID',
                                  'x-session-id', 'X-Transport-Id', 'x-transport-id',
                                  'X-MCP-Session-Id', 'x-mcp-session-id']:
                    if header_name in headers:
                        session_id = headers[header_name]
                        logger.info(f"[Get Session ID] Extracted from {header_name} header: '{session_id}'")
                        return session_id
        except Exception as e:
            logger.warning(f"[Get Session ID] Failed to get HTTP request: {e}")

    # Check if we're in HTTP transport mode where session isolation is required
    if hasattr(ctx, 'transport'):
        transport = ctx.transport
        if transport in ('streamable-http', 'sse'):
            # If still no session_id, raise error
            error_msg = (
                f"Missing required session identifier in {transport} mode. "
                f"Could not find transport/session ID in context. "
                f"Note: request_id changes per request and should not be used for session isolation."
            )
            logger.error(f"[Get Session ID] {error_msg}")
            raise ValueError(error_msg)

    # Fall back to request_id (only for stdio mode, not suitable for HTTP transports)
    if hasattr(ctx, 'request_id') and ctx.request_id:
        logger.info(f"[Get Session ID] Retrieved from ctx.request_id (WARNING: changes per request): '{ctx.request_id}'")
        return str(ctx.request_id)

    # Fall back to client_id
    if hasattr(ctx, 'client_id') and ctx.client_id:
        logger.info(f"[Get Session ID] Retrieved from ctx.client_id: '{ctx.client_id}'")
        return str(ctx.client_id)

    # Default to 'default' for stdio mode
    logger.debug("[Get Session ID] Using 'default' session ID")
    return 'default'


def determine_session_id(
    session_id: Optional[str] = None,
    ctx: Optional[Context] = None,
    log_prefix: str = ""
) -> Optional[str]:
    """Determine session_id from context first, then use provided parameter.

    This function ensures session isolation by prioritizing context-based
    session ID extraction over explicitly provided session_id parameter.

    Priority order:
    1. Session ID from context (if ctx is provided)
    2. Explicitly provided session_id parameter
    3. Default session (for stdio mode only - raises error for HTTP transports)

    Args:
        session_id: Optional explicit session ID parameter
        ctx: Optional FastMCP Context object
        log_prefix: Prefix for log messages (e.g., "[API Request]" or "[Get Active Token]")

    Returns:
        The determined session ID, or None if no session ID is available
        (callers should then use default session determination)

    Raises:
        ValueError: If running in streamable-http or sse mode but no session_id is available
    """
    # Try to get session_id from context first
    determined_session_id = None
    if ctx:
        determined_session_id = get_current_session_id(ctx)
        logger.info(f"{log_prefix} Determined session_id from context: '{determined_session_id}'")
        # If get_current_session_id returns a non-default ID, use it
        if determined_session_id != 'default':
            return determined_session_id

    # Fall back to provided parameter
    if session_id:
        determined_session_id = session_id
        logger.info(f"{log_prefix} Using provided session_id parameter: '{determined_session_id}'")
        return determined_session_id

    # If still no session_id, check if we need to raise an error
    if ctx and hasattr(ctx, 'transport'):
        transport = ctx.transport
        if transport in ('streamable-http', 'sse'):
            error_msg = (
                f"Missing required session_id in {transport} mode. "
                f"Session isolation is required when running behind AgentCore Gateway."
            )
            logger.error(f"{log_prefix} {error_msg}")
            raise ValueError(error_msg)

    logger.debug(f"{log_prefix} No session_id available, will use default session")
    return None


async def set_session_token(token: str, session_id: Optional[str] = None, ctx: Optional[Context] = None) -> None:
    """Set the Terraform Cloud API token for the specified session.

    Args:
        token: The Terraform Cloud API token to store
        session_id: Session identifier (uses ctx.session_id if not provided)
        ctx: Optional FastMCP Context object
    """
    if session_id is None:
        session_id = get_current_session_id(ctx)

    storage = get_session_storage()
    await storage.set_token(session_id, token)


async def get_session_token(session_id: Optional[str] = None, ctx: Optional[Context] = None) -> Optional[str]:
    """Get the Terraform Cloud API token from the specified session.

    Args:
        session_id: Session identifier (uses ctx.session_id if not provided)
        ctx: Optional FastMCP Context object

    Returns:
        The stored token, or None if no token has been set or session is expired
    """
    if session_id is None:
        session_id = get_current_session_id(ctx)

    storage = get_session_storage()
    return await storage.get_token(session_id)


async def clear_session_token(session_id: Optional[str] = None, ctx: Optional[Context] = None) -> None:
    """Clear the Terraform Cloud API token from the specified session.

    Args:
        session_id: Session identifier (uses ctx.session_id if not provided)
        ctx: Optional FastMCP Context object
    """
    if session_id is None:
        session_id = get_current_session_id(ctx)

    storage = get_session_storage()
    await storage.clear_token(session_id)


async def get_all_sessions() -> Dict[str, SessionData]:
    """Get all active sessions.

    Returns:
        Dictionary mapping session IDs to SessionData objects
    """
    storage = get_session_storage()
    return await storage.get_all_sessions()


async def delete_session_token(session_id: str) -> None:
    """Delete a specific session by ID.

    Args:
        session_id: Session identifier to delete
    """
    storage = get_session_storage()
    await storage.clear_token(session_id)
