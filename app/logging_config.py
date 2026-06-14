"""Logging setup.

A single `configure_logging()` call wires up a consistent, timestamped format
across uvicorn, the workers, and the agent/tool layers. Each run is tagged with
its `run_id` via a logging filter so concurrent autonomous runs stay legible.
"""
from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

_run_id: ContextVar[str] = ContextVar("run_id", default="-")


def set_run_id(run_id: str) -> None:
    """Bind a run id to the current context so log lines carry it."""
    _run_id.set(run_id)


class _RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.run_id = _run_id.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s [%(run_id)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    handler.addFilter(_RunIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Quiet down noisy third-party loggers.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
