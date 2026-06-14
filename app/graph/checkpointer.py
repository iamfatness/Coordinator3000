"""Postgres checkpointer for LangGraph.

Backs the durable state machine with Postgres so a run survives restarts and can
be inspected/resumed by `thread_id`. Uses a connection pool so multiple
concurrent runs don't contend on a single connection.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger(__name__)


@asynccontextmanager
async def open_checkpointer(database_url: str, max_size: int = 10):
    """Async context manager yielding a ready-to-use AsyncPostgresSaver.

    Calls `setup()` once to create/upgrade the checkpoint tables. The pool stays
    open for the lifetime of the `async with` block (the FastAPI app lifespan).
    """
    pool = AsyncConnectionPool(
        conninfo=database_url,
        max_size=max_size,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open()
    try:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()
        log.info("postgres checkpointer ready (pool max_size=%d)", max_size)
        yield saver
    finally:
        await pool.close()
        log.info("postgres checkpointer pool closed")
