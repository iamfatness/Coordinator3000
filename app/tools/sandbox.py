"""Sandboxed code execution.

Two modes (SANDBOX_MODE):

* ``subprocess`` — runs the command with the working directory pinned to the
  run's workspace, a hard wall-clock timeout, and a scrubbed environment. Good
  enough for trusted-ish CI-style automation on your own repositories.
* ``docker``     — runs the command inside a throwaway container with the
  workspace bind-mounted, ``--network none`` and dropped capabilities. Use this
  when the issue text (and therefore the code Claude runs) is less trusted.

Neither mode is a security panacea. For hostile inputs, layer on gVisor /
Firecracker / a dedicated build VM. The mode is chosen per-deployment in `.env`.
"""
from __future__ import annotations

import logging
import os
import shlex
import subprocess

from langchain_core.tools import BaseTool, tool

from app.config import get_settings
from app.models import RunContext

log = logging.getLogger(__name__)

# Minimal environment handed to sandboxed processes — no secrets leak in.
_SAFE_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
}


def _truncate(text: str, limit: int = 20_000) -> str:
    return text if len(text) <= limit else text[:limit] + "\n... (output truncated)"


def _run_subprocess(workspace: str, argv: list[str], timeout: int) -> str:
    try:
        proc = subprocess.run(  # noqa: S603 - argv is a list, never shell=True
            argv,
            cwd=workspace,
            env=_SAFE_ENV,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout}s"
    body = (
        f"exit_code: {proc.returncode}\n"
        f"--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
    return _truncate(body)


def _run_docker(workspace: str, argv: list[str], timeout: int, image: str) -> str:
    docker_cmd = [
        "docker", "run", "--rm",
        "--network", "none",
        "--cap-drop", "ALL",
        "--pids-limit", "256",
        "--memory", "1g",
        "-v", f"{os.path.realpath(workspace)}:/workspace:rw",
        "-w", "/workspace",
        image,
        *argv,
    ]
    return _run_subprocess(workspace, docker_cmd, timeout)


def make_sandbox_tools(ctx: RunContext) -> list[BaseTool]:
    cfg = get_settings()
    ws = ctx.workspace

    def _execute(argv: list[str]) -> str:
        log.info("sandbox(%s) exec: %s", cfg.sandbox_mode, " ".join(argv[:6]))
        if cfg.sandbox_mode == "docker":
            return _run_docker(ws, argv, cfg.sandbox_timeout, cfg.sandbox_docker_image)
        return _run_subprocess(ws, argv, cfg.sandbox_timeout)

    @tool
    def run_shell(command: str) -> str:
        """Run a shell command inside the repository workspace and return output.

        Use for builds, installs, linters, and test runners
        (e.g. "pytest -q", "npm test", "go build ./..."). Output is captured
        and truncated; the process is killed after the configured timeout.

        Args:
            command: The command line to execute.
        """
        try:
            argv = ["/bin/sh", "-lc", command]
            return _execute(argv)
        except Exception as exc:  # noqa: BLE001 - report to the agent, never crash
            return f"ERROR: {exc}"

    @tool
    def run_python(code: str) -> str:
        """Execute a snippet of Python inside the workspace and return output.

        Args:
            code: Python source to run with the workspace as the cwd.
        """
        try:
            return _execute(["python", "-c", code])
        except Exception as exc:  # noqa: BLE001
            return f"ERROR: {exc}"

    return [run_shell, run_python]


def run_tests_quick(workspace: str, command: str, timeout: int = 300) -> str:
    """Convenience helper used outside the agent loop (e.g. smoke checks)."""
    return _run_subprocess(workspace, shlex.split(command), timeout)
