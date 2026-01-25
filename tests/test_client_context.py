"""Integration tests for client context functionality

This module tests the complete client context flow from header extraction
through storage and retrieval, ensuring that client metadata from AWS Bedrock
AgentCore Gateway is properly handled.
"""

import pytest
import json
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any

from fastmcp import Context
from terraform_cloud_mcp.utils.client_context import (
    extract_client_context_from_headers,
    store_client_context,
    get_client_context,
    get_client_region,
    get_client_agent,
    get_client_timestamp,
    get_client_preferences,
    clear_client_context,
)


class MockRequest:
    """Mock HTTP request with headers."""
    
    def __init__(self, headers: Dict[str, str]):
        self.headers = headers


class MockRequestContext:
    """Mock request context containing the HTTP request."""
    
    def __init__(self, headers: Dict[str, str]):
        self.request = MockRequest(headers)


class MockContext:
    """Mock FastMCP Context for testing."""
    
    def __init__(self, headers: Dict[str, str] = None, has_native_session: bool = True):
        self.request_context = MockRequestContext(headers or {})
        self._session_state = {}
        self._has_native = has_native_session
    
    async def set_session_state(self, key: str, value: Any):
        """Mock native session state storage."""
        self._session_state[key] = value
    
    async def get_session_state(self, key: str) -> Any:
        """Mock native session state retrieval."""
        return self._session_state.get(key)
    
    async def remove_session_state(self, key: str):
        """Mock native session state removal."""
        self._session_state.pop(key, None)


class TestClientContextExtraction:
    """Test client context header extraction from HTTP requests."""
    
    def test_extract_all_client_context_headers(self):
        """Test extraction of all client context headers."""
        headers = {
            'X-Session-ID': 'test-session-123',
            'X-Client-Region': 'us-west-2',
            'X-Client-Agent': 'TFC-Agent',
            'X-Client-Timestamp': '1705000000.0',
            'X-Client-Preferences': json.dumps({
                "auto_format": True,
                "show_raw": False,
                "show_tools": True,
                "show_thinking": False
            }),
            'Content-Type': 'application/json',
            'Authorization': 'Bearer token123'
        }
        
        ctx = MockContext(headers)
        
        result = extract_client_context_from_headers(ctx)
        
        assert result['region'] == 'us-west-2'
        assert result['agent_name'] == 'TFC-Agent'
        assert result['timestamp'] == 1705000000.0
        assert result['preferences'] == {
            "auto_format": True,
            "show_raw": False,
            "show_tools": True,
            "show_thinking": False
        }
        assert 'raw_headers' in result
        assert result['raw_headers']['X-Client-Region'] == 'us-west-2'
    
    def test_extract_partial_client_context_headers(self):
        """Test extraction with only some client context headers present."""
        headers = {
            'X-Session-ID': 'test-session-123',
            'X-Client-Region': 'eu-central-1',
            'X-Client-Agent': 'Terraform-Agent',
            # Missing: X-Client-Timestamp, X-Client-Preferences
        }
        
        ctx = MockContext(headers)
        
        result = extract_client_context_from_headers(ctx)
        
        assert result['region'] == 'eu-central-1'
        assert result['agent_name'] == 'Terraform-Agent'
        assert 'timestamp' not in result
        assert 'preferences' not in result
        assert 'raw_headers' in result
    
    def test_extract_no_client_context_headers(self):
        """Test extraction when no client context headers are present."""
        headers = {
            'X-Session-ID': 'test-session-123',
            'Content-Type': 'application/json',
            'Authorization': 'Bearer token123'
        }
        
        ctx = MockContext(headers)
        
        result = extract_client_context_from_headers(ctx)
        
        assert result == {}
    
    def test_extract_invalid_timestamp(self):
        """Test extraction with invalid timestamp format."""
        headers = {
            'X-Session-ID': 'test-session-123',
            'X-Client-Timestamp': 'not-a-number'
        }
        
        ctx = MockContext(headers)
        
        result = extract_client_context_from_headers(ctx)
        
        assert 'timestamp' not in result
        assert result == {}  # No valid headers extracted
    
    def test_extract_invalid_preferences_json(self):
        """Test extraction with invalid JSON in preferences header."""
        headers = {
            'X-Session-ID': 'test-session-123',
            'X-Client-Preferences': 'invalid-json{not-valid}'
        }
        
        ctx = MockContext(headers)
        
        result = extract_client_context_from_headers(ctx)
        
        assert 'preferences' not in result
    
    def test_extract_preferences_not_dict(self):
        """Test extraction when preferences is not a dictionary."""
        headers = {
            'X-Session-ID': 'test-session-123',
            'X-Client-Preferences': json.dumps(["list", "not", "dict"])
        }
        
        ctx = MockContext(headers)
        
        result = extract_client_context_from_headers(ctx)
        
        assert 'preferences' not in result
    
    def test_extract_case_insensitive_headers(self):
        """Test that header extraction is case-insensitive."""
        headers = {
            'x-session-id': 'test-session-123',  # lowercase
            'x-client-region': 'ap-southeast-1',  # lowercase
            'X-CLIENT-AGENT': 'TEST-AGENT',  # uppercase
        }
        
        ctx = MockContext(headers)
        
        result = extract_client_context_from_headers(ctx)
        
        assert result['region'] == 'ap-southeast-1'
        assert result['agent_name'] == 'TEST-AGENT'
    
    def test_extract_no_context(self):
        """Test extraction with None context."""
        result = extract_client_context_from_headers(None)
        assert result == {}
    
    def test_extract_no_request_context(self):
        """Test extraction with no request context."""
        ctx = Mock()
        ctx.request_context = None
        
        result = extract_client_context_from_headers(ctx)
        assert result == {}


class TestClientContextStorage:
    """Test client context storage in session state."""
    
    async def test_store_client_context_native_session(self):
        """Test storing client context with native FastMCP session."""
        ctx = MockContext(has_native_session=True)
        client_context_data = {
            'region': 'us-east-1',
            'agent_name': 'Test-Agent',
            'timestamp': 1705000000.0,
            'preferences': {'auto_format': True},
            'raw_headers': {'X-Client-Region': 'us-east-1'}
        }
        
        await store_client_context(ctx, client_context_data)
        
        # Verify all keys were stored
        assert 'client_context' in ctx._session_state
        assert 'client_region' in ctx._session_state
        assert 'client_agent' in ctx._session_state
        assert 'client_timestamp' in ctx._session_state
        assert 'client_preferences' in ctx._session_state
        
        assert ctx._session_state['client_context'] == client_context_data
        assert ctx._session_state['client_region'] == 'us-east-1'
        assert ctx._session_state['client_agent'] == 'Test-Agent'
        assert ctx._session_state['client_timestamp'] == 1705000000.0
        assert ctx._session_state['client_preferences'] == {'auto_format': True}
    
    async def test_store_partial_client_context(self):
        """Test storing partial client context (some fields missing)."""
        ctx = MockContext(has_native_session=True)
        client_context_data = {
            'region': 'eu-west-1',
            # Missing: agent_name, timestamp, preferences
        }
        
        await store_client_context(ctx, client_context_data)
        
        # Only region should be stored
        assert ctx._session_state['client_region'] == 'eu-west-1'
        assert 'client_agent' not in ctx._session_state
        assert 'client_timestamp' not in ctx._session_state
        assert 'client_preferences' not in ctx._session_state
    
    async def test_store_empty_client_context(self):
        """Test storing empty client context."""
        ctx = MockContext(has_native_session=True)
        
        await store_client_context(ctx, {})
        
        # Should store empty dict as client_context
        assert ctx._session_state.get('client_context') == {}
        # Individual fields should not be stored
        assert 'client_region' not in ctx._session_state
    
    async def test_store_none_context(self):
        """Test storing with None context."""
        result = await store_client_context(None, {'region': 'test'})
        assert result is None  # Should return early without error
    
    async def test_store_none_client_context(self):
        """Test storing with None client context data."""
        ctx = MockContext(has_native_session=True)
        
        await store_client_context(ctx, None)
        
        # Should return early without storing anything
        assert ctx._session_state == {}


class TestClientContextRetrieval:
    """Test client context retrieval from session state."""
    
    async def test_get_client_context_complete(self):
        """Test retrieving complete client context."""
        ctx = MockContext(has_native_session=True)
        stored_context = {
            'region': 'us-west-2',
            'agent_name': 'Test-Agent',
            'timestamp': 1705000000.0,
            'preferences': {'auto_format': True},
            'raw_headers': {'X-Client-Region': 'us-west-2'}
        }
        await ctx.set_session_state('client_context', stored_context)
        
        result = await get_client_context(ctx)
        
        assert result == stored_context
    
    async def test_get_client_context_empty(self):
        """Test retrieving client context when not stored."""
        ctx = MockContext(has_native_session=True)
        
        result = await get_client_context(ctx)
        
        assert result == {}
    
    async def test_get_client_region(self):
        """Test retrieving client region."""
        ctx = MockContext(has_native_session=True)
        await ctx.set_session_state('client_region', 'ap-northeast-1')
        
        result = await get_client_region(ctx)
        
        assert result == 'ap-northeast-1'
    
    async def test_get_client_region_none(self):
        """Test retrieving client region when not stored."""
        ctx = MockContext(has_native_session=True)
        
        result = await get_client_region(ctx)
        
        assert result is None
    
    async def test_get_client_agent(self):
        """Test retrieving client agent."""
        ctx = MockContext(has_native_session=True)
        await ctx.set_session_state('client_agent', 'My-Agent')
        
        result = await get_client_agent(ctx)
        
        assert result == 'My-Agent'
    
    async def test_get_client_timestamp(self):
        """Test retrieving client timestamp."""
        ctx = MockContext(has_native_session=True)
        await ctx.set_session_state('client_timestamp', 1705000000.0)
        
        result = await get_client_timestamp(ctx)
        
        assert result == 1705000000.0
    
    async def test_get_client_preferences(self):
        """Test retrieving client preferences."""
        ctx = MockContext(has_native_session=True)
        preferences = {'auto_format': False, 'show_raw': True}
        await ctx.set_session_state('client_preferences', preferences)
        
        result = await get_client_preferences(ctx)
        
        assert result == preferences
    
    async def test_get_client_preferences_empty(self):
        """Test retrieving client preferences when not stored."""
        ctx = MockContext(has_native_session=True)
        
        result = await get_client_preferences(ctx)
        
        assert result == {}


class TestClientContextClearing:
    """Test clearing client context from session state."""
    
    async def test_clear_client_context(self):
        """Test clearing all client context data."""
        ctx = MockContext(has_native_session=True)
        
        # Store various client context data
        await ctx.set_session_state('client_context', {'region': 'test'})
        await ctx.set_session_state('client_region', 'us-east-1')
        await ctx.set_session_state('client_agent', 'Test-Agent')
        await ctx.set_session_state('client_timestamp', 1234567890.0)
        await ctx.set_session_state('client_preferences', {'auto_format': True})
        
        # Clear client context
        await clear_client_context(ctx)
        
        # Verify all client context keys are removed
        assert 'client_context' not in ctx._session_state
        assert 'client_region' not in ctx._session_state
        assert 'client_agent' not in ctx._session_state
        assert 'client_timestamp' not in ctx._session_state
        assert 'client_preferences' not in ctx._session_state
    
    async def test_clear_client_context_none(self):
        """Test clearing client context with None context."""
        result = await clear_client_context(None)
        assert result is None  # Should return early without error


class TestIntegration:
    """Integration tests for complete client context flow."""
    
    async def test_extract_and_store_complete_flow(self):
        """Test complete flow: extract headers → store → retrieve."""
        # Step 1: Create context with headers
        headers = {
            'X-Session-ID': 'integration-test-123',
            'X-Client-Region': 'ca-central-1',
            'X-Client-Agent': 'Integration-Test-Agent',
            'X-Client-Timestamp': '1705000000.0',
            'X-Client-Preferences': json.dumps({
                'auto_format': True,
                'show_raw': False
            })
        }
        ctx = MockContext(headers, has_native_session=True)
        
        # Step 2: Extract client context
        extracted = extract_client_context_from_headers(ctx)
        assert extracted['region'] == 'ca-central-1'
        assert extracted['agent_name'] == 'Integration-Test-Agent'
        
        # Step 3: Store client context
        await store_client_context(ctx, extracted)
        
        # Step 4: Retrieve and verify
        retrieved = await get_client_context(ctx)
        assert retrieved == extracted
        
        region = await get_client_region(ctx)
        assert region == 'ca-central-1'
        
        agent = await get_client_agent(ctx)
        assert agent == 'Integration-Test-Agent'
        
        preferences = await get_client_preferences(ctx)
        assert preferences == {'auto_format': True, 'show_raw': False}
    
    async def test_backward_compatibility_no_headers(self):
        """Test that system works without client context headers (backward compatibility)."""
        headers = {
            'X-Session-ID': 'backward-compat-test',
            'Content-Type': 'application/json'
        }
        ctx = MockContext(headers, has_native_session=True)
        
        # Extract should return empty dict
        extracted = extract_client_context_from_headers(ctx)
        assert extracted == {}
        
        # Store should handle empty dict gracefully
        await store_client_context(ctx, extracted)
        
        # Retrieval should return empty results
        retrieved = await get_client_context(ctx)
        assert retrieved == {}
        
        region = await get_client_region(ctx)
        assert region is None
        
        preferences = await get_client_preferences(ctx)
        assert preferences == {}


# Mark all tests as async
pytest.mark.asyncio(TestClientContextExtraction)
pytest.mark.asyncio(TestClientContextStorage)
pytest.mark.asyncio(TestClientContextRetrieval)
pytest.mark.asyncio(TestClientContextClearing)
pytest.mark.asyncio(TestIntegration)
