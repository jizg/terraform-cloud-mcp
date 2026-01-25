"""Environment variable management for Terraform Cloud MCP"""

import os
import logging
from fastmcp import Context
from typing import Optional

logger = logging.getLogger(__name__)


def get_tfc_token() -> Optional[str]:
    """Get Terraform Cloud API token from environment."""
    return os.getenv("TFC_TOKEN")


async def get_active_token(ctx: Optional[Context] = None) -> str:
    """Get active Terraform Cloud API token for the current session.

    Checks session state for token (stored via set_token tool).
    Falls back to TFC_TOKEN environment variable if no session token.

    Args:
        ctx: FastMCP Context object

    Returns:
        The active token from session or environment.

    Raises:
        ValueError: If no token is configured
    """
    from .session import get_session_token, get_session_id_safe

    if ctx:
        session_id = get_session_id_safe(ctx)
        logger.debug(f"[Get Active Token] Checking token for session: '{session_id}'")
        
        session_token = await get_session_token(ctx)
        
        if session_token:
            logger.debug(f"[Get Active Token] Found session token for '{session_id}'")
            return session_token
    
    # Fall back to environment variable
    env_token = get_tfc_token()
    if env_token:
        logger.debug("[Get Active Token] Using TFC_TOKEN environment variable")
        return env_token

    logger.error("[Get Active Token] No token found in session or environment")
    raise ValueError(
        "Terraform Cloud API token is required. "
        "Use set_token tool to configure your token, or set TFC_TOKEN environment variable."
    )


def get_tfc_address() -> str:
    """Get Terraform Cloud/Enterprise address from environment, with default of app.terraform.io."""
    return os.getenv("TFC_ADDRESS", "https://app.terraform.io")


def should_enable_delete_tools() -> bool:
    """Check if delete tools should be enabled."""
    env_value = os.getenv("ENABLE_DELETE_TOOLS", "false").lower().strip()
    return env_value in ("true", "1", "yes", "on")


def should_return_raw_response() -> bool:
    """Check if raw API responses should be returned instead of filtered responses."""
    env_value = os.getenv("ENABLE_RAW_RESPONSE", "false").lower().strip()
    return env_value in ("true", "1", "yes", "on")


def should_enable_read_only_tools() -> bool:
    """Check if only read-only tools should be enabled."""
    env_value = os.getenv("READ_ONLY_TOOLS", "false").lower().strip()
    return env_value in ("true", "1", "yes", "on")
