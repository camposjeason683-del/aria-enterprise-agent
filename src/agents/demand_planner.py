"""
ARIA-OS: Demand Planner Agent
Department: Inventory & Operations
"""
from google.adk.agents import LlmAgent

from src.config import DEMAND_PLANNER_INSTRUCTION, MODEL_FAST
from src.graph.skill_retriever import get_tools_for_node
from src.callbacks.security import (
    before_model_handler,
    sanitize_output,
    validate_tool_params,
)

demand_planner = LlmAgent(
    name="demand_planner",
    model=MODEL_FAST,
    instruction=DEMAND_PLANNER_INSTRUCTION,
    tools=get_tools_for_node("demand"),
    before_model_callback=before_model_handler,
    after_model_callback=sanitize_output,
    before_tool_callback=validate_tool_params,
    output_key="demand_forecast",
)
