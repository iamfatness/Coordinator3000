"""Filesystem tools, scoped to a single run's cloned workspace.

`make_fs_tools(ctx)` returns LangChain tools bound (via closure) to one run's
workspace directory. All paths are repo-relative and guarded by `safe_join`.
"""
from __future__ import annotations

import logging
import os

from langchain_core.tools import BaseTool, tool

from app.models import RunContext
from app.tools.workspace import safe_join

log = logging.getLogger(__name__)

_MAX_READ_BYTES = 200_000
_SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", "build"}


def make_fs_tools(ctx: RunContext) -> list[BaseTool]:
    ws = ctx.workspace

    @tool
    def list_files(subdir: str = ".") -> str:
        """List files in the repository, relative to the repo root.

        Args:
            subdir: Repo-relative directory to list (default the repo root).
        """
        base = safe_join(ws, subdir)
        if not os.path.isdir(base):
            return f"ERROR: {subdir!r} is not a directory."
        out: list[str] = []
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), ws)
                out.append(rel)
            if len(out) > 2000:
                out.append("... (truncated)")
                break
        return "\n".join(sorted(out)) or "(empty)"

    @tool
    def read_file(path: str) -> str:
        """Read a UTF-8 text file from the repository.

        Args:
            path: Repo-relative path to the file.
        """
        full = safe_join(ws, path)
        if not os.path.isfile(full):
            return f"ERROR: file not found: {path}"
        size = os.path.getsize(full)
        with open(full, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read(_MAX_READ_BYTES)
        suffix = "" if size <= _MAX_READ_BYTES else "\n... (truncated)"
        return data + suffix

    @tool
    def write_file(path: str, content: str) -> str:
        """Create or overwrite a text file in the repository.

        Args:
            path: Repo-relative path to write.
            content: Full new contents of the file.
        """
        full = safe_join(ws, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(content)
        log.info("wrote %s (%d bytes)", path, len(content))
        return f"OK: wrote {len(content)} bytes to {path}"

    @tool
    def delete_file(path: str) -> str:
        """Delete a file from the repository.

        Args:
            path: Repo-relative path to delete.
        """
        full = safe_join(ws, path)
        if not os.path.isfile(full):
            return f"ERROR: file not found: {path}"
        os.remove(full)
        log.info("deleted %s", path)
        return f"OK: deleted {path}"

    return [list_files, read_file, write_file, delete_file]
