"""Git operations: clone / branch / commit / push, plus agent-facing tools.

Standalone functions (`clone_repo`, `create_branch`, `push_branch`, `diff`) are
used by the runner/finalize step. `make_git_tools(ctx)` returns the LangChain
tools the Coder agent uses to stage and commit its work.

Authentication: the GitHub token is injected into the remote URL only at the
moment of clone/push and is never written to `.git/config`, keeping it out of
the workspace that sandboxed code can read.
"""
from __future__ import annotations

import logging
import subprocess
from urllib.parse import quote

from langchain_core.tools import BaseTool, tool

from app.config import get_settings
from app.models import RunContext
from app.utils.retry import network_retry

log = logging.getLogger(__name__)


class GitError(RuntimeError):
    pass


def _git(workspace: str, *args: str, timeout: int = 300) -> str:
    proc = subprocess.run(  # noqa: S603
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _authenticated_url(clone_url: str, token: str) -> str:
    """Embed the token into an https GitHub URL for clone/push only."""
    if not token or not clone_url.startswith("https://"):
        return clone_url
    rest = clone_url[len("https://"):]
    return f"https://x-access-token:{quote(token, safe='')}@{rest}"


@network_retry()
def clone_repo(clone_url: str, workspace: str, base_branch: str) -> None:
    """Clone `base_branch` of the repo into `workspace` and configure identity."""
    cfg = get_settings()
    auth_url = _authenticated_url(clone_url, cfg.github_token)
    log.info("cloning %s (%s) -> %s", clone_url, base_branch, workspace)
    subprocess.run(  # noqa: S603
        ["git", "clone", "--depth", "50", "--branch", base_branch, auth_url, workspace],
        capture_output=True,
        text=True,
        timeout=600,
        check=True,
    )
    _git(workspace, "config", "user.name", cfg.git_author_name)
    _git(workspace, "config", "user.email", cfg.git_author_email)


def create_branch(workspace: str, branch: str) -> None:
    """Create and check out a fresh working branch."""
    _git(workspace, "checkout", "-b", branch)
    log.info("created branch %s", branch)


def apply_patch(workspace: str, diff_text: str) -> None:
    """Apply a unified diff to the workspace and stage it.

    Tries a strict apply, then a 3-way merge fallback. Raises GitError with the
    git message if the patch doesn't apply, so the caller can hand it back to the
    agent to fix.
    """
    import os
    import tempfile

    if not diff_text.endswith("\n"):
        diff_text += "\n"
    fd, path = tempfile.mkstemp(suffix=".patch", dir=workspace)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(diff_text)
        try:
            _git(workspace, "apply", "--whitespace=fix", path)
        except GitError:
            _git(workspace, "apply", "--3way", "--whitespace=fix", path)
        _git(workspace, "add", "-A")
    finally:
        os.remove(path)


def has_commits(workspace: str, base_branch: str) -> bool:
    """True if the working branch has commits beyond `base_branch`."""
    out = _git(workspace, "rev-list", "--count", f"origin/{base_branch}..HEAD")
    try:
        return int(out.strip()) > 0
    except ValueError:
        return False


def diff(workspace: str, base_branch: str) -> str:
    """Return the diff of the working branch against the base branch."""
    return _git(workspace, "diff", f"origin/{base_branch}...HEAD")


def commit_all(workspace: str, message: str) -> str:
    """Stage everything and commit; return the short SHA."""
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-m", message)
    return _git(workspace, "rev-parse", "--short", "HEAD").strip()


@network_retry()
def push_branch(workspace: str, clone_url: str, branch: str) -> None:
    """Push the working branch to origin using an ephemeral authenticated URL."""
    cfg = get_settings()
    auth_url = _authenticated_url(clone_url, cfg.github_token)
    log.info("pushing branch %s", branch)
    proc = subprocess.run(  # noqa: S603
        ["git", "push", auth_url, f"HEAD:refs/heads/{branch}"],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if proc.returncode != 0:
        raise GitError(f"git push failed: {proc.stderr.strip()}")


def make_git_tools(ctx: RunContext) -> list[BaseTool]:
    ws = ctx.workspace
    base = ctx.base_branch

    @tool
    def git_status() -> str:
        """Show the current git status (staged/unstaged/untracked files)."""
        try:
            return _git(ws, "status", "--short", "--branch") or "(clean)"
        except GitError as exc:
            return f"ERROR: {exc}"

    @tool
    def git_diff() -> str:
        """Show the full diff of all changes made so far on this branch."""
        try:
            working = _git(ws, "diff", "HEAD")
            committed = diff(ws, base)
            return (committed + "\n" + working).strip() or "(no changes yet)"
        except GitError as exc:
            return f"ERROR: {exc}"

    @tool
    def git_commit(message: str) -> str:
        """Stage all changes and create a commit.

        Args:
            message: A concise, conventional commit message describing the change.
        """
        try:
            _git(ws, "add", "-A")
            status = _git(ws, "status", "--porcelain")
            if not status.strip():
                return "Nothing to commit (working tree clean)."
            _git(ws, "commit", "-m", message)
            sha = _git(ws, "rev-parse", "--short", "HEAD").strip()
            log.info("committed %s: %s", sha, message)
            return f"OK: created commit {sha}"
        except GitError as exc:
            return f"ERROR: {exc}"

    return [git_status, git_diff, git_commit]
