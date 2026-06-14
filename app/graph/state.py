"""The outer graph's checkpointed state.

This is the durable record of a run, persisted to Postgres by the LangGraph
checkpointer. The inner ReAct agents keep their own ephemeral message state;
only these high-level facts survive across steps and process restarts.
"""
from __future__ import annotations

from typing import TypedDict


class TaskState(TypedDict, total=False):
    plan: str
    coder_report: str
    review_report: str
    review_required_changes: str
    review_passed: bool
    iterations: int
    decision: str          # next route chosen by the orchestrator
    decision_reason: str
    status: str            # running | completed | needs_human | failed | aborted
    pr_url: str
    error: str
