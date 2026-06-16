"""Board administration API — create accounts, projects, goals, tasks, and read
the board. Backs the management UI.

NOTE: these endpoints are unauthenticated for the MVP and assume the app sits
behind network controls. Add an admin guard before exposing publicly — account
creation returns a token.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.auth import admin_auth
from app.api.schemas import AccountIn, GoalIn, ProjectIn, TaskIn
from app.services.notify import emit
from app.store.board import BoardError

# Mutations + token minting require the admin guard; GETs stay open for the
# read-only board UI. `admin` carries no prefix — it's merged into `router`
# (which has the /api/board prefix) at the bottom of this module.
router = APIRouter(prefix="/api/board", tags=["board"])
admin = APIRouter(dependencies=[Depends(admin_auth)])


def _board(request: Request):
    return request.app.state.board


@router.get("")
async def board(request: Request):
    return await _board(request).board()


@admin.post("/accounts", status_code=201)
async def create_account(body: AccountIn, request: Request):
    account, token = await _board(request).create_account(body.name, body.kind, body.scope)
    # The token is shown exactly once.
    return {"account": account, "token": token}


@admin.post("/accounts/{account_id}/revoke")
async def revoke_account(account_id: int, request: Request):
    try:
        return await _board(request).revoke_account(account_id)
    except BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@admin.post("/accounts/{account_id}/rotate")
async def rotate_account(account_id: int, request: Request):
    try:
        account, token = await _board(request).rotate_account(account_id)
        return {"account": account, "token": token}
    except BoardError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/accounts")
async def list_accounts(request: Request):
    return await _board(request).list_accounts()


@admin.post("/projects", status_code=201)
async def create_project(body: ProjectIn, request: Request):
    try:
        return await _board(request).create_project(
            body.key, body.name, body.repo_owner, body.repo_name, body.base_branch
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects")
async def list_projects(request: Request):
    return await _board(request).list_projects()


@admin.post("/goals", status_code=201)
async def create_goal(body: GoalIn, request: Request):
    try:
        return await _board(request).create_goal(
            body.project_key, body.key, body.title, body.description, body.acceptance
        )
    except BoardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/goals")
async def list_goals(request: Request, project_key: str | None = None):
    return await _board(request).list_goals(project_key)


@admin.post("/tasks", status_code=201)
async def create_task(body: TaskIn, request: Request):
    board = _board(request)
    try:
        task = await board.create_task(
            body.goal_key, body.title, body.description, body.priority,
            body.files, body.blocked_by, body.labels, body.acceptance,
        )
    except BoardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await emit(board, "task_created", None, task["key"], body.goal_key.upper(), body.title)
    return task


@router.get("/activity")
async def activity(request: Request, limit: int = 100):
    return await _board(request).list_events(limit=min(limit, 500))


@router.get("/tasks/{key}")
async def get_task(key: str, request: Request):
    task = await _board(request).get_task(key)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task


# Merge the admin-guarded mutation routes under the /api/board prefix.
router.include_router(admin)
