"""The Orchestrator — decides routing between Coder, Reviewer, and finalize.

Uses Claude with structured output to pick the next step, wrapped with
deterministic guards (iteration cap, review state) in the graph node so the run
always terminates and always prefers shipping a PR.
"""
from __future__ import annotations

import logging
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.agents.prompts import ORCHESTRATOR_SYSTEM
from app.models import RunContext

log = logging.getLogger(__name__)


class RouteDecision(BaseModel):
    """Structured routing decision emitted by the orchestrator."""

    next: Literal["code", "review", "finalize", "abort"] = Field(
        description="The next step to take."
    )
    reason: str = Field(description="One sentence explaining the choice.")
    plan: str = Field(
        default="",
        description="On the first decision, a short plan for resolving the issue.",
    )


def decide_route(llm, ctx: RunContext, state: dict) -> RouteDecision:
    """Ask the model for the next routing decision given current run state."""
    context = (
        f"Repository: {ctx.full_name}\n"
        f"Issue #{ctx.issue_number}: {ctx.issue_title}\n\n"
        f"Issue body:\n{ctx.issue_body or '(no description)'}\n\n"
        f"--- Run state ---\n"
        f"iterations_done: {state.get('iterations', 0)}\n"
        f"plan: {state.get('plan') or '(none yet)'}\n"
        f"latest_coder_report: {state.get('coder_report') or '(none yet)'}\n"
        f"latest_review: {state.get('review_report') or '(none yet)'}\n"
        f"review_passed: {state.get('review_passed')}\n"
        f"review_required_changes: {state.get('review_required_changes') or '(none)'}\n"
    )
    structured = llm.with_structured_output(RouteDecision)
    try:
        decision = structured.invoke(
            [SystemMessage(ORCHESTRATOR_SYSTEM), HumanMessage(context)]
        )
        return decision
    except Exception as exc:  # noqa: BLE001 - never let routing crash the run
        log.warning("orchestrator structured decision failed, using fallback: %s", exc)
        # Deterministic fallback keeps the run moving forward.
        if not state.get("coder_report"):
            return RouteDecision(next="code", reason="fallback: start implementation")
        if state.get("review_passed"):
            return RouteDecision(next="finalize", reason="fallback: review passed")
        if state.get("review_report"):
            return RouteDecision(next="code", reason="fallback: address review")
        return RouteDecision(next="review", reason="fallback: review the changes")
