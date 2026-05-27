"""
ARIA-OS: Root Agent Builder (ADK 2.0)
Entry point that main.py calls to get the root agent for the Runner.
Now returns an ADK 2.0 Workflow (graph-based) instead of a KernelAgent.
"""
from src.agents.kernel import build_kernel_workflow


def build_root_agent():
    """Build and return the complete ARIA-OS agent tree as an ADK 2.0 Workflow."""
    return build_kernel_workflow()
