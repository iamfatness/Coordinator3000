"""Turn an agent-submitted diff into a branch, commit, push, and pull request.

This is how worker agents (Claude / Grok / Codex chat apps) land code without
any GitHub credentials of their own: they POST a unified diff, and Coordinator3000
applies it to the project repo with its single token and opens the PR.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import uuid

from app.config import get_settings
from app.tools import git_tools
from app.tools.github_tools import GitHubClient

log = logging.getLogger(__name__)


def _slug(text: str, n: int = 36) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:n].strip("-")) or "task"


class SubmitError(RuntimeError):
    """Raised when the diff cannot be applied or the PR cannot be opened."""


async def submit_diff(project: dict, task: dict, account_name: str, diff: str, summary: str) -> dict:
    """Apply `diff` to the project repo on a new branch and open a PR.

    Returns {"branch", "pr_url", "sha"}. Raises SubmitError on a bad patch.
    """
    cfg = get_settings()
    owner, repo = project["repo_owner"], project["repo_name"]
    base = project["base_branch"]
    clone_url = f"https://github.com/{owner}/{repo}.git"
    branch = f"c3k/{task['key'].lower()}-{_slug(task['title'])}"
    workspace = os.path.join(cfg.workspace_root, f"submit-{task['key'].lower()}-{uuid.uuid4().hex[:8]}")
    os.makedirs(cfg.workspace_root, exist_ok=True)

    github = GitHubClient(owner, repo)
    try:
        await asyncio.to_thread(git_tools.clone_repo, clone_url, workspace, base)
        await asyncio.to_thread(git_tools.create_branch, workspace, branch)
        try:
            await asyncio.to_thread(git_tools.apply_patch, workspace, diff)
        except git_tools.GitError as exc:
            raise SubmitError(f"patch did not apply: {exc}") from exc

        commit_msg = f"{task['key']}: {task['title']}\n\n{summary}\n\nSubmitted via Coordinator3000 by {account_name}."
        sha = await asyncio.to_thread(git_tools.commit_all, workspace, commit_msg)
        full_sha = await asyncio.to_thread(git_tools.head_sha, workspace)
        await asyncio.to_thread(git_tools.push_branch, workspace, clone_url, branch)

        accept = task.get("acceptance") or task.get("goal_acceptance") or ""
        accept_block = f"**Definition of done:**\n{accept}\n\n" if accept else ""
        body = (
            f"### {task['key']} — {task['title']}\n\n"
            f"{task.get('description') or ''}\n\n"
            f"{accept_block}"
            f"**Summary (agent):**\n{summary}\n\n"
            f"---\n_Submitted via Coordinator3000 by worker `{account_name}`._"
        )
        pr = await asyncio.to_thread(
            lambda: github.create_pull_request(
                title=f"[{task['key']}] {task['title']}",
                head=branch, base=base, body=body, draft=False,
            )
        )
        pr_url = pr.get("html_url", "")
        # Best-effort GitHub commit status so the PR shows a Coordinator3000 check.
        try:
            await asyncio.to_thread(
                github.create_commit_status, full_sha, "success",
                "coordinator3000", f"submitted by {account_name}",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("commit status failed: %s", exc)
        log.info("submitted %s -> %s", task["key"], pr_url)
        return {"branch": branch, "pr_url": pr_url, "sha": sha}
    finally:
        github.close()
        shutil.rmtree(workspace, ignore_errors=True)
