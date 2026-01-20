"""Session management for Terraform Cloud MCP

This module provides thread-safe in-memory storage for session-specific data,
such as the Terraform Cloud API token. The token is stored only for the
duration of the MCP server instance and is cleared on restart.
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SessionStorage:
    """Thread-safe storage for session data."""

    def __init__(self):
        """Initialize session storage with empty token."""
        self._token: Optional[str] = None
        self._lock = asyncio.Lock()

    async def set_token(self, token: str) -> None:
        """Store the Terraform Cloud API token for this session.

        Args:
            token: The Terraform Cloud API token to store
        """
        async with self._lock:
            self._token = token
            masked_token = f"{token[:8]}...{token[-4:]}" if token else "None"
            logger.info(f"Session token set (masked: {masked_token})")

    async def get_token(self) -> Optional[str]:
        """Retrieve the stored Terraform Cloud API token.

        Returns:
            The stored token, or None if no token has been set
        """
        async with self._lock:
            return self._token

    async def clear_token(self) -> None:
        """Clear the stored token from session."""
        async with self._lock:
            self._token = None
            logger.info("Session token cleared")


# Global session instance - one per MCP server instance
_session = SessionStorage()


async def set_session_token(token: str) -> None:
    """Set the Terraform Cloud API token for the current session.

    Args:
        token: The Terraform Cloud API token to store
    """
    await _session.set_token(token)


async def get_session_token() -> Optional[str]:
    """Get the Terraform Cloud API token from the current session.

    Returns:
        The stored token, or None if no token has been set
    """
    return await _session.get_token()


async def clear_session_token() -> None:
    """Clear the Terraform Cloud API token from the current session."""
    await _session.clear_token()
