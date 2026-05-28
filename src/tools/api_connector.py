import json
import httpx
from typing import Dict, Any, Optional

class APIConnector:
    """
    A dynamic tool that allows ARIA-OS agents to interact with ANY external API
    provided by a tenant, by reading its OpenAPI Specification or equivalent guide.
    """
    
    def __init__(self, tenant_id: str, openapi_spec_json: str):
        """
        Initializes the connector with the tenant's specific OpenAPI specification.
        """
        self.tenant_id = tenant_id
        try:
            self.spec = json.loads(openapi_spec_json)
        except json.JSONDecodeError:
            self.spec = {}
            
    def get_endpoints_summary(self) -> str:
        """
        Returns a summary of available endpoints so the LLM agent understands
        what actions it can perform on the external system.
        """
        if not self.spec.get("paths"):
            return "No endpoints defined in the OpenAPI spec."
            
        summary = "Available API Endpoints:\n"
        for path, methods in self.spec["paths"].items():
            for method, details in methods.items():
                summary += f"- {method.upper()} {path}: {details.get('summary', 'No description')}\n"
        return summary
        
    def execute_request(self, endpoint_path: str, method: str, params: Optional[Dict[str, Any]] = None, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Executes an HTTP request against the configured API.
        The agent can call this after reading the get_endpoints_summary() output.
        """
        # In a real scenario, this base_url would come from the spec or tenant config
        base_url = self.spec.get("servers", [{"url": ""}])[0].get("url")
        if not base_url:
            return {"error": "Base URL not found in API spec."}
            
        url = f"{base_url}{endpoint_path}"
        
        # Simple sandbox execution using httpx
        try:
            with httpx.Client() as client:
                response = client.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    json=body,
                    timeout=10.0
                )
            
            return {
                "status_code": response.status_code,
                "data": response.json() if response.text else None,
                "url_called": url
            }
        except Exception as e:
            return {"error": str(e)}

# This tool can be registered in dynamic_execution.py or skill_synthesizer.py 
# to allow the agent to dynamically explore and call external APIs.
