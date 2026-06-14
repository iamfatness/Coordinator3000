"""Tests for webhook signature verification and issue-event parsing.

These import only the light webhook/config/model layers (no LLM stack), so they
run fast and offline.
"""
from __future__ import annotations

import hashlib
import hmac
from types import SimpleNamespace

import pytest

from app.webhooks import github as gh


def _settings(secret: str = "", label: str = "ai-task") -> SimpleNamespace:
    return SimpleNamespace(github_webhook_secret=secret, ai_task_label=label)


def _payload(action="labeled", label="ai-task", labels=None, pr=False) -> dict:
    issue = {
        "number": 7,
        "title": "Fix the thing",
        "body": "details here",
        "labels": [{"name": n} for n in (labels or [])],
    }
    if pr:
        issue["pull_request"] = {"url": "https://example/pulls/1"}
    return {
        "action": action,
        "label": {"name": label},
        "issue": issue,
        "repository": {
            "name": "repo",
            "owner": {"login": "me"},
            "default_branch": "main",
            "clone_url": "https://github.com/me/repo.git",
        },
    }


# ---- signature --------------------------------------------------------------
def test_verify_signature_roundtrip(monkeypatch):
    monkeypatch.setattr(gh, "get_settings", lambda: _settings(secret="s3cr3t"))
    body = b'{"hello":"world"}'
    sig = "sha256=" + hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
    assert gh.verify_signature(body, sig) is True


def test_verify_signature_rejects_bad(monkeypatch):
    monkeypatch.setattr(gh, "get_settings", lambda: _settings(secret="s3cr3t"))
    assert gh.verify_signature(b"{}", "sha256=deadbeef") is False
    assert gh.verify_signature(b"{}", None) is False


def test_verify_signature_no_secret_accepts(monkeypatch):
    monkeypatch.setattr(gh, "get_settings", lambda: _settings(secret=""))
    assert gh.verify_signature(b"{}", None) is True


# ---- parsing ----------------------------------------------------------------
def test_labeled_with_target_label(monkeypatch):
    monkeypatch.setattr(gh, "get_settings", lambda: _settings())
    job = gh.parse_issue_event("issues", _payload(action="labeled", label="ai-task"))
    assert job is not None
    assert job.issue_number == 7
    assert job.owner == "me" and job.repo == "repo"
    assert job.base_branch == "main"
    assert job.clone_url.endswith("me/repo.git")


def test_labeled_with_other_label_ignored(monkeypatch):
    monkeypatch.setattr(gh, "get_settings", lambda: _settings())
    assert gh.parse_issue_event("issues", _payload(action="labeled", label="bug")) is None


def test_opened_with_label_present(monkeypatch):
    monkeypatch.setattr(gh, "get_settings", lambda: _settings())
    job = gh.parse_issue_event("issues", _payload(action="opened", labels=["ai-task"]))
    assert job is not None


def test_opened_without_label_ignored(monkeypatch):
    monkeypatch.setattr(gh, "get_settings", lambda: _settings())
    assert gh.parse_issue_event("issues", _payload(action="opened", labels=["bug"])) is None


def test_pull_request_events_ignored(monkeypatch):
    monkeypatch.setattr(gh, "get_settings", lambda: _settings())
    payload = _payload(action="labeled", label="ai-task", pr=True)
    assert gh.parse_issue_event("issues", payload) is None


def test_non_issue_event_ignored(monkeypatch):
    monkeypatch.setattr(gh, "get_settings", lambda: _settings())
    assert gh.parse_issue_event("push", {}) is None
