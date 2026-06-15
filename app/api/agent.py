"""Agent-facing API — what a worker chat agent calls to move work forward.

Loop: GET /agent/goals/{goal}/work -> POST claim -> do the work -> POST submit
(a unified diff; Coordinator3000 opens the PR) -> POST notes for coordination.
All endpoints require a per-account bearer token.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.auth import current_account
from app.api.schemas import BlockIn, NoteIn, SubmitIn
from app.services.submit import SubmitError, submit_diff
from app.store.board import BoardError, Conflict

log = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"])


def _board(request: Request):
    return request.app.state.board


def _require_write(account: dict) -> None:
    if account.get("scope", "write") != "write":
        raise HTTPException(status_code=403, detail="this token is read-only")


@router.get("/me")
async def me(account: dict = Depends(current_account)) -> dict:
    return account


@router.get("/goals")
async def goals(request: Request, project_key: str | None = None, account: dict = Depends(current_account)):
    return await _board(request).list_goals(project_key)


@router.get("/goals/{goal_key}/work")
async def work(goal_key: str, request: Request, account: dict = Depends(current_account)):
    try:
        return await _board(request).list_work(goal_key)
    except BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tasks/{key}")
async def get_task(key: str, request: Request, account: dict = Depends(current_account)):
    task = await _board(request).get_task(key)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.post("/tasks/{key}/claim")
async def claim(key: str, request: Request, account: dict = Depends(current_account)):
    _require_write(account)
    board = _board(request)
    try:
        result = await board.claim_task(key, account["id"])
    except Conflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await board.record_event("claimed", account["id"], key.upper())
    if result.get("conflicts"):
        await board.record_event(
            "conflict", account["id"], key.upper(), "overlaps " + ", ".join(result["conflicts"])
        )
    return result


@router.post("/tasks/{key}/notes")
async def add_note(key: str, body: NoteIn, request: Request, account: dict = Depends(current_account)):
    _require_write(account)
    board = _board(request)
    try:
        note = await board.add_note(key, account["id"], body.body, body.kind)
    except BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await board.record_event("note", account["id"], key.upper(), body.body)
    return note


@router.post("/tasks/{key}/submit")
async def submit(key: str, body: SubmitIn, request: Request, account: dict = Depends(current_account)):
    _require_write(account)
    board = _board(request)
    task = await board.get_task(key)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task.get("assignee") not in (account["id"], None):
        raise HTTPException(status_code=409, detail="task is claimed by another account")
    project = await board.project_by_id(task["project_id"])
    if not project:
        raise HTTPException(status_code=400, detail="task has no project")
    try:
        result = await submit_diff(project, task, account["name"], body.diff, body.summary)
    except SubmitError as exc:
        # Patch failed — keep the task claimed and tell the agent what broke.
        await board.add_note(key, account["id"], f"Submit failed: {exc}", "note")
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await board.submit_task(key, result["branch"], result["pr_url"])
    await board.record_event("submitted", account["id"], key.upper(), result["pr_url"])
    return {"status": "in_review", **result}


@router.post("/tasks/{key}/block")
async def block(key: str, body: BlockIn, request: Request, account: dict = Depends(current_account)):
    _require_write(account)
    board = _board(request)
    try:
        await board.add_note(key, account["id"], f"Blocked: {body.reason}", "note")
        task = await board.set_status(key, "blocked")
    except BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await board.record_event("blocked", account["id"], key.upper(), body.reason)
    return task


@router.post("/tasks/{key}/release")
async def release(key: str, request: Request, account: dict = Depends(current_account)):
    _require_write(account)
    board = _board(request)
    try:
        task = await board.set_status(key, "backlog")
    except BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await board.record_event("released", account["id"], key.upper())
    return task
