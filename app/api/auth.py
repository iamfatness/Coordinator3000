"""Per-account bearer-token auth for the agent API.

Each worker (a Claude / Grok / Codex chat session) authenticates as an account
with a `c3k_...` token via `Authorization: Bearer <token>`.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.config import get_settings


async def admin_auth(request: Request) -> None:
    """Guard board-management + token-minting endpoints.

    Authorized by EITHER an `admin`-role account token (`Authorization: Bearer`)
    OR the shared `X-Admin-Token`. If `ADMIN_TOKEN` is unset and no admin token is
    presented, the endpoints are open (dev only) — set it before exposing publicly.
    """
    cfg = get_settings()
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        account = await request.app.state.board.account_by_token(auth[len("Bearer "):].strip())
        if account and account.get("role") == "admin":
            return
    if not cfg.admin_token:
        return
    if request.headers.get("X-Admin-Token", "") != cfg.admin_token:
        raise HTTPException(
            status_code=401,
            detail="admin auth required (X-Admin-Token or an admin-role token)",
        )


async def current_account(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = auth[len("Bearer "):].strip()
    account = await request.app.state.board.account_by_token(token)
    if not account:
        raise HTTPException(status_code=401, detail="invalid token")
    return account
