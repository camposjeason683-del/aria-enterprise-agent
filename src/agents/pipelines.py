"""
ARIA-OS: Workflows & Pipelines
Orchestrates Sequential and Parallel executions across departments.
"""
from google.adk.agents import BaseAgent, ParallelAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.utils.context_utils import Aclosing
from google.adk.events import Event
from typing import AsyncGenerator

from src.agents.deep_researcher import deep_researcher
from src.agents.demand_planner import demand_planner
from src.agents.document_worker import DocumentWorker
from src.agents.finance_analyst import finance_analyst
from src.agents.inventory_analyst import inventory_analyst
from src.agents.procurement_analyst import procurement_analyst
from src.agents.sales_analyst import sales_analyst
from src.agents.strategic_advisor import strategic_advisor
from src.agents.sync_worker import SyncWorker
from src.agents.synthesizer import SynthesizerWorker

def _c(agent, suffix: str):
    return agent.model_copy(update={"name": f"{agent.name}_{suffix}"})

synthesizer = SynthesizerWorker(name="synthesizer")
document_worker = DocumentWorker(name="document_worker")
sync_worker = SyncWorker(name="sync_worker")

# Research Pipeline: Fetch from Google -> Synthesize -> Output
research_pipeline = SequentialAgent(
    name="research_pipeline",
    sub_agents=[_c(deep_researcher, "res"), SynthesizerWorker(name="synthesizer_res")],
)

# ─── Audit Workflows ────────────────────────────────────────────────

# Basic audit pipeline: Inventory -> Demand -> Finance
audit_pipeline = SequentialAgent(
    name="audit_pipeline",
    sub_agents=[_c(inventory_analyst, "audit"), _c(demand_planner, "audit"), _c(finance_analyst, "audit")],
)

# ─── Automated Pipelines ────────────────────────────────────────────

parallel_report = ParallelAgent(
    name="parallel_report",
    sub_agents=[_c(sales_analyst, "rep"), _c(inventory_analyst, "rep"), _c(finance_analyst, "rep")],
)

morning_brief = SequentialAgent(
    name="morning_brief",
    sub_agents=[
        SyncWorker(name="sync_worker_brief"),
        parallel_report.model_copy(update={
            "name": "parallel_report_brief",
            "sub_agents": [_c(sales_analyst, "brief"), _c(inventory_analyst, "brief"), _c(finance_analyst, "brief")]
        }),
        DocumentWorker(name="document_worker_brief")
    ],
)

reorder_alert = SequentialAgent(
    name="reorder_alert",
    sub_agents=[_c(demand_planner, "reorder"), _c(procurement_analyst, "reorder"), DocumentWorker(name="document_worker_reorder")],
)

class ProactivePipelineAgent(BaseAgent):
    """
    Custom agent that runs the sync worker followed by the strategic advisor.
    It isolates the strategic advisor's chat history from the sync worker's events.
    """
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        if len(self.sub_agents) < 2:
            return
            
        sync_worker = self.sub_agents[0]
        advisor_proactive = self.sub_agents[1]
        
        events_before = len(ctx.session.events)
        
        async with Aclosing(sync_worker.run_async(ctx)) as agen:
            async for event in agen:
                yield event
                
        all_events = ctx.session.events
        sync_events = all_events[events_before:]
        
        ctx.session.events = all_events[:events_before]
        
        try:
            async with Aclosing(advisor_proactive.run_async(ctx)) as agen:
                async for event in agen:
                    yield event
        finally:
            ctx.session.events.extend(sync_events)

proactive_pipeline = ProactivePipelineAgent(
    name="proactive_pipeline",
    sub_agents=[
        SyncWorker(name="sync_worker_proactive"),
        _c(strategic_advisor, "proactive")
    ],
)

