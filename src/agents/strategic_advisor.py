"""
ARIA-OS: Strategic Advisor Agent
Department: Executive / C-Suite
The apex agent capable of requesting human confirmation.
"""
from typing import AsyncGenerator
from google.adk.agents import LlmAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

from src.config import STRATEGIC_ADVISOR_INSTRUCTION, MODEL_DEEP
from src.agents.inventory_analyst import inventory_analyst
from src.agents.finance_analyst import finance_analyst
from src.graph.skill_retriever import get_tools_for_node
from src.callbacks.security import (
    before_model_handler,
    sanitize_output,
    validate_tool_params,
)

inventory_worker = inventory_analyst.model_copy(update={
    "name": "inventory_worker",
    "mode": "single_turn",
})
finance_worker = finance_analyst.model_copy(update={
    "name": "finance_worker",
    "mode": "single_turn",
})


class StrategicAdvisor(LlmAgent):
    """
    Custom LLM Agent.
    """

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        # Proceed with the normal LLM flow.
        async for event in super()._run_async_impl(ctx):
            yield event


strategic_advisor = StrategicAdvisor(
    name="strategic_advisor",
    model=MODEL_DEEP,  # Deep model for best strategic reasoning
    instruction=STRATEGIC_ADVISOR_INSTRUCTION,
    tools=get_tools_for_node("strategic"),
    sub_agents=[inventory_worker, finance_worker],
    before_model_callback=before_model_handler,
    after_model_callback=sanitize_output,
    before_tool_callback=validate_tool_params,
    output_key="strategic_proposal",
)
