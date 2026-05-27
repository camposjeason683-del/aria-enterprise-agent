"""
ARIA-OS: Sales Analyst Agent
Department: Sales & Customers
"""
from google.adk.agents import LlmAgent

from src.config import SALES_ANALYST_INSTRUCTION, MODEL_FAST
from src.graph.skill_retriever import get_tools_for_node
from src.callbacks.security import (
    before_model_handler,
    sanitize_output,
    validate_tool_params,
)

# Use the skill retriever to get only the relevant tools
tools = get_tools_for_node("sales")

sales_analyst = LlmAgent(
    name="sales_analyst",
    model=MODEL_FAST,
    instruction=SALES_ANALYST_INSTRUCTION,
    tools=tools,
    before_model_callback=before_model_handler,
    after_model_callback=sanitize_output,
    before_tool_callback=validate_tool_params,
    output_key="sales_analysis",
)
