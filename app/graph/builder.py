"""Assemble and compile the outer orchestration graph for a single run.

Topology (durable, checkpointed):

        START
          │
          ▼
   ┌─ orchestrator ◀─────────────┐
   │      │ decision             │
   │  ┌───┼───────────┬───────┐  │
   ▼  ▼   ▼           ▼       ▼  │
 code  review     finalize  abort
   │     │            │       │
   └──────┘           ▼       ▼
   (back to orchestrator)    END

The Coder and Reviewer nodes each run a self-contained ReAct agent (their own
tool loops). The orchestrator decides routing; deterministic guards cap
iterations and always steer toward shipping a PR.
"""
from __future__ import annotations

import asyncio
import logging

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph

from app.agents.coder import build_coder_agent
from app.agents.llm import build_llm
from app.agents.orchestrator import decide_route
from app.agents.reviewer import build_reviewer_agent
from app.config import get_settings
from app.graph.state import TaskState
from app.models import RunContext
from app.tools import git_tools
from app.tools.github_tools import GitHubClient

log = logging.getLogger(__name__)

_INNER_RECURSION_LIMIT = 80


def _message_text(msg) -> str:
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(p for p in parts if p)
    return str(content)


def _final_text(result: dict) -> str:
    messages = result.get("messages", [])
    return _message_text(messages[-1]) if messages else ""


def build_graph(ctx: RunContext, github_client: GitHubClient, checkpointer):
    cfg = get_settings()

    orchestrator_llm = build_llm("orchestrator")
    coder_llm = build_llm("coder")
    reviewer_llm = build_llm("reviewer")
    coder_agent = build_coder_agent(ctx, coder_llm, github_client)

    # ---- nodes --------------------------------------------------------------
    async def orchestrator_node(state: TaskState) -> dict:
        iterations = state.get("iterations", 0)
        # Hard guard: stop iterating and ship whatever we have.
        if iterations >= cfg.max_iterations and not state.get("review_passed"):
            log.info("max iterations (%d) reached -> finalize", cfg.max_iterations)
            return {
                "decision": "finalize",
                "decision_reason": f"reached max iterations ({cfg.max_iterations})",
                "status": "running",
            }
        decision = await asyncio.to_thread(decide_route, orchestrator_llm, ctx, state)
        log.info("orchestrator -> %s (%s)", decision.next, decision.reason)
        updates: dict = {
            "decision": decision.next,
            "decision_reason": decision.reason,
            "status": "running",
        }
        if decision.plan and not state.get("plan"):
            updates["plan"] = decision.plan
        return updates

    async def coder_node(state: TaskState) -> dict:
        instruction = _coder_instruction(ctx, state)
        log.info("coder: starting (iteration %d)", state.get("iterations", 0) + 1)
        result = await coder_agent.ainvoke(
            {"messages": [HumanMessage(instruction)]},
            config={"recursion_limit": _INNER_RECURSION_LIMIT},
        )
        report = _final_text(result) or "(coder produced no summary)"
        return {
            "coder_report": report,
            "iterations": state.get("iterations", 0) + 1,
            "review_passed": False,
            "review_report": "",
            "review_required_changes": "",
        }

    async def reviewer_node(state: TaskState) -> dict:
        agent, verdict = build_reviewer_agent(ctx, reviewer_llm)
        instruction = _reviewer_instruction(ctx, state)
        log.info("reviewer: starting")
        await agent.ainvoke(
            {"messages": [HumanMessage(instruction)]},
            config={"recursion_limit": _INNER_RECURSION_LIMIT},
        )
        if verdict["submitted"]:
            return {
                "review_passed": verdict["approved"],
                "review_report": verdict["summary"],
                "review_required_changes": verdict["required_changes"],
            }
        # Reviewer failed to submit — treat as not-passed, ask for another pass.
        return {
            "review_passed": False,
            "review_report": "Reviewer did not submit a verdict.",
            "review_required_changes": "Re-review the changes and submit a verdict.",
        }

    async def finalize_node(state: TaskState) -> dict:
        return await _finalize(ctx, github_client, state, cfg)

    async def abort_node(state: TaskState) -> dict:
        reason = state.get("decision_reason", "not actionable")
        body = (
            f"🤖 **Coordinator3000** could not act on this issue autonomously.\n\n"
            f"Reason: {reason}\n\n_Removing the `{cfg.ai_task_label}` label and "
            f"re-applying it will trigger another attempt._"
        )
        try:
            await asyncio.to_thread(
                github_client.add_issue_comment, ctx.issue_number, body
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("failed to post abort comment: %s", exc)
        return {"status": "aborted", "error": reason}

    def route(state: TaskState) -> str:
        return state.get("decision", "finalize")

    # ---- wiring -------------------------------------------------------------
    graph = StateGraph(TaskState)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("code", coder_node)
    graph.add_node("review", reviewer_node)
    graph.add_node("finalize", finalize_node)
    graph.add_node("abort", abort_node)

    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        route,
        {
            "code": "code",
            "review": "review",
            "finalize": "finalize",
            "abort": "abort",
        },
    )
    graph.add_edge("code", "orchestrator")
    graph.add_edge("review", "orchestrator")
    graph.add_edge("finalize", END)
    graph.add_edge("abort", END)

    return graph.compile(checkpointer=checkpointer)


# ---- instruction builders ---------------------------------------------------
def _coder_instruction(ctx: RunContext, state: TaskState) -> str:
    base = (
        f"GitHub issue #{ctx.issue_number} in {ctx.full_name}\n"
        f"Title: {ctx.issue_title}\n\n"
        f"Description:\n{ctx.issue_body or '(no description)'}\n\n"
        f"Plan:\n{state.get('plan') or '(none — form your own)'}\n\n"
        f"You are on branch '{ctx.branch}' (base '{ctx.base_branch}'). "
        f"Implement the change, run the tests, and commit."
    )
    if state.get("review_required_changes"):
        base += (
            "\n\nA previous review requested changes. Address them now:\n"
            f"{state['review_required_changes']}"
        )
    return base


def _reviewer_instruction(ctx: RunContext, state: TaskState) -> str:
    return (
        f"Review the work for issue #{ctx.issue_number} in {ctx.full_name}.\n"
        f"Title: {ctx.issue_title}\n\n"
        f"Issue description:\n{ctx.issue_body or '(no description)'}\n\n"
        f"Coder's report:\n{state.get('coder_report') or '(none)'}\n\n"
        f"Inspect the diff, verify it in the sandbox, then submit your verdict."
    )


def _pr_body(ctx: RunContext, state: TaskState) -> str:
    review = state.get("review_report") or "(no review summary)"
    plan = state.get("plan") or "(no recorded plan)"
    passed = state.get("review_passed")
    badge = "✅ automated review passed" if passed else "⚠️ opened for human review"
    return (
        f"## Automated change for #{ctx.issue_number}\n\n"
        f"Closes #{ctx.issue_number}\n\n"
        f"**Status:** {badge}\n\n"
        f"### Plan\n{plan}\n\n"
        f"### Review summary\n{review}\n\n"
        f"---\n_Opened autonomously by Coordinator3000 "
        f"({state.get('iterations', 0)} coder/reviewer iteration(s))._"
    )


async def _finalize(ctx: RunContext, github_client: GitHubClient, state: TaskState, cfg) -> dict:
    has_changes = await asyncio.to_thread(
        git_tools.has_commits, ctx.workspace, ctx.base_branch
    )
    if not has_changes:
        log.warning("finalize: no commits produced for issue #%d", ctx.issue_number)
        try:
            await asyncio.to_thread(
                github_client.add_issue_comment,
                ctx.issue_number,
                "🤖 **Coordinator3000** finished without producing any code changes. "
                "The issue may need clarification or manual work.",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("failed to post no-change comment: %s", exc)
        return {"status": "needs_human", "error": "no changes produced"}

    await asyncio.to_thread(
        git_tools.push_branch, ctx.workspace, ctx.clone_url, ctx.branch
    )

    # Minimal-HITL: ready-for-review when the automated review passed and human
    # approval isn't required; otherwise open as a draft for a human to take over.
    draft = cfg.require_human_approval or not state.get("review_passed", False)
    title = f"[ai-task] {ctx.issue_title} (#{ctx.issue_number})"
    body = _pr_body(ctx, state)

    pr = await asyncio.to_thread(
        lambda: github_client.create_pull_request(
            title=title,
            head=ctx.branch,
            base=ctx.base_branch,
            body=body,
            draft=draft,
        )
    )
    pr_url = pr.get("html_url", "")
    ctx.pr_url = pr_url
    log.info("opened PR %s (draft=%s)", pr_url, draft)

    comment = (
        f"🤖 Opened {'a **draft** ' if draft else 'a '}pull request: {pr_url}\n\n"
        f"{state.get('review_report') or ''}"
    )
    try:
        await asyncio.to_thread(
            github_client.add_issue_comment, ctx.issue_number, comment
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("failed to post PR comment: %s", exc)

    return {"status": "completed", "pr_url": pr_url}
