"""
ARIA-OS: Coordinator LLM
Fallback LLM agent for queries that are too ambiguous for heuristic routing.
Extracted from coordinator.py so the kernel_workflow can import it without
creating circular imports.
"""
from google.adk import Agent
from google.adk.agents import BaseAgent
BaseAgent.mode = None

from src.callbacks.security import (
    before_model_handler,
    sanitize_output,
    validate_tool_params,
)
from src.config import COORDINATOR_INSTRUCTION, MODEL_FAST
from src.graph.skill_retriever import get_tools_for_node


def build_coordinator_llm() -> Agent:
    """
    Build the LLM-powered fallback coordinator.

    Sub-agents are cloned with a unique name suffix and run in `single_turn`
    mode so that each parallel data-fetch branch:
      - Returns control automatically to the coordinator when done
      - Runs in an isolated session branch (no cross-contamination of tokens)
      - Can be executed concurrently (parallel_worker=True)

    NOTE: single_turn mode only applies to LlmAgent (Agent) instances.
    SequentialAgent / custom BaseAgent subclasses retain default behaviour.
    """
    from src.agents.demand_planner import demand_planner
    from src.agents.inventory_analyst import inventory_analyst
    from src.agents.pipelines import research_pipeline
    from src.agents.sales_analyst import sales_analyst
    from src.agents.procurement_analyst import procurement_analyst
    from src.agents.finance_analyst import finance_analyst
    from src.agents.strategic_advisor import strategic_advisor
    from src.agents.document_worker import DocumentWorker

    def _clone_as_worker(agent, suffix: str):
        """Clone an LlmAgent as a single_turn isolated worker."""
        cloned = agent.model_copy(update={
            "name": f"{agent.name}_{suffix}",
            "mode": "single_turn",         # Auto-return, no user interaction
        })
        return cloned

    def _clone(agent, suffix: str):
        """Clone a non-LlmAgent (SequentialAgent etc.) with a unique name."""
        return agent.model_copy(update={"name": f"{agent.name}_{suffix}"})

    return Agent(
        name="coordinator_llm",
        model=MODEL_FAST,
        instruction=COORDINATOR_INSTRUCTION,
        mode="chat",
        tools=get_tools_for_node("coordinator", include_dynamic=False),
        sub_agents=[
            _clone_as_worker(inventory_analyst,  "coord"),
            _clone_as_worker(demand_planner,     "coord"),
            _clone(research_pipeline,            "coord"),  # SequentialAgent
            _clone_as_worker(sales_analyst,      "coord"),
            _clone_as_worker(procurement_analyst,"coord"),
            _clone_as_worker(finance_analyst,    "coord"),
            _clone_as_worker(strategic_advisor,  "coord"),
            DocumentWorker(name="document_worker_coord"),
        ],
        before_model_callback=before_model_handler,
        after_model_callback=sanitize_output,
        before_tool_callback=validate_tool_params,
    )

