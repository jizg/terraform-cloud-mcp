"""Session management tools for Terraform Cloud MCP

This module provides tools for managing sessions in FastMCP, enabling users
to view session information, manage context, and clear session data.

Using FastMCP's native session state (3.0.0+), sessions are automatically
isolated and support distributed storage backends.
"""

import logging
from typing import Dict, Any, Optional

from fastmcp import Context
from ..utils.session import (
    get_session_info,
    clear_session_token,
    clear_session_context,
    get_session_context,
    set_session_context,
    get_session_id_safe,
    get_client_context,
    get_client_preferences,
)
from ..utils.decorators import handle_api_errors

logger = logging.getLogger(__name__)


@handle_api_errors
async def get_session_status(ctx: Context) -> Dict[str, Any]:
    """Get comprehensive information about the current session.

    This tool returns detailed information about the current session,
    including session ID, transport type, token status, current context
    (organization/workspace/project), user preferences, and client context
    (region, agent name, timestamp, and user preferences from AWS Bedrock AgentCore).

    Args:
        ctx: FastMCP Context (automatically injected)

    Returns:
        Dictionary with complete session information

    Examples:
        >>> await get_session_status(ctx)
        {
            "session_id": "session-abc123",
            "transport": "streamable-http",
            "has_token": true,
            "context": {
                "organization": "my-org",
                "workspace": "my-workspace",
                "project": null
            },
            "preferences": {},
            "client_context": {
                "region": "us-west-2",
                "agent_name": "TFC-Agent",
                "timestamp": 1705000000.0,
                "preferences": {}
            }
        }
    """
    return await get_session_info(ctx)


@handle_api_errors
async def clear_session(ctx: Context, clear_token: bool = True, clear_context: bool = True) -> Dict[str, Any]:
    """Clear session data (token and/or context).

    This tool removes stored data from the current session. You can choose
    to clear the token, context (organization/workspace/project), or both.

    Args:
        ctx: FastMCP Context (automatically injected)
        clear_token: Whether to clear the stored token (default: True)
        clear_context: Whether to clear session context (default: True)

    Returns:
        Dictionary with success status and message

    Examples:
        >>> await clear_session(ctx)
        {"status": "success", "message": "Session cleared (token + context)"}

        >>> await clear_session(ctx, clear_token=True, clear_context=False)
        {"status": "success", "message": "Session token cleared"}
    """
    session_id = get_session_id_safe(ctx)
    cleared_items = []
    
    if clear_token:
        await clear_session_token(ctx)
        cleared_items.append("token")
    
    if clear_context:
        await clear_session_context(ctx)
        cleared_items.append("context")
    
    if not cleared_items:
        return {
            "status": "info",
            "message": "No items to clear (both flags set to False)"
        }
    
    items_str = " + ".join(cleared_items)
    logger.info(f"Session '{session_id}' cleared: {items_str}")

    return {
        "status": "success",
        "message": f"Session cleared ({items_str}). Use set_token to configure a new token."
    }


@handle_api_errors
async def set_context(
    ctx: Context,
    organization: Optional[str] = None,
    workspace: Optional[str] = None,
    project: Optional[str] = None
) -> Dict[str, Any]:
    """Set current organization/workspace/project context.

    This tool stores context values in the session, allowing you to set
    a default organization, workspace, or project that can be used by
    other tools without explicitly passing these parameters every time.

    Args:
        ctx: FastMCP Context (automatically injected)
        organization: Organization name or ID to set as current
        workspace: Workspace name or ID to set as current
        project: Project ID to set as current

    Returns:
        Dictionary with success status and updated context

    Examples:
        >>> await set_context(ctx, organization="my-org", workspace="my-workspace")
        {
            "status": "success",
            "message": "Context updated",
            "context": {
                "organization": "my-org",
                "workspace": "my-workspace",
                "project": null
            }
        }
    """
    if not any([organization, workspace, project]):
        return {
            "error": "At least one context value (organization, workspace, or project) must be provided."
        }
    
    await set_session_context(ctx, organization=organization, workspace=workspace, project=project)
    
    # Get the updated context
    updated_context = await get_session_context(ctx)
    
    set_items = []
    if organization:
        set_items.append(f"organization={organization}")
    if workspace:
        set_items.append(f"workspace={workspace}")
    if project:
        set_items.append(f"project={project}")
    
    logger.info(f"Context updated: {', '.join(set_items)}")

    return {
        "status": "success",
        "message": "Context updated",
        "context": updated_context
    }


@handle_api_errors
async def get_context(ctx: Context) -> Dict[str, Any]:
    """Get the current organization/workspace/project context.

    Returns the currently set context values for the session.

    Args:
        ctx: FastMCP Context (automatically injected)

    Returns:
        Dictionary with current context values

    Examples:
        >>> await get_context(ctx)
        {
            "organization": "my-org",
            "workspace": "my-workspace",
            "project": null
        }
    """
    context = await get_session_context(ctx)
    return {
        "status": "success",
        "context": context
    }


@handle_api_errors
async def get_client_context_tool(ctx: Context) -> Dict[str, Any]:
    """Get client context information for the current session.

    Returns client metadata passed from AWS Bedrock AgentCore Gateway including
    region, agent name, timestamp, and user preferences from the Streamlit Chat UI.

    Args:
        ctx: FastMCP Context (automatically injected)

    Returns:
        Dictionary with client context information

    Examples:
        >>> await get_client_context_tool(ctx)
        {
            "status": "success",
            "client_context": {
                "region": "us-west-2",
                "agent_name": "TFC-Agent",
                "timestamp": 1705000000.0,
                "preferences": {
                    "auto_format": true,
                    "show_raw": false,
                    "show_tools": true,
                    "show_thinking": false
                }
            }
        }
    """
    client_ctx = await get_client_context(ctx)
    
    if not client_ctx:
        return {
            "status": "info",
            "message": "No client context available for this session. "
                      "This is normal if the client doesn't send client context headers."
        }
    
    # Extract individual fields for cleaner response
    region = await get_client_region(ctx)
    agent = await get_client_agent(ctx)
    timestamp = await get_client_timestamp(ctx)
    preferences = await get_client_preferences(ctx)
    
    return {
        "status": "success",
        "client_context": {
            "region": region,
            "agent_name": agent,
            "timestamp": timestamp,
            "preferences": preferences
        }
    }


@handle_api_errors
async def get_client_preferences_tool(ctx: Context) -> Dict[str, Any]:
    """Get user preferences from client context.

    Returns the user preferences sent from the Streamlit Chat UI, including
    display options like auto_format, show_raw, show_tools, and show_thinking.

    Args:
        ctx: FastMCP Context (automatically injected)

    Returns:
        Dictionary with user preferences

    Examples:
        >>> await get_client_preferences_tool(ctx)
        {
            "status": "success",
            "preferences": {
                "auto_format": true,
                "show_raw": false,
                "show_tools": true,
                "show_thinking": false
            }
        }
    """
    preferences = await get_client_preferences(ctx)
    
    return {
        "status": "success",
        "preferences": preferences
    }
