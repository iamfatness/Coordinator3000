"""The Coder agent — a ReAct agent that implements the requested change.

It runs its own internal tool-calling loop (read/write files, run the sandbox,
commit) and is invoked as a single node by the outer LangGraph state machine.
"""
from __future__ import annotations

from langgraph.prebuilt import create_react_agent

from app.agents.prompts import CODER_SYSTEM
from app.models import RunContext
from app.tools.fs_tools import make_fs_tools
from app.tools.git_tools import make_git_tools
from app.tools.github_tools import GitHubClient, make_github_tools
from app.tools.sandbox import make_sandbox_tools


def build_coder_agent(ctx: RunContext, llm, github_client: GitHubClient):
    tools = (
        make_fs_tools(ctx)
        + make_git_tools(ctx)
        + make_sandbox_tools(ctx)
        + make_github_tools(ctx, github_client)
    )
    return create_react_agent(llm, tools, prompt=CODER_SYSTEM)
