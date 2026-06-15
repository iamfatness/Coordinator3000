"""Board store — the Jira-like coordination layer (Postgres-backed).

Projects -> Goals (epics) -> Tasks, plus Notes and Accounts. Worker agents
(regular Claude / Grok / Codex chat apps, authenticated by a per-account token)
pull outstanding work for a goal, atomically claim a task, submit a diff, and
leave coordination notes. File-overlap conflict detection flags when two active
tasks touch the same paths.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from contextlib import asynccontextmanager

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

log = logging.getLogger(__name__)

ACTIVE_STATUSES = ("claimed", "in_progress", "in_review")

_DDL = (
    """
    CREATE TABLE IF NOT EXISTS c3k_accounts (
        id          BIGSERIAL PRIMARY KEY,
        name        TEXT UNIQUE NOT NULL,
        kind        TEXT NOT NULL DEFAULT 'agent',
        token_sha   TEXT NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS c3k_projects (
        id          BIGSERIAL PRIMARY KEY,
        key         TEXT UNIQUE NOT NULL,
        name        TEXT NOT NULL,
        repo_owner  TEXT NOT NULL,
        repo_name   TEXT NOT NULL,
        base_branch TEXT NOT NULL DEFAULT 'main',
        task_seq    INTEGER NOT NULL DEFAULT 0,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS c3k_goals (
        id          BIGSERIAL PRIMARY KEY,
        project_id  BIGINT NOT NULL REFERENCES c3k_projects(id) ON DELETE CASCADE,
        key         TEXT UNIQUE NOT NULL,
        title       TEXT NOT NULL,
        description TEXT DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'open',
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS c3k_tasks (
        id          BIGSERIAL PRIMARY KEY,
        project_id  BIGINT NOT NULL REFERENCES c3k_projects(id) ON DELETE CASCADE,
        goal_id     BIGINT REFERENCES c3k_goals(id) ON DELETE SET NULL,
        key         TEXT UNIQUE NOT NULL,
        title       TEXT NOT NULL,
        description TEXT DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'backlog',
        priority    INTEGER NOT NULL DEFAULT 2,
        assignee    BIGINT REFERENCES c3k_accounts(id) ON DELETE SET NULL,
        blocked_by  TEXT[] NOT NULL DEFAULT '{}',
        files       TEXT[] NOT NULL DEFAULT '{}',
        branch      TEXT,
        pr_url      TEXT,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS c3k_notes (
        id          BIGSERIAL PRIMARY KEY,
        task_id     BIGINT REFERENCES c3k_tasks(id) ON DELETE CASCADE,
        goal_id     BIGINT REFERENCES c3k_goals(id) ON DELETE CASCADE,
        account_id  BIGINT REFERENCES c3k_accounts(id) ON DELETE SET NULL,
        kind        TEXT NOT NULL DEFAULT 'note',
        body        TEXT NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS c3k_tasks_goal_idx ON c3k_tasks (goal_id)",
    "CREATE INDEX IF NOT EXISTS c3k_notes_task_idx ON c3k_notes (task_id)",
    # Migrations (idempotent) — token lifecycle + claim TTL.
    "ALTER TABLE c3k_accounts ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ",
    "ALTER TABLE c3k_accounts ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'write'",
    "ALTER TABLE c3k_tasks ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ",
    # Phase 2 — activity feed + labels.
    "ALTER TABLE c3k_tasks ADD COLUMN IF NOT EXISTS labels TEXT[] NOT NULL DEFAULT '{}'",
    """
    CREATE TABLE IF NOT EXISTS c3k_events (
        id          BIGSERIAL PRIMARY KEY,
        type        TEXT NOT NULL,
        account_id  BIGINT REFERENCES c3k_accounts(id) ON DELETE SET NULL,
        task_key    TEXT,
        goal_key    TEXT,
        detail      TEXT NOT NULL DEFAULT '',
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS c3k_events_created_idx ON c3k_events (created_at DESC)",
    # Phase 2 — definition of done (acceptance criteria).
    "ALTER TABLE c3k_goals ADD COLUMN IF NOT EXISTS acceptance TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE c3k_tasks ADD COLUMN IF NOT EXISTS acceptance TEXT NOT NULL DEFAULT ''",
)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class BoardError(RuntimeError):
    pass


class Conflict(BoardError):
    """Raised when a claim cannot proceed (already taken / blocked / missing)."""


class BoardStore:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            for stmt in _DDL:
                await conn.execute(stmt)
        log.info("board store ready")

    # ---- accounts -----------------------------------------------------------
    async def create_account(
        self, name: str, kind: str = "agent", scope: str = "write"
    ) -> tuple[dict, str]:
        token = "c3k_" + secrets.token_urlsafe(28)
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "INSERT INTO c3k_accounts (name, kind, token_sha, scope) "
                    "VALUES (%s, %s, %s, %s) RETURNING id, name, kind, scope, created_at",
                    (name, kind, _hash_token(token), scope),
                )
                account = await cur.fetchone()
        return account, token

    async def account_by_token(self, token: str) -> dict | None:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT id, name, kind, scope, created_at FROM c3k_accounts "
                    "WHERE token_sha = %s AND revoked_at IS NULL",
                    (_hash_token(token),),
                )
                return await cur.fetchone()

    async def list_accounts(self) -> list[dict]:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT id, name, kind, scope, created_at, revoked_at "
                    "FROM c3k_accounts ORDER BY id"
                )
                return list(await cur.fetchall())

    async def revoke_account(self, account_id: int) -> dict:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "UPDATE c3k_accounts SET revoked_at = now() WHERE id = %s "
                    "RETURNING id, name, kind, scope, revoked_at",
                    (account_id,),
                )
                account = await cur.fetchone()
        if not account:
            raise BoardError(f"unknown account {account_id}")
        return account

    async def rotate_account(self, account_id: int) -> tuple[dict, str]:
        token = "c3k_" + secrets.token_urlsafe(28)
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "UPDATE c3k_accounts SET token_sha = %s, revoked_at = NULL WHERE id = %s "
                    "RETURNING id, name, kind, scope",
                    (_hash_token(token), account_id),
                )
                account = await cur.fetchone()
        if not account:
            raise BoardError(f"unknown account {account_id}")
        return account, token

    # ---- projects / goals ---------------------------------------------------
    async def create_project(
        self, key: str, name: str, repo_owner: str, repo_name: str, base_branch: str = "main"
    ) -> dict:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "INSERT INTO c3k_projects (key, name, repo_owner, repo_name, base_branch) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING *",
                    (key.upper(), name, repo_owner, repo_name, base_branch),
                )
                return await cur.fetchone()

    async def list_projects(self) -> list[dict]:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT * FROM c3k_projects ORDER BY key")
                return list(await cur.fetchall())

    async def project_by_id(self, project_id: int) -> dict | None:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT * FROM c3k_projects WHERE id = %s", (project_id,))
                return await cur.fetchone()

    async def _project_by_key(self, conn, key: str) -> dict | None:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM c3k_projects WHERE key = %s", (key.upper(),))
            return await cur.fetchone()

    async def create_goal(
        self, project_key: str, key: str, title: str, description: str = "", acceptance: str = ""
    ) -> dict:
        async with self._pool.connection() as conn:
            project = await self._project_by_key(conn, project_key)
            if not project:
                raise BoardError(f"unknown project {project_key!r}")
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "INSERT INTO c3k_goals (project_id, key, title, description, acceptance) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING *",
                    (project["id"], key.upper(), title, description, acceptance),
                )
                return await cur.fetchone()

    async def list_goals(self, project_key: str | None = None) -> list[dict]:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                if project_key:
                    project = await self._project_by_key(conn, project_key)
                    await cur.execute(
                        "SELECT * FROM c3k_goals WHERE project_id = %s ORDER BY id",
                        (project["id"] if project else -1,),
                    )
                else:
                    await cur.execute("SELECT * FROM c3k_goals ORDER BY id")
                return list(await cur.fetchall())

    # ---- tasks --------------------------------------------------------------
    async def create_task(
        self,
        goal_key: str,
        title: str,
        description: str = "",
        priority: int = 2,
        files: list[str] | None = None,
        blocked_by: list[str] | None = None,
        labels: list[str] | None = None,
        acceptance: str = "",
    ) -> dict:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT * FROM c3k_goals WHERE key = %s", (goal_key.upper(),))
                goal = await cur.fetchone()
                if not goal:
                    raise BoardError(f"unknown goal {goal_key!r}")
                # Per-project task number.
                await cur.execute(
                    "UPDATE c3k_projects SET task_seq = task_seq + 1 WHERE id = %s "
                    "RETURNING key, task_seq",
                    (goal["project_id"],),
                )
                proj = await cur.fetchone()
                task_key = f"{proj['key']}-{proj['task_seq']}"
                await cur.execute(
                    "INSERT INTO c3k_tasks (project_id, goal_id, key, title, description, "
                    "priority, files, blocked_by, labels, acceptance) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                    (
                        goal["project_id"], goal["id"], task_key, title, description,
                        priority, files or [], [b.upper() for b in (blocked_by or [])],
                        labels or [], acceptance,
                    ),
                )
                return await cur.fetchone()

    async def _task_by_key(self, conn, key: str) -> dict | None:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM c3k_tasks WHERE key = %s", (key.upper(),))
            return await cur.fetchone()

    async def get_task(self, key: str) -> dict | None:
        async with self._pool.connection() as conn:
            task = await self._task_by_key(conn, key)
            if not task:
                return None
            task["notes"] = await self._notes_for(conn, task["id"])
            task["conflicts"] = [t["key"] for t in await self._overlaps(conn, task)]
            if task.get("goal_id"):
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "SELECT key, acceptance FROM c3k_goals WHERE id = %s", (task["goal_id"],)
                    )
                    goal = await cur.fetchone()
                if goal:
                    task["goal_key"] = goal["key"]
                    task["goal_acceptance"] = goal["acceptance"]
            return task

    async def list_work(self, goal_key: str) -> dict:
        """Outstanding (backlog, unblocked) tasks for a goal, best-first."""
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT * FROM c3k_goals WHERE key = %s", (goal_key.upper(),))
                goal = await cur.fetchone()
                if not goal:
                    raise BoardError(f"unknown goal {goal_key!r}")
                await cur.execute(
                    "SELECT * FROM c3k_tasks WHERE goal_id = %s AND status = 'backlog' "
                    "ORDER BY priority DESC, id ASC",
                    (goal["id"],),
                )
                tasks = list(await cur.fetchall())
                # done set, to evaluate blocked_by
                await cur.execute(
                    "SELECT key FROM c3k_tasks WHERE goal_id = %s AND status = 'done'",
                    (goal["id"],),
                )
                done = {r["key"] for r in await cur.fetchall()}
            ready = [t for t in tasks if all(b in done for b in t["blocked_by"])]
            blocked = [t for t in tasks if t not in ready]
            return {"goal": goal, "ready": ready, "blocked": blocked}

    async def claim_task(self, key: str, account_id: int) -> dict:
        """Atomically claim a backlog task; return task + conflict task keys."""
        async with self._pool.connection() as conn:
            task = await self._task_by_key(conn, key)
            if not task:
                raise BoardError(f"unknown task {key!r}")
            # Enforce blocked_by.
            if task["blocked_by"]:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "SELECT key FROM c3k_tasks WHERE key = ANY(%s) AND status <> 'done'",
                        (task["blocked_by"],),
                    )
                    open_blockers = [r["key"] for r in await cur.fetchall()]
                if open_blockers:
                    raise Conflict(f"task {key} is blocked by {', '.join(open_blockers)}")
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "UPDATE c3k_tasks SET status='in_progress', assignee=%s, "
                    "claimed_at=now(), updated_at=now() "
                    "WHERE key=%s AND status='backlog' RETURNING *",
                    (account_id, key.upper()),
                )
                claimed = await cur.fetchone()
            if not claimed:
                raise Conflict(f"task {key} is not available to claim (already taken?)")
            overlaps = await self._overlaps(conn, claimed)
            if overlaps:
                names = ", ".join(t["key"] for t in overlaps)
                await self._add_note(
                    conn, claimed["id"], None, account_id, "conflict",
                    f"File overlap with active task(s): {names}. Coordinate before committing.",
                )
                for other in overlaps:
                    await self._add_note(
                        conn, other["id"], None, account_id, "conflict",
                        f"Task {claimed['key']} was claimed and overlaps your files.",
                    )
            claimed["conflicts"] = [t["key"] for t in overlaps]
            return claimed

    async def submit_task(self, key: str, branch: str, pr_url: str) -> dict:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "UPDATE c3k_tasks SET status='in_review', branch=%s, pr_url=%s, "
                    "updated_at=now() WHERE key=%s RETURNING *",
                    (branch, pr_url, key.upper()),
                )
                task = await cur.fetchone()
            if not task:
                raise BoardError(f"unknown task {key!r}")
            return task

    async def set_status(self, key: str, status: str, account_id: int | None = None) -> dict:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                if status == "backlog":
                    await cur.execute(
                        "UPDATE c3k_tasks SET status='backlog', assignee=NULL, updated_at=now() "
                        "WHERE key=%s RETURNING *", (key.upper(),))
                else:
                    await cur.execute(
                        "UPDATE c3k_tasks SET status=%s, updated_at=now() WHERE key=%s RETURNING *",
                        (status, key.upper()))
                task = await cur.fetchone()
            if not task:
                raise BoardError(f"unknown task {key!r}")
            return task

    async def release_stale(self, ttl_seconds: int) -> list[str]:
        """Return in-progress tasks claimed longer than `ttl_seconds` to backlog.

        Prevents a stalled worker from locking a task forever. Adds a note to each
        released task. Returns the released task keys.
        """
        if ttl_seconds < 0:
            return []
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "UPDATE c3k_tasks SET status='backlog', assignee=NULL, "
                    "claimed_at=NULL, updated_at=now() "
                    "WHERE status='in_progress' AND claimed_at IS NOT NULL "
                    "AND claimed_at < now() - make_interval(secs => %s) "
                    "RETURNING id, key",
                    (ttl_seconds,),
                )
                released = list(await cur.fetchall())
            for row in released:
                await self._add_note(
                    conn, row["id"], None, None, "note",
                    f"Auto-released to backlog: claim exceeded the {ttl_seconds}s TTL.",
                )
                await conn.execute(
                    "INSERT INTO c3k_events (type, task_key, detail) VALUES (%s,%s,%s)",
                    ("auto_released", row["key"], f"claim exceeded {ttl_seconds}s TTL"),
                )
        return [r["key"] for r in released]

    async def add_note(self, task_key: str, account_id: int | None, body: str, kind: str = "note") -> dict:
        async with self._pool.connection() as conn:
            task = await self._task_by_key(conn, task_key)
            if not task:
                raise BoardError(f"unknown task {task_key!r}")
            return await self._add_note(conn, task["id"], None, account_id, kind, body)

    # ---- activity feed ------------------------------------------------------
    async def record_event(
        self, type_: str, account_id: int | None = None,
        task_key: str | None = None, goal_key: str | None = None, detail: str = "",
    ) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO c3k_events (type, account_id, task_key, goal_key, detail) "
                "VALUES (%s,%s,%s,%s,%s)",
                (type_, account_id, task_key, goal_key, (detail or "")[:500]),
            )

    async def list_events(self, limit: int = 100) -> list[dict]:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT e.id, e.type, e.task_key, e.goal_key, e.detail, e.created_at, "
                    "a.name AS account FROM c3k_events e "
                    "LEFT JOIN c3k_accounts a ON a.id = e.account_id "
                    "ORDER BY e.id DESC LIMIT %s",
                    (limit,),
                )
                return list(await cur.fetchall())

    # ---- board view ---------------------------------------------------------
    async def board(self) -> dict:
        async with self._pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT * FROM c3k_projects ORDER BY key")
                projects = list(await cur.fetchall())
                await cur.execute("SELECT * FROM c3k_goals ORDER BY id")
                goals = list(await cur.fetchall())
                await cur.execute(
                    "SELECT t.*, a.name AS assignee_name FROM c3k_tasks t "
                    "LEFT JOIN c3k_accounts a ON a.id = t.assignee ORDER BY t.priority DESC, t.id"
                )
                tasks = list(await cur.fetchall())
        return {"projects": projects, "goals": goals, "tasks": tasks}

    # ---- internals ----------------------------------------------------------
    async def _overlaps(self, conn, task: dict) -> list[dict]:
        if not task["files"]:
            return []
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM c3k_tasks WHERE id <> %s AND status = ANY(%s) AND files && %s",
                (task["id"], list(ACTIVE_STATUSES), task["files"]),
            )
            return list(await cur.fetchall())

    async def _notes_for(self, conn, task_id: int) -> list[dict]:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT n.id, n.kind, n.body, n.created_at, a.name AS author "
                "FROM c3k_notes n LEFT JOIN c3k_accounts a ON a.id = n.account_id "
                "WHERE n.task_id = %s ORDER BY n.id", (task_id,))
            return list(await cur.fetchall())

    async def _add_note(self, conn, task_id, goal_id, account_id, kind, body) -> dict:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "INSERT INTO c3k_notes (task_id, goal_id, account_id, kind, body) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id, kind, body, created_at",
                (task_id, goal_id, account_id, kind, body))
            return await cur.fetchone()


@asynccontextmanager
async def open_board_store(database_url: str, max_size: int = 5):
    pool = AsyncConnectionPool(
        conninfo=database_url, max_size=max_size, open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    await pool.open()
    try:
        store = BoardStore(pool)
        await store.setup()
        yield store
    finally:
        await pool.close()
