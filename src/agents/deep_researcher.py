"""
ARIA-OS: Deep Researcher Agent
Department: Intelligence
Specializes in real-time internet grounding.
"""
from google.adk.agents import LlmAgent

from src.config import DEEP_RESEARCHER_INSTRUCTION, MODEL_DEEP
from src.tools.search import google_search

deep_researcher = LlmAgent(
    name="deep_researcher",
    model=MODEL_DEEP,  # Uses the full gemini-3.1-flash for better synthesis
    instruction=DEEP_RESEARCHER_INSTRUCTION,
    tools=[google_search],
    output_key="research_raw_data",
)
