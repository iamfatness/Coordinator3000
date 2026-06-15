"""Per-account bearer-token auth for the agent API.

Each worker (a Claude / Grok / Codex chat session) authenticates as an account
with a `c3k_...` token via `Authorization: Bearer <token>`.
"""
from __future__ import annotations

from fastapi import HTTPException, Request


async def current_account(request: Request) -> dict:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = auth[len("Bearer "):].strip()
    account = await request.app.state.board.account_by_token(token)
    if not account:
        raise HTTPException(status_code=401, detail="invalid token")
    return account
