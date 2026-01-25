"""Session management for Terraform Cloud MCP using FastMCP native session state

This module provides utilities for working with FastMCP's built-in session state
functionality (available in FastMCP 3.0.0+). It stores per-session data such as:
- Terraform Cloud API token
- Current organization/workspace/project context
- User preferences

FastMCP automatically handles session isolation via ctx.session_id header,
with support for distributed deployments via custom storage backends.
"""

import logging
from typing import Dict, Any, Optional
from fastmcp import Context
import asyncio

# Import client context utilities
from . import client_context

logger = logging.getLogger(__name__)

# Session state keys
SESSION_KEY_TOKEN = "tfc_token"
SESSION_KEY_ORGANIZATION = "current_organization"
SESSION_KEY_WORKSPACE = "current_workspace"
SESSION_KEY_PROJECT = "current_project"
SESSION_KEY_PREFERENCES = "preferences"
SESSION_KEY_CLIENT_CONTEXT = "client_context"
SESSION_KEY_CLIENT_REGION = "client_region"
SESSION_KEY_CLIENT_AGENT = "client_agent"
SESSION_KEY_CLIENT_TIMESTAMP = "client_timestamp"
SESSION_KEY_CLIENT_PREFERENCES = "client_preferences"

# Fallback in-memory storage when FastMCP Context doesn't expose
# get/set/remove_session_state (older FastMCP versions).
# Structure: { session_id: { key: value } }
_fallback_store: Dict[str, Dict[str, Any]] = {}

def _has_native_session(ctx: Optional[Context]) -> bool:
    return bool(
        ctx
        and hasattr(ctx, "set_session_state")
        and hasattr(ctx, "get_session_state")
        and hasattr(ctx, "remove_session_state")
    )

def _fb_set(session_id: str, key: str, value: Any) -> None:
    bucket = _fallback_store.setdefault(session_id, {})
    bucket[key] = value

def _fb_get(session_id: str, key: str) -> Any:
    bucket = _fallback_store.get(session_id, {})
    return bucket.get(key)

def _fb_remove(session_id: str, key: str) -> None:
    bucket = _fallback_store.get(session_id)
    if not bucket:
        return
    bucket.pop(key, None)


def get_session_id_safe(ctx: Optional[Context]) -> str:
    """Safely get session ID from context with proper error handling.
    
    This function extracts the session ID from FastMCP context, which is:
    - Automatically set by FastMCP from Mcp-Session-Id header
    - Available as ctx.session_id after session establishment
    - Unique per client session (not per request)
    
    Args:
        ctx: FastMCP Context object (may be None in some edge cases)
    
    Returns:
        Session ID string, or 'default' for stdio mode
        
    Raises:
        ValueError: If running in HTTP mode (sse/streamable-http) but no session_id available
    """
    if not ctx:
        logger.info("[Session ID] No context provided, using 'default'")
        return 'default'
    
    # Primary: Extract x-session-id from HTTP request headers
    if ctx.request_context and hasattr(ctx.request_context, 'request'):
        try:
            request = ctx.request_context.request
            if request and hasattr(request, 'headers'):
                headers = dict(request.headers)
                logger.info(f"[Session ID DEBUG] All received headers: {headers}")
                # Find x-session-id header (case-insensitive)
                for header_name, header_value in headers.items():
                    if header_name.lower() == 'x-session-id' and header_value:
                        session_id = str(header_value)
                        logger.info(f"[Session ID] Using x-session-id header: '{session_id}'")
                        
                        # Extract and store client context from headers (fire and forget)
                        client_ctx = client_context.extract_client_context_from_headers(ctx)
                        if client_ctx:
                            logger.info(f"[Session ID] Client context found, storing for session '{session_id}'")
                            # Fire and forget - don't block session ID extraction
                            _ = asyncio.create_task(client_context.store_client_context(ctx, client_ctx))
                        else:
                            logger.info(f"[Session ID] No client context headers found for session '{session_id}'")
                        
                        return session_id
        except Exception as e:
            logger.warning(f"[Session ID] Failed to get HTTP request: {e}")
    
    # Fallback: Check if ctx.session_id exists (for older FastMCP versions)
    if hasattr(ctx, 'session_id') and ctx.session_id:
        logger.info(f"[Session ID] Using ctx.session_id as fallback: '{ctx.session_id}'")
        return str(ctx.session_id)
    
    # Check transport type
    transport = getattr(ctx, 'transport', None)
    
    if transport in ('streamable-http', 'sse'):
        # HTTP mode REQUIRES session_id for proper isolation
        error_msg = (
            f"Missing required x-session-id header in {transport} mode. "
            f"Ensure your HTTP client sends the 'x-session-id' header for session isolation."
        )
        logger.error(f"[Session ID] {error_msg}")
        raise ValueError(error_msg)
    
    # Stdio mode: use default session
    logger.info("[Session ID] Using 'default' for stdio mode")
    return 'default'


# ============================================================================
# Token Management
# ============================================================================

async def set_session_token(token: str, ctx: Optional[Context] = None) -> None:
    """Set the Terraform Cloud API token in session state.
    
    Uses FastMCP's native ctx.set_session_state() which:
    - Automatically isolates by session_id
    - Supports distributed storage backends
    - Has 1-day default TTL
    
    Args:
        token: The Terraform Cloud API token to store
        ctx: FastMCP Context object (required in HTTP mode)
    """
    if not ctx:
        logger.warning("[Set Token] No context provided, token not stored")
        return
    
    session_id = get_session_id_safe(ctx)
    if _has_native_session(ctx):
        await ctx.set_session_state(SESSION_KEY_TOKEN, token)
    else:
        _fb_set(session_id, SESSION_KEY_TOKEN, token)
    
    masked = f"{token[:8]}...{token[-4:]}" if len(token) > 12 else "***"
    logger.info(f"[Set Token] Token stored for session '{session_id}' (masked: {masked})")


async def get_session_token(ctx: Optional[Context] = None) -> Optional[str]:
    """Get the Terraform Cloud API token from session state.
    
    Args:
        ctx: FastMCP Context object
        
    Returns:
        The stored token, or None if not set or expired
    """
    if not ctx:
        logger.info("[Get Token] No context provided, returning None")
        return None
    
    session_id = get_session_id_safe(ctx)
    if _has_native_session(ctx):
        token = await ctx.get_session_state(SESSION_KEY_TOKEN)
    else:
        token = _fb_get(session_id, SESSION_KEY_TOKEN)
    
    if token:
        logger.info(f"[Get Token] Retrieved token for session '{session_id}'")
    else:
        logger.info(f"[Get Token] No token found for session '{session_id}'")
    
    return token


async def clear_session_token(ctx: Optional[Context] = None) -> None:
    """Clear the Terraform Cloud API token from session state.
    
    Args:
        ctx: FastMCP Context object
    """
    if not ctx:
        logger.warning("[Clear Token] No context provided")
        return
    
    session_id = get_session_id_safe(ctx)
    if _has_native_session(ctx):
        await ctx.remove_session_state(SESSION_KEY_TOKEN)
    else:
        _fb_remove(session_id, SESSION_KEY_TOKEN)
    logger.info(f"[Clear Token] Token removed for session '{session_id}'")


# ============================================================================
# Context Management (Organization/Workspace/Project)
# ============================================================================

async def set_current_organization(organization: str, ctx: Optional[Context] = None) -> None:
    """Set the current organization in session context.
    
    Args:
        organization: Organization name or ID
        ctx: FastMCP Context object
    """
    if not ctx:
        return

    session_id = get_session_id_safe(ctx)
    if _has_native_session(ctx):
        await ctx.set_session_state(SESSION_KEY_ORGANIZATION, organization)
    else:
        _fb_set(session_id, SESSION_KEY_ORGANIZATION, organization)
    logger.info(f"[Context] Set current organization to '{organization}'")


async def get_current_organization(ctx: Optional[Context] = None) -> Optional[str]:
    """Get the current organization from session context.
    
    Returns:
        Organization name/ID, or None if not set
    """
    if not ctx:
        return None

    session_id = get_session_id_safe(ctx)
    if _has_native_session(ctx):
        return await ctx.get_session_state(SESSION_KEY_ORGANIZATION)
    else:
        return _fb_get(session_id, SESSION_KEY_ORGANIZATION)


async def set_current_workspace(workspace: str, ctx: Optional[Context] = None) -> None:
    """Set the current workspace in session context.
    
    Args:
        workspace: Workspace name or ID
        ctx: FastMCP Context object
    """
    if not ctx:
        return

    session_id = get_session_id_safe(ctx)
    if _has_native_session(ctx):
        await ctx.set_session_state(SESSION_KEY_WORKSPACE, workspace)
    else:
        _fb_set(session_id, SESSION_KEY_WORKSPACE, workspace)
    logger.info(f"[Context] Set current workspace to '{workspace}'")


async def get_current_workspace(ctx: Optional[Context] = None) -> Optional[str]:
    """Get the current workspace from session context.
    
    Returns:
        Workspace name/ID, or None if not set
    """
    if not ctx:
        return None

    session_id = get_session_id_safe(ctx)
    if _has_native_session(ctx):
        return await ctx.get_session_state(SESSION_KEY_WORKSPACE)
    else:
        return _fb_get(session_id, SESSION_KEY_WORKSPACE)


async def set_current_project(project: str, ctx: Optional[Context] = None) -> None:
    """Set the current project in session context.
    
    Args:
        project: Project name or ID
        ctx: FastMCP Context object
    """
    if not ctx:
        return

    session_id = get_session_id_safe(ctx)
    if _has_native_session(ctx):
        await ctx.set_session_state(SESSION_KEY_PROJECT, project)
    else:
        _fb_set(session_id, SESSION_KEY_PROJECT, project)
    logger.info(f"[Context] Set current project to '{project}'")


async def get_current_project(ctx: Optional[Context] = None) -> Optional[str]:
    """Get the current project from session context.
    
    Returns:
        Project name/ID, or None if not set
    """
    if not ctx:
        return None

    session_id = get_session_id_safe(ctx)
    if _has_native_session(ctx):
        return await ctx.get_session_state(SESSION_KEY_PROJECT)
    else:
        return _fb_get(session_id, SESSION_KEY_PROJECT)


async def set_session_context(
    ctx: Optional[Context] = None,
    organization: Optional[str] = None,
    workspace: Optional[str] = None,
    project: Optional[str] = None
) -> None:
    """Set multiple context values at once.
    
    Args:
        ctx: FastMCP Context object
        organization: Organization name/ID to set
        workspace: Workspace name/ID to set
        project: Project name/ID to set
    """
    if not ctx:
        return
    
    if organization:
        await set_current_organization(organization, ctx)
    if workspace:
        await set_current_workspace(workspace, ctx)
    if project:
        await set_current_project(project, ctx)


async def get_session_context(ctx: Optional[Context] = None) -> Dict[str, Optional[str]]:
    """Get all context values for the current session.
    
    Returns:
        Dictionary with organization, workspace, and project
    """
    if not ctx:
        return {
            "organization": None,
            "workspace": None,
            "project": None
        }
    
    return {
        "organization": await get_current_organization(ctx),
        "workspace": await get_current_workspace(ctx),
        "project": await get_current_project(ctx)
    }


async def clear_session_context(ctx: Optional[Context] = None) -> None:
    """Clear all context values from session state.
    
    Args:
        ctx: FastMCP Context object
    """
    if not ctx:
        return

    session_id = get_session_id_safe(ctx)
    if _has_native_session(ctx):
        await ctx.remove_session_state(SESSION_KEY_ORGANIZATION)
        await ctx.remove_session_state(SESSION_KEY_WORKSPACE)
        await ctx.remove_session_state(SESSION_KEY_PROJECT)
    else:
        _fb_remove(session_id, SESSION_KEY_ORGANIZATION)
        _fb_remove(session_id, SESSION_KEY_WORKSPACE)
        _fb_remove(session_id, SESSION_KEY_PROJECT)
    logger.info("[Context] Cleared all session context")


# ============================================================================
# User Preferences
# ============================================================================

async def set_preference(key: str, value: Any, ctx: Optional[Context] = None) -> None:
    """Set a user preference in session state.
    
    Args:
        key: Preference key (e.g., 'output_format', 'page_size')
        value: Preference value
        ctx: FastMCP Context object
    """
    if not ctx:
        return

    session_id = get_session_id_safe(ctx)
    if _has_native_session(ctx):
        preferences = await ctx.get_session_state(SESSION_KEY_PREFERENCES) or {}
        preferences[key] = value
        await ctx.set_session_state(SESSION_KEY_PREFERENCES, preferences)
    else:
        prefs = _fb_get(session_id, SESSION_KEY_PREFERENCES) or {}
        prefs[key] = value
        _fb_set(session_id, SESSION_KEY_PREFERENCES, prefs)
    logger.debug(f"[Preferences] Set {key}={value}")


async def get_preference(key: str, default: Any = None, ctx: Optional[Context] = None) -> Any:
    """Get a user preference from session state.
    
    Args:
        key: Preference key
        default: Default value if not set
        ctx: FastMCP Context object
        
    Returns:
        Preference value or default
    """
    if not ctx:
        return default

    session_id = get_session_id_safe(ctx)
    if _has_native_session(ctx):
        preferences = await ctx.get_session_state(SESSION_KEY_PREFERENCES) or {}
    else:
        preferences = _fb_get(session_id, SESSION_KEY_PREFERENCES) or {}
    return preferences.get(key, default)


async def get_all_preferences(ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Get all user preferences from session state.
    
    Returns:
        Dictionary of all preferences
    """
    if not ctx:
        return {}

    session_id = get_session_id_safe(ctx)
    if _has_native_session(ctx):
        return await ctx.get_session_state(SESSION_KEY_PREFERENCES) or {}
    else:
        return _fb_get(session_id, SESSION_KEY_PREFERENCES) or {}


# ============================================================================
# Client Context Integration
# ============================================================================

async def get_client_context(ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Get the complete client context for the session.
    
    Returns client metadata passed from AWS Bedrock AgentCore Gateway including
    region, agent name, timestamp, and user preferences.
    
    Args:
        ctx: FastMCP Context object
        
    Returns:
        Dictionary with client context information
    """
    if not ctx:
        return {}
    
    return await client_context.get_client_context(ctx)


async def get_client_region(ctx: Optional[Context] = None) -> Optional[str]:
    """Get the AWS region from client context.
    
    Args:
        ctx: FastMCP Context object
        
    Returns:
        AWS region string or None if not available
    """
    if not ctx:
        return None
    
    return await client_context.get_client_region(ctx)


async def get_client_agent(ctx: Optional[Context] = None) -> Optional[str]:
    """Get the agent name from client context.
    
    Args:
        ctx: FastMCP Context object
        
    Returns:
        Agent name string or None if not available
    """
    if not ctx:
        return None
    
    return await client_context.get_client_agent(ctx)


async def get_client_timestamp(ctx: Optional[Context] = None) -> Optional[float]:
    """Get the request timestamp from client context.
    
    Args:
        ctx: FastMCP Context object
        
    Returns:
        Unix timestamp float or None if not available
    """
    if not ctx:
        return None
    
    return await client_context.get_client_timestamp(ctx)


async def get_client_preferences(ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Get user preferences from client context.
    
    Args:
        ctx: FastMCP Context object
        
    Returns:
        Dictionary of user preferences or empty dict if not available
    """
    if not ctx:
        return {}
    
    return await client_context.get_client_preferences(ctx)


async def clear_client_context(ctx: Optional[Context] = None) -> None:
    """Clear all client context data from session state.
    
    Args:
        ctx: FastMCP Context object
    """
    if not ctx:
        return
    
    await client_context.clear_client_context(ctx)


# ============================================================================
# Session Information & Debugging
# ============================================================================

async def get_session_info(ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Get comprehensive session information for debugging.
    
    Returns:
        Dictionary with session ID, context, token status, preferences, and client context
    """
    if not ctx:
        return {
            "session_id": "unknown",
            "transport": None,
            "has_token": False,
            "context": {},
            "preferences": {},
            "client_context": {}
        }
    
    session_id = get_session_id_safe(ctx)
    token = await get_session_token(ctx)
    context = await get_session_context(ctx)
    preferences = await get_all_preferences(ctx)
    client_context = await get_client_context(ctx)
    
    # Add individual client context fields for easy access
    client_region = await get_client_region(ctx)
    client_agent = await get_client_agent(ctx)
    client_timestamp = await get_client_timestamp(ctx)
    client_preferences = await get_client_preferences(ctx)
    
    return {
        "session_id": session_id,
        "transport": getattr(ctx, 'transport', None),
        "has_token": bool(token),
        "context": context,
        "preferences": preferences,
        "client_context": {
            **client_context,
            "region": client_region,
            "agent_name": client_agent,
            "timestamp": client_timestamp,
            "preferences": client_preferences
        }
    }
