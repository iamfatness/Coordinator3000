"""GitHub webhook verification and event parsing.

Verifies the HMAC signature, then turns an `issues` event into a `Job` when the
configured `ai-task` label is involved. Everything else is ignored.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import uuid

from app.config import get_settings
from app.models import Job

log = logging.getLogger(__name__)


def verify_signature(body: bytes, signature_header: str | None) -> bool:
    """Constant-time verification of the `X-Hub-Signature-256` header."""
    cfg = get_settings()
    if not cfg.github_webhook_secret:
        log.warning("GITHUB_WEBHOOK_SECRET not set — accepting webhook unverified")
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    digest = hmac.new(
        cfg.github_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    expected = f"sha256={digest}"
    return hmac.compare_digest(expected, signature_header)


def parse_issue_event(event: str, payload: dict) -> Job | None:
    """Return a Job if this event should trigger an autonomous run, else None.

    Triggers on:
      * action == "labeled" with the target label, or
      * action == "opened"/"reopened" where the target label is already present.
    """
    if event != "issues":
        return None

    cfg = get_settings()
    action = payload.get("action")
    issue = payload.get("issue") or {}
    repo = payload.get("repository") or {}

    labels = {lbl.get("name") for lbl in issue.get("labels", [])}

    if action == "labeled":
        if (payload.get("label") or {}).get("name") != cfg.ai_task_label:
            return None
    elif action in ("opened", "reopened"):
        if cfg.ai_task_label not in labels:
            return None
    else:
        return None

    if issue.get("pull_request"):
        return None  # issue events fire for PRs too; skip those.

    return Job(
        run_id=uuid.uuid4().hex[:12],
        owner=(repo.get("owner") or {}).get("login", ""),
        repo=repo.get("name", ""),
        issue_number=issue.get("number", 0),
        issue_title=issue.get("title", ""),
        issue_body=issue.get("body") or "",
        base_branch=repo.get("default_branch", "main"),
        clone_url=repo.get("clone_url", ""),
    )
