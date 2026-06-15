"""Per-account bearer-token auth for the agent API.

Each worker (a Claude / Grok / Codex chat session) authenticates as an account
with a `c3k_...` token via `Authorization: Bearer <token>`.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.config import get_settings


async def admin_auth(request: Request) -> None:
    """Guard board-management + token-minting endpoints via `X-Admin-Token`.

    If `ADMIN_TOKEN` is unset the endpoints are open (dev only); set it before
    exposing the app publicly.
    """
    cfg = get_settings()
    if not cfg.admin_token:
        return
    if request.headers.get("X-Admin-Token", "") != cfg.admin_token:
        raise HTTPException(status_code=401, detail="missing or invalid admin token")


async def current_account(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = auth[len("Bearer "):].strip()
    account = await request.app.state.board.account_by_token(token)
    if not account:
        raise HTTPException(status_code=401, detail="invalid token")
    return account
