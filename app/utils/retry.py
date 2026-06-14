"""Reusable retry helpers built on tenacity.

Used to harden network-facing calls (GitHub API, git push) against transient
failures with exponential backoff + jitter.
"""
from __future__ import annotations

import logging

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

log = logging.getLogger(__name__)

# Exceptions that are worth retrying (transient network / 5xx situations).
TRANSIENT_EXCEPTIONS = (
    httpx.TransportError,
    httpx.TimeoutException,
)


def network_retry(attempts: int = 4):
    """Decorator: retry a function on transient network errors.

    Backoff: 2s, 4s, 8s, 16s (capped), with jitter. Mirrors the push/fetch
    backoff policy used throughout the project.
    """

    return retry(
        reraise=True,
        stop=stop_after_attempt(attempts),
        wait=wait_exponential_jitter(initial=2, max=16),
        retry=retry_if_exception_type(TRANSIENT_EXCEPTIONS),
        before_sleep=lambda rs: log.warning(
            "retrying after error (attempt %s/%s): %s",
            rs.attempt_number,
            attempts,
            rs.outcome.exception() if rs.outcome else "?",
        ),
    )
