"""MCP server exposing the Coordinator3000 board as tools.

Connector-capable chat apps (Claude.ai, ChatGPT) attach this as an MCP server
and drive the work loop with tools — same operations as the REST API. Workers
authenticate with their `c3k_...` token via the `Authorization: Bearer` header
on the connector; the token is resolved per-request into the calling account.

Run standalone (its own endpoint — kept separate from the FastAPI app so their
lifespans don't entangle):

    python -m app.mcp_server            # serves streamable-http on :8001

Requires the optional `mcp` dependency (`pip install mcp`).
"""
from __future__ import annotations

import asyncio
import contextvars
import logging

from app.config import get_settings
from app.store.board import BoardError, BoardStore, Conflict

log = logging.getLogger(__name__)

try:
    from mcp.server.fastmcp import FastMCP
except Exception as exc:  # noqa: BLE001
    raise RuntimeError("the 'mcp' package is required for the MCP server") from exc

from app.services.submit import SubmitError, submit_diff  # noqa: E402

_account_ctx: contextvars.ContextVar[dict | None] = contextvars.ContextVar("c3k_account", default=None)
_store: BoardStore | None = None
_lock = asyncio.Lock()

mcp = FastMCP("Coordinator3000")


async def _board() -> BoardStore:
    global _store
    if _store is None:
        async with _lock:
            if _store is None:
                from psycopg_pool import AsyncConnectionPool

                cfg = get_settings()
                pool = AsyncConnectionPool(
                    conninfo=cfg.database_url, max_size=4, open=False,
                    kwargs={"autocommit": True, "prepare_threshold": 0},
                )
                await pool.open()
                store = BoardStore(pool)
                await store.setup()
                _store = store
    return _store


def _account() -> dict:
    acct = _account_ctx.get()
    if not acct:
        raise ValueError("Unauthorized — set 'Authorization: Bearer <c3k token>' on the connector.")
    return acct


@mcp.tool()
async def whoami() -> dict:
    """Return the worker account this connector is authenticated as."""
    return _account()


@mcp.tool()
async def list_work(goal_key: str) -> dict:
    """List outstanding (ready vs blocked) tasks for a goal, best task first."""
    _account()
    try:
        return await (await _board()).list_work(goal_key)
    except BoardError as exc:
        return {"error": str(exc)}


@mcp.tool()
async def get_task(task_key: str) -> dict:
    """Get a task's full detail, including notes and file-overlap conflicts."""
    _account()
    return await (await _board()).get_task(task_key) or {"error": "task not found"}


@mcp.tool()
async def claim_task(task_key: str) -> dict:
    """Atomically claim a task so no other worker takes it. Returns conflicts."""
    acct = _account()
    try:
        return await (await _board()).claim_task(task_key, acct["id"])
    except Conflict as exc:
        return {"error": str(exc), "conflict": True}
    except BoardError as exc:
        return {"error": str(exc)}


@mcp.tool()
async def add_note(task_key: str, body: str) -> dict:
    """Add a coordination note to a task (e.g. to flag or resolve a conflict)."""
    acct = _account()
    try:
        return await (await _board()).add_note(task_key, acct["id"], body)
    except BoardError as exc:
        return {"error": str(exc)}


@mcp.tool()
async def submit_work(task_key: str, summary: str, diff: str) -> dict:
    """Submit a unified diff for a claimed task. Coordinator3000 commits it and
    opens the pull request, then marks the task in-review."""
    acct = _account()
    board = await _board()
    task = await board.get_task(task_key)
    if not task:
        return {"error": "task not found"}
    project = await board.project_by_id(task["project_id"])
    try:
        result = await submit_diff(project, task, acct["name"], diff, summary)
    except SubmitError as exc:
        await board.add_note(task_key, acct["id"], f"Submit failed: {exc}")
        return {"error": str(exc)}
    await board.submit_task(task_key, result["branch"], result["pr_url"])
    return {"status": "in_review", **result}


@mcp.tool()
async def block_task(task_key: str, reason: str) -> dict:
    """Mark a task blocked with a reason (added as a note)."""
    acct = _account()
    board = await _board()
    await board.add_note(task_key, acct["id"], f"Blocked: {reason}")
    return await board.set_status(task_key, "blocked")


@mcp.tool()
async def release_task(task_key: str) -> dict:
    """Release a claimed task back to the backlog for another worker."""
    _account()
    return await (await _board()).set_status(task_key, "backlog")


class _AuthASGI:
    """Pure-ASGI middleware: resolve the bearer token into the account contextvar
    in the same task that handles the request (so tools can read it)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.lower(): v for k, v in (scope.get("headers") or [])}
            auth = headers.get(b"authorization", b"").decode()
            token = auth[len("Bearer "):].strip() if auth.startswith("Bearer ") else ""
            account = None
            if token:
                try:
                    account = await (await _board()).account_by_token(token)
                except Exception:  # noqa: BLE001
                    account = None
            reset = _account_ctx.set(account)
            try:
                await self.app(scope, receive, send)
            finally:
                _account_ctx.reset(reset)
        else:
            await self.app(scope, receive, send)


def get_asgi_app():
    """Return the streamable-HTTP ASGI app wrapped with token auth."""
    return _AuthASGI(mcp.streamable_http_app())


if __name__ == "__main__":
    from app.logging_config import configure_logging

    configure_logging(get_settings().log_level)
    # FastMCP manages its own session lifespan when run directly.
    mcp.settings.host = "0.0.0.0"
    mcp.settings.port = 8001
    mcp.run(transport="streamable-http")
