"""Request bodies for the board + agent APIs."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AccountIn(BaseModel):
    name: str
    kind: str = "agent"
    scope: str = "write"  # "write" (claim/submit) or "read" (list/get only)


class ProjectIn(BaseModel):
    key: str
    name: str
    repo_owner: str
    repo_name: str
    base_branch: str = "main"


class GoalIn(BaseModel):
    project_key: str
    key: str
    title: str
    description: str = ""


class TaskIn(BaseModel):
    goal_key: str
    title: str
    description: str = ""
    priority: int = 2
    files: list[str] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)


class NoteIn(BaseModel):
    body: str
    kind: str = "note"


class SubmitIn(BaseModel):
    summary: str
    diff: str


class BlockIn(BaseModel):
    reason: str
