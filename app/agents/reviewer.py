"""The Reviewer agent — a ReAct agent that verifies the Coder's work.

It inspects the diff, runs tests/linters in the sandbox, and records a verdict by
calling the `submit_review` tool exactly once. The verdict is captured in a
mutable holder dict the calling node reads after the agent finishes.
"""
from __future__ import annotations

from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from app.agents.prompts import REVIEWER_SYSTEM
from app.models import RunContext
from app.tools import git_tools
from app.tools.fs_tools import make_fs_tools
from app.tools.sandbox import make_sandbox_tools


def build_reviewer_agent(ctx: RunContext, llm) -> tuple[object, dict]:
    """Return (compiled_agent, verdict_holder)."""
    verdict: dict = {
        "submitted": False,
        "approved": False,
        "summary": "",
        "required_changes": "",
    }

    @tool
    def git_diff() -> str:
        """Show the full diff of this branch against the base branch."""
        try:
            return git_tools.diff(ctx.workspace, ctx.base_branch) or "(no changes)"
        except git_tools.GitError as exc:
            return f"ERROR: {exc}"

    @tool
    def submit_review(approved: bool, summary: str, required_changes: str = "") -> str:
        """Record the final review verdict. Call this exactly once when done.

        Args:
            approved: True only if the change fully and correctly resolves the issue.
            summary: A short overall assessment.
            required_changes: If not approved, concrete fixes the Coder must make.
        """
        verdict.update(
            submitted=True,
            approved=bool(approved),
            summary=summary,
            required_changes=required_changes,
        )
        return "Review recorded."

    tools = [git_diff, *make_fs_tools(ctx), *make_sandbox_tools(ctx), submit_review]
    agent = create_react_agent(llm, tools, prompt=REVIEWER_SYSTEM)
    return agent, verdict
