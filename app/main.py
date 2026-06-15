"""FastAPI application: management UI + GitHub webhook intake + workers.

Routes:
  GET  /                  -> management dashboard (HTML)
  GET  /healthz           -> liveness probe
  GET  /api/info          -> service/config summary (JSON)
  GET  /api/runs          -> list runs
  GET  /api/runs/{id}     -> run detail
  POST /api/runs          -> manually trigger a run (owner/repo/issue)
  POST /webhooks/github   -> GitHub webhook (issues labeled `ai-task`)

On startup it opens the Postgres checkpointer + run store and spins up the
worker pool; webhook/manual triggers enqueue jobs that workers run.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app import __version__
from app.api.admin import router as admin_router
from app.api.agent import router as agent_router
from app.config import get_settings
from app.graph.checkpointer import open_checkpointer
from app.logging_config import configure_logging, get_logger
from app.models import Job
from app.store.board import open_board_store
from app.store.runs import open_run_store
from app.tools.github_tools import GitHubClient
from app.webhooks.github import parse_issue_event, verify_signature
from app.worker.queue import JobQueue
from app.worker.runner import _make_processor

log = get_logger("app.main")

_WEB_DIR = Path(__file__).parent / "web"


async def _wait_for_db(database_url: str, attempts: int = 12, delay: float = 3.0) -> None:
    """Block until Postgres accepts a connection, with backoff.

    Makes startup resilient to a momentarily-unavailable DB (slow boot, failover)
    so the deploy doesn't hard-fail on a transient connection error.
    """
    import psycopg

    last = None
    for i in range(1, attempts + 1):
        try:
            conn = await psycopg.AsyncConnection.connect(database_url, connect_timeout=5)
            await conn.close()
            if i > 1:
                log.info("database reachable after %d attempt(s)", i)
            return
        except Exception as exc:  # noqa: BLE001
            last = exc
            log.warning("database not ready (attempt %d/%d): %s", i, attempts, exc)
            if i < attempts:
                await asyncio.sleep(delay)
    raise RuntimeError(f"database unreachable after {attempts} attempts: {last}")


async def _stale_claim_sweeper(board, cfg) -> None:
    """Periodically return tasks claimed past the TTL to the backlog."""
    if cfg.claim_ttl_seconds <= 0:
        return
    while True:
        try:
            released = await board.release_stale(cfg.claim_ttl_seconds)
            if released:
                log.info("auto-released stale claims: %s", ", ".join(released))
        except Exception:  # noqa: BLE001
            log.exception("stale-claim sweep failed")
        await asyncio.sleep(max(5, cfg.claim_sweep_interval))


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    configure_logging(cfg.log_level)
    log.info("Coordinator3000 %s starting up", __version__)

    # Wait for Postgres before opening the stores (resilient startup).
    await _wait_for_db(cfg.database_url)

    async with AsyncExitStack() as stack:
        saver = await stack.enter_async_context(
            open_checkpointer(
                cfg.database_url, max_size=max(4, cfg.worker_concurrency * 2)
            )
        )
        run_store = await stack.enter_async_context(open_run_store(cfg.database_url))
        board = await stack.enter_async_context(open_board_store(cfg.database_url))
        queue = JobQueue(
            processor=_make_processor(saver, run_store),
            concurrency=cfg.worker_concurrency,
        )
        await queue.start()
        app.state.queue = queue
        app.state.checkpointer = saver
        app.state.run_store = run_store
        app.state.board = board
        sweeper = asyncio.create_task(_stale_claim_sweeper(board, cfg))
        try:
            yield
        finally:
            sweeper.cancel()
            await queue.stop()
    log.info("shutdown complete")


app = FastAPI(title="Coordinator3000", version=__version__, lifespan=lifespan)

# Board + agent coordination API (Jira-like tasks; per-account token auth).
app.include_router(agent_router)
app.include_router(admin_router)


# ---- UI ---------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(_WEB_DIR / "index.html")


@app.get("/board", include_in_schema=False)
async def board_ui() -> FileResponse:
    return FileResponse(_WEB_DIR / "board.html")


@app.get("/demo", include_in_schema=False)
async def demo() -> FileResponse:
    # Static, mock-data preview of the envisioned console (no backend calls).
    return FileResponse(_WEB_DIR / "demo.html")


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/info")
async def info() -> dict:
    cfg = get_settings()
    return {
        "service": "Coordinator3000",
        "version": __version__,
        "trigger_label": cfg.ai_task_label,
        "default_provider": cfg.llm_provider,
        "default_model": cfg.llm_model,
        "orchestrator_model": cfg.orchestrator_model or f"{cfg.llm_provider}:{cfg.llm_model}",
        "coder_model": cfg.coder_model or f"{cfg.llm_provider}:{cfg.llm_model}",
        "reviewer_model": cfg.reviewer_model or f"{cfg.llm_provider}:{cfg.llm_model}",
        "max_iterations": cfg.max_iterations,
        "require_human_approval": cfg.require_human_approval,
        "worker_concurrency": cfg.worker_concurrency,
    }


# ---- Runs API ---------------------------------------------------------------
@app.get("/api/runs")
async def list_runs(request: Request) -> JSONResponse:
    runs = await request.app.state.run_store.list(limit=100)
    return JSONResponse(content=_jsonable(runs))


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> JSONResponse:
    run = await request.app.state.run_store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return JSONResponse(content=_jsonable(run))


class TriggerRequest(BaseModel):
    owner: str
    repo: str
    issue_number: int


@app.post("/api/runs", status_code=202)
async def trigger_run(req: TriggerRequest, request: Request) -> JSONResponse:
    """Manually start a run for an existing issue, no webhook/label required."""
    client = GitHubClient(req.owner, req.repo)
    try:
        issue = await asyncio.to_thread(client.get_issue, req.issue_number)
        repo_info = await asyncio.to_thread(client.get_repo)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail=f"could not load issue: {exc}"
        ) from exc
    finally:
        client.close()

    if issue.get("pull_request"):
        raise HTTPException(status_code=400, detail="that number is a PR, not an issue")

    job = Job(
        run_id=uuid.uuid4().hex[:12],
        owner=req.owner,
        repo=req.repo,
        issue_number=req.issue_number,
        issue_title=issue.get("title", ""),
        issue_body=issue.get("body") or "",
        base_branch=repo_info.get("default_branch", "main"),
        clone_url=repo_info.get("clone_url", ""),
        trigger="manual",
    )
    await request.app.state.queue.enqueue(job)
    return JSONResponse(
        status_code=202, content={"status": "accepted", "run_id": job.run_id}
    )


# ---- Webhook ----------------------------------------------------------------
@app.post("/webhooks/github")
async def github_webhook(request: Request) -> Response:
    body = await request.body()

    if not verify_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return JSONResponse(content={"msg": "pong"})

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc

    job = parse_issue_event(event, payload)
    if job is None:
        return JSONResponse(content={"status": "ignored", "event": event})
    if not job.clone_url or not job.owner:
        raise HTTPException(status_code=422, detail="incomplete repository payload")

    await request.app.state.queue.enqueue(job)
    log.info("accepted run %s for %s#%d", job.run_id, job.full_name, job.issue_number)
    return JSONResponse(
        status_code=202, content={"status": "accepted", "run_id": job.run_id}
    )


def _jsonable(data):
    """Convert datetime fields to ISO strings for JSON responses."""
    def conv(v):
        return v.isoformat() if hasattr(v, "isoformat") else v

    if isinstance(data, list):
        return [{k: conv(v) for k, v in row.items()} for row in data]
    return {k: conv(v) for k, v in data.items()}
