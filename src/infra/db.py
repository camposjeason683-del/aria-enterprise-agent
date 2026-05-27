"""
ARIA-OS: Supabase Connection Pool (Singleton)
Never create a client per request. This module provides a single
reusable async client for the entire application lifecycle.
"""
import os
import httpx
from supabase import AsyncClientOptions
from supabase._async.client import AsyncClient, create_client

_client: AsyncClient | None = None


async def get_supabase() -> AsyncClient:
    """Return the singleton Supabase async client."""
    global _client
    if _client is None:
        options = AsyncClientOptions(
            httpx_client=httpx.AsyncClient(http2=False)
        )
        _client = await create_client(
            os.environ["SUPABASE_URL"],
            os.environ["SUPABASE_SERVICE_KEY"],
            options=options,
        )
    return _client


async def close_supabase():
    """Close the connection. Called during server shutdown."""
    global _client
    if _client:
        _client = None

