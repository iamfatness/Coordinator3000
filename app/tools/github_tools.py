"""GitHub REST API client + agent-facing comment tool.

A thin synchronous wrapper over the GitHub REST API (issues, pull requests,
comments, labels). Synchronous on purpose: the worker calls it via
``asyncio.to_thread`` and the agent's sync tools are offloaded to threads by
LangChain, so we never block the event loop.
"""
from __future__ import annotations

import logging

import httpx
from langchain_core.tools import BaseTool, tool
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.config import get_settings
from app.models import RunContext

log = logging.getLogger(__name__)

_RETRYABLE = (httpx.TransportError, httpx.TimeoutException)


class GitHubClient:
    """Minimal GitHub REST client scoped to a single repository."""

    def __init__(self, owner: str, repo: str) -> None:
        cfg = get_settings()
        self.owner = owner
        self.repo = repo
        self._client = httpx.Client(
            base_url=cfg.github_api_url,
            headers={
                "Authorization": f"Bearer {cfg.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "Coordinator3000",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GitHubClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential_jitter(initial=2, max=16),
        retry=retry_if_exception_type(_RETRYABLE),
    )
    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        resp = self._client.request(method, path, **kwargs)
        # 5xx is transient — raise so tenacity retries; 4xx is surfaced as-is.
        if resp.status_code >= 500:
            raise httpx.TransportError(f"GitHub {resp.status_code}: {resp.text[:200]}")
        return resp

    # ---- Issues -------------------------------------------------------------
    def add_issue_comment(self, issue_number: int, body: str) -> dict:
        resp = self._request(
            "POST",
            f"/repos/{self.owner}/{self.repo}/issues/{issue_number}/comments",
            json={"body": body},
        )
        resp.raise_for_status()
        return resp.json()

    def add_labels(self, issue_number: int, labels: list[str]) -> None:
        self._request(
            "POST",
            f"/repos/{self.owner}/{self.repo}/issues/{issue_number}/labels",
            json={"labels": labels},
        )

    def get_issue(self, issue_number: int) -> dict:
        resp = self._request(
            "GET", f"/repos/{self.owner}/{self.repo}/issues/{issue_number}"
        )
        resp.raise_for_status()
        return resp.json()

    def get_repo(self) -> dict:
        resp = self._request("GET", f"/repos/{self.owner}/{self.repo}")
        resp.raise_for_status()
        return resp.json()

    # ---- Pull requests ------------------------------------------------------
    def create_commit_status(
        self, sha: str, state: str, context: str, description: str = ""
    ) -> None:
        self._request(
            "POST",
            f"/repos/{self.owner}/{self.repo}/statuses/{sha}",
            json={"state": state, "context": context, "description": description[:140]},
        )

    def create_pull_request(
        self, *, title: str, head: str, base: str, body: str, draft: bool = False
    ) -> dict:
        resp = self._request(
            "POST",
            f"/repos/{self.owner}/{self.repo}/pulls",
            json={
                "title": title,
                "head": head,
                "base": base,
                "body": body,
                "draft": draft,
                "maintainer_can_modify": True,
            },
        )
        resp.raise_for_status()
        return resp.json()


def make_github_tools(ctx: RunContext, client: GitHubClient) -> list[BaseTool]:
    """Tools that let agents talk back to the issue thread."""

    @tool
    def post_issue_comment(comment: str) -> str:
        """Post a progress comment on the GitHub issue being worked on.

        Use sparingly — for meaningful status updates the human should see.

        Args:
            comment: Markdown body of the comment.
        """
        try:
            client.add_issue_comment(ctx.issue_number, comment)
            return "OK: comment posted."
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {exc}"

    return [post_issue_comment]
