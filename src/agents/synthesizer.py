"""
ARIA-OS: Synthesizer Worker (Non-LLM)
Department: Intelligence
"""
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import types


class SynthesizerWorker(BaseAgent):
    """
    Transforms raw research into structured JSON and outputs it
    so the pipeline can route it or present it.
    """

    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        raw_data = ctx.session.state.get("research_raw_data", "No data found.")
        
        # In a real scenario, this could use a structured parser or
        # another LLM pass to ensure strict JSON. For now, it passes
        # the raw markdown forward while updating the state.
        
        ctx.session.state["structured_research"] = raw_data
        
        yield Event(
            author=self.name,
            content=types.Content(parts=[types.Part(text=raw_data)])
        )
