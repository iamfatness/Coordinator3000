"""FastAPI application: GitHub webhook intake + background worker lifecycle.

On startup it opens the Postgres checkpointer and spins up the worker pool; the
webhook endpoint verifies signatures, converts qualifying issue events into jobs,
and returns 202 immediately while workers run the orchestration graph.
"""
from __future__ import annotations

import json
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response

from app import __version__
from app.config import get_settings
from app.graph.checkpointer import open_checkpointer
from app.logging_config import configure_logging, get_logger
from app.webhooks.github import parse_issue_event, verify_signature
from app.worker.queue import JobQueue
from app.worker.runner import _make_processor

log = get_logger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    configure_logging(cfg.log_level)
    log.info("Coordinator3000 %s starting up", __version__)

    async with AsyncExitStack() as stack:
        saver = await stack.enter_async_context(
            open_checkpointer(
                cfg.database_url, max_size=max(4, cfg.worker_concurrency * 2)
            )
        )
        queue = JobQueue(
            processor=_make_processor(saver), concurrency=cfg.worker_concurrency
        )
        await queue.start()
        app.state.queue = queue
        app.state.checkpointer = saver
        try:
            yield
        finally:
            await queue.stop()
    log.info("shutdown complete")


app = FastAPI(title="Coordinator3000", version=__version__, lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/")
async def root() -> dict:
    cfg = get_settings()
    return {
        "service": "Coordinator3000",
        "version": __version__,
        "trigger_label": cfg.ai_task_label,
        "webhook": "POST /webhooks/github",
    }


@app.post("/webhooks/github")
async def github_webhook(request: Request) -> Response:
    body = await request.body()

    if not verify_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401, detail="invalid signature")

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return Response(
            content=json.dumps({"msg": "pong"}), media_type="application/json"
        )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc

    job = parse_issue_event(event, payload)
    if job is None:
        return Response(
            content=json.dumps({"status": "ignored", "event": event}),
            media_type="application/json",
        )
    if not job.clone_url or not job.owner:
        raise HTTPException(status_code=422, detail="incomplete repository payload")

    await request.app.state.queue.enqueue(job)
    log.info("accepted run %s for %s#%d", job.run_id, job.full_name, job.issue_number)
    return Response(
        status_code=202,
        content=json.dumps({"status": "accepted", "run_id": job.run_id}),
        media_type="application/json",
    )
