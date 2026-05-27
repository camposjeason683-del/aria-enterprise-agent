"""
ARIA-OS: Procurement Analyst Agent
Department: Procurement & Suppliers
"""
from google.adk.agents import LlmAgent

from src.config import PROCUREMENT_ANALYST_INSTRUCTION, MODEL_FAST
from src.graph.skill_retriever import get_tools_for_node
from src.callbacks.security import (
    before_model_handler,
    sanitize_output,
    validate_tool_params,
)

procurement_analyst = LlmAgent(
    name="procurement_analyst",
    model=MODEL_FAST,
    instruction=PROCUREMENT_ANALYST_INSTRUCTION,
    tools=get_tools_for_node("procurement"),
    before_model_callback=before_model_handler,
    after_model_callback=sanitize_output,
    before_tool_callback=validate_tool_params,
    output_key="procurement_analysis",
)
