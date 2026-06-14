"""Plain data structures shared across the webhook -> queue -> worker pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Job:
    """A unit of autonomous work derived from a labeled GitHub issue."""

    run_id: str
    owner: str
    repo: str
    issue_number: int
    issue_title: str
    issue_body: str
    base_branch: str
    clone_url: str
    delivery_id: str = ""
    trigger: str = "webhook"  # "webhook" | "manual"

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(slots=True)
class RunContext:
    """Everything a single run needs: identity, workspace, repo + issue facts.

    Tools and graph nodes are bound to one of these, so there is no shared
    mutable global state between concurrent runs.
    """

    run_id: str
    owner: str
    repo: str
    issue_number: int
    issue_title: str
    issue_body: str
    base_branch: str
    branch: str
    workspace: str
    clone_url: str
    # Set lazily by the GitHub client/runner.
    pr_url: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"
