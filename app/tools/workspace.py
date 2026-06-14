"""Workspace path safety.

Every file/shell tool resolves paths through `safe_join` so an agent can never
read or write outside the cloned repository (no `../../etc/passwd`, no absolute
escapes). This is the primary containment boundary for filesystem access.
"""
from __future__ import annotations

import os


class PathEscapeError(ValueError):
    """Raised when a requested path resolves outside the workspace."""


def safe_join(workspace: str, rel_path: str) -> str:
    """Resolve `rel_path` inside `workspace`, refusing any escape.

    Returns an absolute, normalized path guaranteed to live under `workspace`.
    """
    workspace_abs = os.path.realpath(workspace)
    # Treat the input as relative even if it starts with "/".
    candidate = os.path.normpath(os.path.join(workspace_abs, rel_path.lstrip("/")))
    candidate_abs = os.path.realpath(candidate)
    if candidate_abs != workspace_abs and not candidate_abs.startswith(
        workspace_abs + os.sep
    ):
        raise PathEscapeError(f"path {rel_path!r} escapes the workspace")
    return candidate
