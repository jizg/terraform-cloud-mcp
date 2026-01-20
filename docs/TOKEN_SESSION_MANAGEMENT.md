# Runtime TFC Token Session Management

## Product Overview

Implement session-based token management for Terraform Cloud MCP server, allowing users to configure their TFC token once per session through the Chat UI instead of passing it to every tool call.

## Core Features

- Create a new `set_token` tool that accepts a token parameter and stores it in memory
- Implement in-memory session storage using a module-level variable
- Modify token retrieval logic to check session token first, then fall back to environment variable
- Register the `set_token` tool in the server
- Maintain backward compatibility with existing TFC_TOKEN environment variable
- Update all tool functions to use the new token retrieval mechanism
- Add proper error handling for token validation

## Tech Stack

- Language: Python 3.x
- Framework: FastMCP
- Storage: In-memory (module-level variable)

## Tech Architecture

### System Architecture

- Architecture pattern: Layered Architecture (storage layer, utility layer, API client layer, tools layer)
- Component structure: Session Store → Token Utility → API Client → Tool Functions
- Token priority: Session token → Environment variable (DEFAULT_TOKEN)

### Module Division

- **Session Storage Module**: New module for managing in-memory session state
- **Token Utility Module**: Enhanced token retrieval with fallback logic
- **API Client Module**: Updated to use new token retrieval function
- **Tools Module**: All tools inherit new token handling automatically

### Data Flow

User calls set_token tool → Token stored in session memory → Subsequent tool calls check session token first → Token passed to API client → API request executed

## Implementation Details

### Core Directory Structure

```
terraform_cloud_mcp/
├── utils/
│   ├── session.py              # New: Session management module
│   └── env.py                  # Modified: Enhanced token retrieval
├── api/
│   └── client.py               # Modified: Use get_active_token()
├── tools/
│   ├── token.py                # New: set_token tool
│   └── ...                     # Existing tools (no changes needed)
└── server.py                   # Modified: Register set_token tool
```

### Key Code Structures

**SessionStorage Class**: Thread-safe in-memory storage for session data.

```python
# New module: terraform_cloud_mcp/utils/session.py
class SessionStorage:
    def __init__(self):
        self._token: Optional[str] = None
        self._lock = asyncio.Lock()

    async def set_token(self, token: str) -> None:
        async with self._lock:
            self._token = token

    async def get_token(self) -> Optional[str]:
        async with self._lock:
            return self._token

# Global session instance
_session = SessionStorage()
```

**get_active_token Function**: Retrieves token with fallback priority.

```python
# Enhanced function in terraform_cloud_mcp/utils/env.py
async def get_active_token() -> Optional[str]:
    """Get active token: session token first, then environment variable."""
    from .session import get_session_token
    session_token = await get_session_token()
    return session_token or get_tfc_token()
```

**API Client Update**: Use async token retrieval instead of DEFAULT_TOKEN.

```python
# Modified in terraform_cloud_mcp/api/client.py
async def api_request(
    path: str,
    method: str = "GET",
    token: Optional[str] = None,
    ...
) -> Dict[str, Any]:
    if token is None:
        from ..utils.env import get_active_token
        token = await get_active_token()

    if not token:
        return {"error": "Token is required. Use set_token tool to configure your token."}
    ...
```

**set_token Tool**: Tool for runtime token configuration.

```python
# New tool in terraform_cloud_mcp/tools/token.py
from ..utils.session import set_session_token

async def set_token(token: str) -> Dict[str, Any]:
    """Set Terraform Cloud API token for the current session."""
    if not token or not token.strip():
        return {"error": "Token cannot be empty"}

    await set_session_token(token.strip())
    return {"status": "success", "message": "Token configured successfully"}
```

### Technical Implementation Plan

1. **Session Storage Implementation**: Create thread-safe SessionStorage class with async lock for token access
2. **Token Retrieval Enhancement**: Add get_active_token() function with session-first, fallback logic
3. **API Client Migration**: Replace DEFAULT_TOKEN with dynamic get_active_token() call
4. **Tool Registration**: Add set_token tool registration in server.py
5. **Backward Compatibility**: Ensure existing TFC_TOKEN environment variable still works

### Integration Points

- Session storage is accessed via utility functions in utils/session.py
- API client imports get_active_token from utils/env
- All existing tools automatically benefit from new token logic through api_request
- New token.py module provides set_token tool for Chat UI

## Technical Considerations

### Logging

- Log when session token is set successfully (masked for security)
- Log when fallback to environment variable occurs
- Log warnings when no token is available

### Performance Optimization

- In-memory storage provides O(1) token retrieval
- Async lock ensures thread safety without blocking
- Session token is cached in memory, no disk I/O

### Security Measures

- Token values are masked in logs
- Input validation for empty or whitespace-only tokens
- Token stored only in memory (cleared on server restart)
- No token persistence to disk

### Scalability

- In-memory storage is lightweight and fast
- Session token lifecycle is tied to MCP server instance
- Each MCP connection maintains its own session context
- Suitable for single-user interactive sessions (typical MCP use case)

## Usage

### Setting the Token

Users can set their Terraform Cloud token through the Chat UI by calling:

```
set_token("your-tfc-token-here")
```

### Automatic Token Resolution

Once set, the token will be automatically used by all Terraform Cloud MCP tools without requiring explicit token parameters.

### Backward Compatibility

If a session token is not set, the system automatically falls back to the `TFC_TOKEN` environment variable, ensuring existing deployments continue to work without changes.
