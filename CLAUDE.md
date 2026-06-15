# Coordinator3000 — working notes for agents

## What this is
An AI coordination engine with two surfaces:
- **Coordination board** (`app/store/board.py`, `app/api/`, `app/mcp_server.py`,
  `app/web/board.html`) — a Jira-like board driven by external chat-app agents
  (Claude/Grok/Codex) via REST + MCP, per-account tokens; workers submit diffs and
  Coordinator3000 opens the PRs (`app/services/submit.py`).
- **Autonomous engine** (`app/graph/`, `app/agents/`, `app/worker/`) — LangGraph
  Orchestrator→Coder→Reviewer, triggered by `ai-task`-labeled GitHub issues.

## Standing rules
- **Keep the website current.** The public site is `site/` (deployed to
  `c3000.iamfatness.us`). **Every feature add or pivot must update `site/public/`
  (landing + demo) and the `README.md` in the same change.** Treat docs/site as part
  of "done," not a follow-up.
- **Branch + PR flow.** Develop on `claude/elegant-thompson-swd74y`; commit, push,
  and open a **draft PR**. Don't push straight to `main`.
- **Deploys.** Merging to `main` triggers `.github/workflows/deploy-c3000.yml`
  (`wrangler deploy`), which needs `CLOUDFLARE_API_TOKEN` (+ DNS edit) and
  `CLOUDFLARE_ACCOUNT_ID` repo secrets. Without them the deploy step skips.
- **Models.** Default LLM is `claude-opus-4-8`; provider is pluggable
  (`anthropic`/`openai`/`xai`) per agent via `provider:model` env overrides. Never
  set `temperature`/`top_p`/`top_k` on Opus-4.x Anthropic calls (they 400).
- **Secrets.** `.env` is gitignored — never commit tokens.

## Local run / test (this repo ships with a Postgres-backed stack)
```bash
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
# Postgres: a local cluster works — pg_ctlcluster 16 main start; createdb coordinator
export DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/coordinator
uvicorn app.main:app --port 8000      # /, /board, /demo, /api/*, /agent/*
python -m app.mcp_server               # MCP server on :8001
python -m pytest -q                    # offline unit tests
```
Tables are created on startup (checkpointer + run store + board store).
