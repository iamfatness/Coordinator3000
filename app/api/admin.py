"""Board administration API — create accounts, projects, goals, tasks, and read
the board. Backs the management UI.

NOTE: these endpoints are unauthenticated for the MVP and assume the app sits
behind network controls. Add an admin guard before exposing publicly — account
creation returns a token.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.api.schemas import AccountIn, GoalIn, ProjectIn, TaskIn
from app.store.board import BoardError

router = APIRouter(prefix="/api/board", tags=["board"])


def _board(request: Request):
    return request.app.state.board


@router.get("")
async def board(request: Request):
    return await _board(request).board()


@router.post("/accounts", status_code=201)
async def create_account(body: AccountIn, request: Request):
    account, token = await _board(request).create_account(body.name, body.kind)
    # The token is shown exactly once.
    return {"account": account, "token": token}


@router.get("/accounts")
async def list_accounts(request: Request):
    return await _board(request).list_accounts()


@router.post("/projects", status_code=201)
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


@router.post("/goals", status_code=201)
async def create_goal(body: GoalIn, request: Request):
    try:
        return await _board(request).create_goal(
            body.project_key, body.key, body.title, body.description
        )
    except BoardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/goals")
async def list_goals(request: Request, project_key: str | None = None):
    return await _board(request).list_goals(project_key)


@router.post("/tasks", status_code=201)
async def create_task(body: TaskIn, request: Request):
    try:
        return await _board(request).create_task(
            body.goal_key, body.title, body.description, body.priority, body.files, body.blocked_by
        )
    except BoardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tasks/{key}")
async def get_task(key: str, request: Request):
    task = await _board(request).get_task(key)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return task
