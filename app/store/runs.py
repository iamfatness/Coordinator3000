"""Postgres-backed registry of runs, powering the management UI.

The LangGraph checkpointer persists the *graph* state keyed by thread_id, but
it's not convenient to enumerate or summarize for a dashboard. This lightweight
`coordinator_runs` table gives the UI a flat, queryable view: one row per run,
updated live as the orchestration graph streams through its nodes.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger(__name__)

# Separate statements — psycopg's execute() prepares each statement and cannot
# run multiple commands in one call.
_DDL = (
    """
    CREATE TABLE IF NOT EXISTS coordinator_runs (
        run_id        TEXT PRIMARY KEY,
        owner         TEXT NOT NULL,
        repo          TEXT NOT NULL,
        issue_number  INTEGER NOT NULL,
        issue_title   TEXT,
        branch        TEXT,
        status        TEXT NOT NULL DEFAULT 'queued',
        phase         TEXT,
        pr_url        TEXT,
        error         TEXT,
        plan          TEXT,
        coder_report  TEXT,
        review_report TEXT,
        review_passed BOOLEAN,
        iterations    INTEGER NOT NULL DEFAULT 0,
        trigger       TEXT NOT NULL DEFAULT 'webhook',
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS coordinator_runs_created_idx "
    "ON coordinator_runs (created_at DESC)",
)

# Columns the worker is allowed to update as a run progresses.
_UPDATABLE = {
    "branch", "status", "phase", "pr_url", "error",
    "plan", "coder_report", "review_report", "review_passed", "iterations",
}


class RunStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            for stmt in _DDL:
                await conn.execute(stmt)
        log.info("run store ready")

    async def create(
        self,
        *,
        run_id: str,
        owner: str,
        repo: str,
        issue_number: int,
        issue_title: str,
        branch: str = "",
        trigger: str = "webhook",
        status: str = "running",
    ) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO coordinator_runs
                    (run_id, owner, repo, issue_number, issue_title, branch, status, trigger)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE
                    SET status = EXCLUDED.status, branch = EXCLUDED.branch,
                        updated_at = now()
                """,
                (run_id, owner, repo, issue_number, issue_title, branch, status, trigger),
            )

    async def update(self, run_id: str, **fields) -> None:
        cols = {k: v for k, v in fields.items() if k in _UPDATABLE}
        set_sql = ", ".join(f"{k} = %s" for k in cols)
        set_sql = f"{set_sql + ', ' if set_sql else ''}updated_at = now()"
        params = [*cols.values(), run_id]
        async with self._pool.connection() as conn:
            await conn.execute(
                f"UPDATE coordinator_runs SET {set_sql} WHERE run_id = %s", params
            )

    async def get(self, run_id: str) -> dict | None:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT * FROM coordinator_runs WHERE run_id = %s", (run_id,)
                )
                return await cur.fetchone()

    async def list(self, limit: int = 100) -> list[dict]:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT run_id, owner, repo, issue_number, issue_title, branch, "
                    "status, phase, pr_url, review_passed, iterations, trigger, "
                    "created_at, updated_at "
                    "FROM coordinator_runs ORDER BY created_at DESC LIMIT %s",
                    (limit,),
                )
                return list(await cur.fetchall())


@asynccontextmanager
async def open_run_store(database_url: str, max_size: int = 5):
    pool = AsyncConnectionPool(
        conninfo=database_url,
        max_size=max_size,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open()
    try:
        store = RunStore(pool)
        await store.setup()
        yield store
    finally:
        await pool.close()
