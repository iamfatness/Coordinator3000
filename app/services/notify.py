"""Events out — post board activity to Slack / a generic webhook.

`emit()` is the single call sites use: it records the event in the activity feed
*and* fires a best-effort outbound notification. Notifications are config-gated
(no-op unless `SLACK_WEBHOOK_URL` or `EVENTS_WEBHOOK_URL` is set) and never raise
into the request path.
"""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


def event_text(type_: str, account: str | None = None, task_key: str | None = None,
               detail: str = "") -> str:
    tk = f" {task_key}" if task_key else ""
    who = f" by {account}" if account else ""
    d = f" — {detail}" if detail else ""
    return f"[Coordinator3000] {type_}{tk}{who}{d}"


async def notify(text: str) -> None:
    cfg = get_settings()
    url = cfg.slack_webhook_url or cfg.events_webhook_url
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={"text": text})
    except Exception as exc:  # noqa: BLE001 - notifications are best-effort
        log.warning("event notification failed: %s", exc)


async def emit(board, type_: str, account: dict | None = None, task_key: str | None = None,
               goal_key: str | None = None, detail: str = "") -> None:
    """Record an activity event and fire an outbound notification."""
    await board.record_event(
        type_, account["id"] if account else None, task_key, goal_key, detail
    )
    await notify(event_text(type_, account["name"] if account else None, task_key, detail))
