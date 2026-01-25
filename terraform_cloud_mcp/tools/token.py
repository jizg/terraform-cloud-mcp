"""Token management tools for Terraform Cloud MCP

This module provides tools for configuring Terraform Cloud API tokens
at runtime through the Chat UI, enabling session-based authentication
without requiring environment variable configuration.

Tokens are now stored using FastMCP's native session state functionality,
which provides automatic session isolation and support for distributed deployments.
"""

import logging
from typing import Dict, Any
from fastmcp import Context

from ..utils.session import set_session_token, get_session_token
from ..utils.decorators import handle_api_errors

logger = logging.getLogger(__name__)


@handle_api_errors
async def set_token(token: str, ctx: Context) -> Dict[str, Any]:
    """Set Terraform Cloud API token for the current session.

    This tool stores your Terraform Cloud API token in FastMCP's session state,
    which automatically isolates tokens per session and supports distributed
    deployments. The token persists for 1 day (default TTL) or until cleared.

    Usage:
        1. Call set_token with your Terraform Cloud API token
        2. Use any other Terraform Cloud tools (list_workspaces, etc.)
        3. The stored token will be used automatically

    Args:
        token: Your Terraform Cloud API token. You can generate one at:
               https://app.terraform.io/app/settings/tokens
        ctx: FastMCP Context (automatically injected)

    Returns:
        Dictionary with success status and message

    Examples:
        >>> await set_token("atlasv1.abc123...")
        {"status": "success", "message": "Token configured successfully"}
    """
    if not token or not token.strip():
        return {
            "error": "Token cannot be empty. Please provide a valid Terraform Cloud API token."
        }

    # Strip whitespace and store the token
    clean_token = token.strip()
    await set_session_token(clean_token, ctx)

    # Mask the token for logging
    masked_token = f"{clean_token[:8]}...{clean_token[-4:]}" if len(clean_token) > 12 else "***"
    logger.info(f"Token configured successfully via set_token (masked: {masked_token})")

    return {
        "status": "success",
        "message": "Token configured successfully. All subsequent tool calls will use this token."
    }


@handle_api_errors
async def get_current_token(ctx: Context) -> Dict[str, Any]:
    """Get the currently configured Terraform Cloud API token.

    Returns information about the token currently being used, including
    whether it's from the session state or from the environment variable.

    Args:
        ctx: FastMCP Context (automatically injected)

    Returns:
        Dictionary with token status information

    Examples:
        >>> await get_current_token()
        {"status": "configured", "source": "session", "has_token": true}
    """
    token = await get_session_token(ctx)

    if token:
        masked_token = f"{token[:8]}...{token[-4:]}" if len(token) > 12 else "***"
        return {
            "status": "configured",
            "source": "session",
            "has_token": True,
            "token_preview": masked_token
        }
    else:
        import os
        env_token = os.getenv("TFC_TOKEN")
        if env_token:
            return {
                "status": "configured",
                "source": "environment",
                "has_token": True,
                "note": "Using TFC_TOKEN environment variable"
            }
        else:
            return {
                "status": "not_configured",
                "source": None,
                "has_token": False,
                "message": "No token configured. Use set_token() to configure a token."
            }
