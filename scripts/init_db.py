"""Create/upgrade the LangGraph checkpoint tables in Postgres.

Run once before first boot (the app also calls setup() on startup, but running
this explicitly is handy for CI / migrations):

    python -m scripts.init_db
"""
from __future__ import annotations

from langgraph.checkpoint.postgres import PostgresSaver

from app.config import get_settings


def main() -> None:
    cfg = get_settings()
    with PostgresSaver.from_conn_string(cfg.database_url) as saver:
        saver.setup()
    print("✅ checkpoint tables ready in", cfg.database_url.rsplit("@", 1)[-1])


if __name__ == "__main__":
    main()
