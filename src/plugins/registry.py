"""
ARIA-OS: SaaS Plugin Registry
Dynamically loads capabilities per-tenant from the database.
"""
from typing import Any
from src.infra.db import get_supabase
from src.infra.logger import log_info

class PluginRegistry:
    """
    Manages dynamic tool capabilities available per tenant.
    For example: some tenants pay for 'DeepResearchPlugin', 
    others only have access to 'InventoryPlugin'.
    """
    
    async def get_active_plugins(self, tenant_id: str) -> list[str]:
        client = await get_supabase()
        res = await client.table("tenant_plugins").select("plugin_name").eq("tenant_id", tenant_id).eq("active", True).execute()
        return [p["plugin_name"] for p in (res.data or [])]
        
    async def get_data_sources(self, tenant_id: str) -> list[dict[str, Any]]:
        client = await get_supabase()
        res = await client.table("tenant_data_sources").select("source_type, credentials").eq("tenant_id", tenant_id).execute()
        return res.data or []
        
    def inject_plugins_into_agent(self, agent_name: str, active_plugins: list[str]):
        """
        Stub: In a full SaaS context, this would mutate the agent's tool layout
        by appending plugin-provided FunctionTools.
        """
        log_info(f"Injecting {len(active_plugins)} plugins into {agent_name}")
        pass

registry = PluginRegistry()
