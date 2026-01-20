"""Token management tools for Terraform Cloud MCP

This module provides tools for configuring Terraform Cloud API tokens
at runtime through the Chat UI, enabling session-based authentication
without requiring environment variable configuration.
"""

import logging
from typing import Dict, Any

from ..utils.session import set_session_token, get_session_token
from ..utils.decorators import handle_api_errors

logger = logging.getLogger(__name__)


@handle_api_errors
async def set_token(token: str) -> Dict[str, Any]:
    """Set Terraform Cloud API token for the current session.

    This tool allows you to configure your Terraform Cloud API token
    at runtime through the Chat UI. Once set, all subsequent tool calls
    will use this token for authentication. The token is stored only
    in memory for the duration of the session and is cleared when the
    MCP server restarts.

    Usage:
        1. Call set_token with your Terraform Cloud API token
        2. Use any other Terraform Cloud tools (list_workspaces, etc.)
        3. The stored token will be used automatically

    Args:
        token: Your Terraform Cloud API token. You can generate one at:
               https://app.terraform.io/app/settings/tokens

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
    await set_session_token(clean_token)

    # Mask the token for logging
    masked_token = f"{clean_token[:8]}...{clean_token[-4:]}" if len(clean_token) > 12 else "***"
    logger.info(f"Token configured successfully via set_token (masked: {masked_token})")

    return {
        "status": "success",
        "message": "Token configured successfully. All subsequent tool calls will use this token."
    }


@handle_api_errors
async def get_current_token() -> Dict[str, Any]:
    """Get the currently configured Terraform Cloud API token.

    Returns information about the token currently being used, including
    whether it's from the session or from the environment variable.

    Returns:
        Dictionary with token status information

    Examples:
        >>> await get_current_token()
        {"status": "configured", "source": "session", "has_token": true}
    """
    token = await get_session_token()

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
