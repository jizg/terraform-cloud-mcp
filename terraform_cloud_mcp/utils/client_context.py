"""Client context management for Terraform Cloud MCP

This module handles extraction, storage, and retrieval of client context headers
passed from AWS Bedrock AgentCore Gateway. These headers contain metadata about
the client request including region, agent name, timestamp, and user preferences.

Headers processed:
- X-Client-Region: AWS region of the request origin
- X-Client-Agent: Agent name from AgentCore
- X-Client-Timestamp: Request timestamp (Unix epoch)
- X-Client-Preferences: User preferences as JSON string
"""

import json
import logging
from typing import Dict, Any, Optional
from fastmcp import Context

logger = logging.getLogger(__name__)

# Session state keys for client context
SESSION_KEY_CLIENT_CONTEXT = "client_context"
SESSION_KEY_CLIENT_REGION = "client_region"
SESSION_KEY_CLIENT_AGENT = "client_agent"
SESSION_KEY_CLIENT_TIMESTAMP = "client_timestamp"
SESSION_KEY_CLIENT_PREFERENCES = "client_preferences"


def _has_native_session(ctx: Optional[Context]) -> bool:
    """Check if the context supports FastMCP's native session state API."""
    return bool(
        ctx
        and hasattr(ctx, "set_session_state")
        and hasattr(ctx, "get_session_state")
        and hasattr(ctx, "remove_session_state")
    )


def extract_client_context_from_headers(ctx: Optional[Context]) -> Dict[str, Any]:
    """Extract client context from HTTP request headers.
    
    This function reads the X-Client-* headers from the incoming HTTP request
    and returns them as a dictionary. All headers are optional and the function
    will return an empty dictionary if no client context headers are present.
    
    Args:
        ctx: FastMCP Context object that may contain request information
        
    Returns:
        Dictionary containing client context with keys:
        - region: AWS region string (optional)
        - agent_name: Agent name string (optional)
        - timestamp: Unix timestamp float (optional)
        - preferences: Dictionary of user preferences (optional)
        - raw_headers: Original header values for debugging (optional)
    """
    if not ctx:
        logger.debug("[Client Context] No context provided, returning empty context")
        return {}
    
    # Check if we have request context with headers
    if not (ctx.request_context and hasattr(ctx.request_context, 'request')):
        logger.debug("[Client Context] No request context available")
        return {}
    
    try:
        request = ctx.request_context.request
        if not (request and hasattr(request, 'headers')):
            logger.debug("[Client Context] No headers in request")
            return {}
        
        headers = dict(request.headers)
        logger.debug(f"[Client Context] All received headers: {list(headers.keys())}")
        
        client_context: Dict[str, Any] = {}
        raw_headers: Dict[str, str] = {}
        
        # Extract X-Client-Region
        for header_name, header_value in headers.items():
            if header_name.lower() == 'x-client-region' and header_value:
                region = str(header_value)
                client_context['region'] = region
                raw_headers['X-Client-Region'] = region
                logger.info(f"[Client Context] Extracted region: '{region}'")
                break
        
        # Extract X-Client-Agent
        for header_name, header_value in headers.items():
            if header_name.lower() == 'x-client-agent' and header_value:
                agent_name = str(header_value)
                client_context['agent_name'] = agent_name
                raw_headers['X-Client-Agent'] = agent_name
                logger.info(f"[Client Context] Extracted agent: '{agent_name}'")
                break
        
        # Extract X-Client-Timestamp
        for header_name, header_value in headers.items():
            if header_name.lower() == 'x-client-timestamp' and header_value:
                try:
                    timestamp = float(header_value)
                    client_context['timestamp'] = timestamp
                    raw_headers['X-Client-Timestamp'] = header_value
                    logger.info(f"[Client Context] Extracted timestamp: {timestamp}")
                except (ValueError, TypeError) as e:
                    logger.warning(f"[Client Context] Invalid timestamp value '{header_value}': {e}")
                break
        
        # Extract X-Client-Preferences
        for header_name, header_value in headers.items():
            if header_name.lower() == 'x-client-preferences' and header_value:
                try:
                    preferences = json.loads(str(header_value))
                    if isinstance(preferences, dict):
                        client_context['preferences'] = preferences
                        raw_headers['X-Client-Preferences'] = str(header_value)
                        logger.info(f"[Client Context] Extracted preferences: {preferences}")
                    else:
                        logger.warning(f"[Client Context] Preferences is not a dict: {type(preferences)}")
                except json.JSONDecodeError as e:
                    logger.warning(f"[Client Context] Invalid JSON in preferences: {e}")
                break
        
        # Store raw headers for debugging if any client context was found
        if raw_headers:
            client_context['raw_headers'] = raw_headers
            logger.debug(f"[Client Context] Complete extracted context: {client_context}")
        elif headers:
            logger.debug("[Client Context] No client context headers found in request")
        
        return client_context
        
    except Exception as e:
        logger.error(f"[Client Context] Failed to extract client context: {e}")
        return {}


def _get_session_id_from_context(ctx: Optional[Context]) -> str:
    """Safely get session ID from context.
    
    This is a helper function that extracts the session ID using the same
    logic as the main session management module. It's used internally
    when we need the session ID for storage operations.
    
    Args:
        ctx: FastMCP Context object
        
    Returns:
        Session ID string or 'default' for stdio mode
    """
    if not ctx:
        return 'default'
    
    # Import here to avoid circular dependency
    from .session import get_session_id_safe
    return get_session_id_safe(ctx)


def _fb_set(session_id: str, key: str, value: Any) -> None:
    """Set value in fallback in-memory storage."""
    # Import here to avoid circular dependency
    from .session import _fallback_store as fb_store
    bucket = fb_store.setdefault(session_id, {})
    bucket[key] = value


def _fb_get(session_id: str, key: str) -> Any:
    """Get value from fallback in-memory storage."""
    # Import here to avoid circular dependency
    from .session import _fallback_store as fb_store
    bucket = fb_store.get(session_id, {})
    return bucket.get(key)


async def store_client_context(ctx: Optional[Context], client_context: Dict[str, Any]) -> None:
    """Store client context in session state.
    
    Stores the complete client context dictionary and individual fields
    in session state for easy retrieval later.
    
    Args:
        ctx: FastMCP Context object
        client_context: Dictionary containing client context data
    """
    if not ctx or not client_context:
        logger.debug("[Client Context] No context or client_context provided, nothing to store")
        return
    
    session_id = _get_session_id_from_context(ctx)
    logger.info(f"[Client Context] Storing context for session '{session_id}'")
    
    # Store complete client context
    if _has_native_session(ctx):
        await ctx.set_session_state(SESSION_KEY_CLIENT_CONTEXT, client_context)
    else:
        _fb_set(session_id, SESSION_KEY_CLIENT_CONTEXT, client_context)
    logger.debug(f"[Client Context] Stored complete context: {list(client_context.keys())}")
    
    # Store individual fields for easy access
    if 'region' in client_context:
        region = client_context['region']
        if _has_native_session(ctx):
            await ctx.set_session_state(SESSION_KEY_CLIENT_REGION, region)
        else:
            _fb_set(session_id, SESSION_KEY_CLIENT_REGION, region)
        logger.debug(f"[Client Context] Stored region: '{region}'")
    
    if 'agent_name' in client_context:
        agent_name = client_context['agent_name']
        if _has_native_session(ctx):
            await ctx.set_session_state(SESSION_KEY_CLIENT_AGENT, agent_name)
        else:
            _fb_set(session_id, SESSION_KEY_CLIENT_AGENT, agent_name)
        logger.debug(f"[Client Context] Stored agent: '{agent_name}'")
    
    if 'timestamp' in client_context:
        timestamp = client_context['timestamp']
        if _has_native_session(ctx):
            await ctx.set_session_state(SESSION_KEY_CLIENT_TIMESTAMP, timestamp)
        else:
            _fb_set(session_id, SESSION_KEY_CLIENT_TIMESTAMP, timestamp)
        logger.debug(f"[Client Context] Stored timestamp: {timestamp}")
    
    if 'preferences' in client_context:
        preferences = client_context['preferences']
        if _has_native_session(ctx):
            await ctx.set_session_state(SESSION_KEY_CLIENT_PREFERENCES, preferences)
        else:
            _fb_set(session_id, SESSION_KEY_CLIENT_PREFERENCES, preferences)
        logger.debug(f"[Client Context] Stored preferences: {preferences}")
    
    logger.info(f"[Client Context] Successfully stored context for session '{session_id}'")


async def get_client_context(ctx: Optional[Context]) -> Dict[str, Any]:
    """Get the complete client context from session state.
    
    Args:
        ctx: FastMCP Context object
        
    Returns:
        Dictionary containing client context, or empty dict if not found
    """
    if not ctx:
        logger.debug("[Client Context] No context provided, returning empty context")
        return {}
    
    session_id = _get_session_id_from_context(ctx)
    
    if _has_native_session(ctx):
        client_context = await ctx.get_session_state(SESSION_KEY_CLIENT_CONTEXT)
    else:
        client_context = _fb_get(session_id, SESSION_KEY_CLIENT_CONTEXT)
    
    if client_context:
        logger.debug(f"[Client Context] Retrieved context for session '{session_id}'")
        return client_context
    else:
        logger.debug(f"[Client Context] No context found for session '{session_id}'")
        return {}


async def get_client_region(ctx: Optional[Context]) -> Optional[str]:
    """Get the client region from session state.
    
    Args:
        ctx: FastMCP Context object
        
    Returns:
        AWS region string or None if not found
    """
    if not ctx:
        return None
    
    session_id = _get_session_id_from_context(ctx)
    
    if _has_native_session(ctx):
        region = await ctx.get_session_state(SESSION_KEY_CLIENT_REGION)
    else:
        region = _fb_get(session_id, SESSION_KEY_CLIENT_REGION)
    
    if region:
        logger.debug(f"[Client Context] Retrieved region: '{region}'")
    
    return region


async def get_client_agent(ctx: Optional[Context]) -> Optional[str]:
    """Get the client agent name from session state.
    
    Args:
        ctx: FastMCP Context object
        
    Returns:
        Agent name string or None if not found
    """
    if not ctx:
        return None
    
    session_id = _get_session_id_from_context(ctx)
    
    if _has_native_session(ctx):
        agent = await ctx.get_session_state(SESSION_KEY_CLIENT_AGENT)
    else:
        agent = _fb_get(session_id, SESSION_KEY_CLIENT_AGENT)
    
    if agent:
        logger.debug(f"[Client Context] Retrieved agent: '{agent}'")
    
    return agent


async def get_client_timestamp(ctx: Optional[Context]) -> Optional[float]:
    """Get the client timestamp from session state.
    
    Args:
        ctx: FastMCP Context object
        
    Returns:
        Unix timestamp float or None if not found
    """
    if not ctx:
        return None
    
    session_id = _get_session_id_from_context(ctx)
    
    if _has_native_session(ctx):
        timestamp = await ctx.get_session_state(SESSION_KEY_CLIENT_TIMESTAMP)
    else:
        timestamp = _fb_get(session_id, SESSION_KEY_CLIENT_TIMESTAMP)
    
    if timestamp is not None:
        logger.debug(f"[Client Context] Retrieved timestamp: {timestamp}")
    
    return timestamp


async def get_client_preferences(ctx: Optional[Context]) -> Dict[str, Any]:
    """Get the client preferences from session state.
    
    Args:
        ctx: FastMCP Context object
        
    Returns:
        Dictionary of preferences or empty dict if not found
    """
    if not ctx:
        return {}
    
    session_id = _get_session_id_from_context(ctx)
    
    if _has_native_session(ctx):
        preferences = await ctx.get_session_state(SESSION_KEY_CLIENT_PREFERENCES)
    else:
        preferences = _fb_get(session_id, SESSION_KEY_CLIENT_PREFERENCES)
    
    if preferences:
        logger.debug(f"[Client Context] Retrieved preferences: {preferences}")
        return preferences
    else:
        return {}


async def clear_client_context(ctx: Optional[Context]) -> None:
    """Clear all client context data from session state.
    
    Args:
        ctx: FastMCP Context object
    """
    if not ctx:
        logger.debug("[Client Context] No context provided, nothing to clear")
        return
    
    session_id = _get_session_id_from_context(ctx)
    logger.info(f"[Client Context] Clearing context for session '{session_id}'")
    
    if _has_native_session(ctx):
        await ctx.remove_session_state(SESSION_KEY_CLIENT_CONTEXT)
        await ctx.remove_session_state(SESSION_KEY_CLIENT_REGION)
        await ctx.remove_session_state(SESSION_KEY_CLIENT_AGENT)
        await ctx.remove_session_state(SESSION_KEY_CLIENT_TIMESTAMP)
        await ctx.remove_session_state(SESSION_KEY_CLIENT_PREFERENCES)
    else:
        # Import here to avoid circular dependency
        from .session import _fb_remove
        _fb_remove(session_id, SESSION_KEY_CLIENT_CONTEXT)
        _fb_remove(session_id, SESSION_KEY_CLIENT_REGION)
        _fb_remove(session_id, SESSION_KEY_CLIENT_AGENT)
        _fb_remove(session_id, SESSION_KEY_CLIENT_TIMESTAMP)
        _fb_remove(session_id, SESSION_KEY_CLIENT_PREFERENCES)
    
    logger.info(f"[Client Context] Cleared context for session '{session_id}'")
