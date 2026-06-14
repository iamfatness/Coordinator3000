# Coordinator3000

**AI Coordination Engine** — a minimal-HITL (human-in-the-loop), autonomous
multi-agent orchestration system. Label a GitHub issue `ai-task` and Coordinator3000
clones the repo, plans the work, writes the code, reviews it, and opens a pull
request — with no human babysitting the run.

Built on **LangGraph** (stateful graph workflows + Postgres checkpointing),
deployed as a **FastAPI** app with **background workers** and **GitHub webhooks**.
Agents default to **Claude** (`claude-opus-4-8`) and can be mixed with **Grok** and
**Codex** per agent.

---

## What it does

```
 GitHub issue labeled "ai-task"
            │  (webhook)
            ▼
   FastAPI webhook endpoint ──► async job queue ──► background worker
                                                          │
                            clone repo + create branch    │
                                                          ▼
                              ┌──────────  LangGraph state machine  ──────────┐
                              │                                               │
                              │   Orchestrator ──routes──► Coder ──► Reviewer │
                              │        ▲                     │          │     │
                              │        └─────────────────────┴──────────┘     │
                              │                     │                          │
                              │                  Finalize: push branch,        │
                              │                  open PR, comment on issue     │
                              └───────────────────────────────────────────────┘
                                   (state persisted in Postgres per run)
```

* **Orchestrator** — plans the task and routes between Coder/Reviewer, with
  deterministic guards (iteration cap) that always steer toward shipping a PR.
* **Coder** — a ReAct agent with tools for files, sandboxed execution, and
  git (stage/commit). Implements the change and runs the tests.
* **Reviewer** — a ReAct agent that inspects the diff, re-runs tests/linters in
  the sandbox, and returns a structured pass/fail verdict.
* **Finalize** — pushes the branch, opens a pull request (ready-for-review when
  the automated review passed; draft otherwise), and comments on the issue.

Every run is checkpointed in Postgres, so it survives restarts and is inspectable
by `thread_id`.

---

## Project structure

```
Coordinator3000/
├── app/
│   ├── main.py                 # FastAPI app: webhook endpoint + worker lifecycle
│   ├── config.py               # Pydantic settings (all env config lives here)
│   ├── logging_config.py       # Structured logging, per-run id tagging
│   ├── models.py               # Job / RunContext dataclasses
│   ├── agents/
│   │   ├── llm.py              # Provider-pluggable chat-model factory (Claude/Grok/Codex)
│   │   ├── prompts.py          # System prompts (autonomy-tuned)
│   │   ├── orchestrator.py     # Routing decision (structured output + guards)
│   │   ├── coder.py            # Coder ReAct agent
│   │   └── reviewer.py         # Reviewer ReAct agent (+ verdict tool)
│   ├── graph/
│   │   ├── state.py            # Checkpointed TaskState
│   │   ├── builder.py          # Builds & compiles the orchestration graph
│   │   └── checkpointer.py     # AsyncPostgresSaver (pooled)
│   ├── tools/
│   │   ├── workspace.py        # Path-containment guard (safe_join)
│   │   ├── fs_tools.py         # read/write/list/delete files (workspace-scoped)
│   │   ├── sandbox.py          # run_shell / run_python (subprocess or docker)
│   │   ├── git_tools.py        # clone/branch/commit/push + agent git tools
│   │   └── github_tools.py     # GitHub REST client (issues, PRs, comments)
│   ├── webhooks/
│   │   └── github.py           # HMAC verification + issue-event parsing
│   └── worker/
│       ├── queue.py            # In-process async job queue + worker pool
│       └── runner.py           # Per-run lifecycle (clone → graph → cleanup)
├── scripts/
│   └── init_db.py              # Create LangGraph checkpoint tables
├── tests/                      # Webhook + path-guard unit tests (offline)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml          # app + postgres
├── Makefile
├── .env.example
└── README.md
```

---

## Prerequisites

* Python 3.11+ (3.12 recommended) and `git` on the host, **or** Docker.
* A **Postgres** database (the compose file provides one).
* A **GitHub token** (fine-grained PAT) with, on the target repos:
  * Contents: **Read and write** (clone + push)
  * Pull requests: **Read and write** (open PRs)
  * Issues: **Read and write** (comment / label)
* An **Anthropic API key** (and optionally OpenAI / xAI keys).
* A public HTTPS URL for GitHub to reach the webhook (e.g. a deployed host, or
  `ngrok http 8000` for local testing).

---

## Quick start (Docker Compose)

```bash
cp .env.example .env
# edit .env: GITHUB_TOKEN, GITHUB_WEBHOOK_SECRET, ANTHROPIC_API_KEY

docker compose up --build
```

This starts Postgres and the app on `http://localhost:8000`. The app creates its
checkpoint tables automatically on boot. Health check: `GET /healthz`.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # fill in secrets; point DATABASE_URL at your Postgres
python -m scripts.init_db       # create checkpoint tables (optional; app also does this)

make dev                        # uvicorn app.main:app --reload
```

---

## Connect GitHub

1. Create the trigger label once per repo: **`ai-task`** (or change `AI_TASK_LABEL`).
2. Repo → **Settings → Webhooks → Add webhook**:
   * **Payload URL:** `https://<your-host>/webhooks/github`
   * **Content type:** `application/json`
   * **Secret:** the same value as `GITHUB_WEBHOOK_SECRET`
   * **Events:** *Let me select individual events* → **Issues**
3. Open an issue describing the task and add the **`ai-task`** label (or add the
   label to an existing issue).

Coordinator3000 comments that it picked up the issue, works autonomously, and
opens a PR that closes the issue.

---

## Configuration

All configuration is environment-driven (see `.env.example`). Highlights:

| Variable | Default | Purpose |
|---|---|---|
| `GITHUB_TOKEN` | — | PAT for clone/push + REST API |
| `GITHUB_WEBHOOK_SECRET` | — | HMAC secret for webhook verification |
| `AI_TASK_LABEL` | `ai-task` | Label that triggers a run |
| `LLM_PROVIDER` / `LLM_MODEL` | `anthropic` / `claude-opus-4-8` | Default AI for all agents |
| `ORCHESTRATOR_MODEL` / `CODER_MODEL` / `REVIEWER_MODEL` | — | Per-agent override (`provider:model`) |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `XAI_API_KEY` | — | Provider keys |
| `DATABASE_URL` | local pg | Postgres for the checkpointer |
| `MAX_ITERATIONS` | `4` | Coder⇄Reviewer rounds before shipping |
| `WORKER_CONCURRENCY` | `2` | Parallel autonomous runs |
| `REQUIRE_HUMAN_APPROVAL` | `false` | When true, PRs open as drafts |
| `SANDBOX_MODE` | `subprocess` | `subprocess` or `docker` code execution |
| `SANDBOX_TIMEOUT` | `300` | Per-command wall-clock limit (seconds) |
| `WORKSPACE_ROOT` | `/tmp/coordinator-workspaces` | Where repos are cloned |

### Using Claude, Grok, and Codex together

Every agent is built through one provider-pluggable factory, so you can assign
each agent to whichever AI suits it. Claude is the default; mix in the others via
per-role overrides:

```bash
# Plan + review with Claude, write code with Codex, sanity-check with Grok:
ORCHESTRATOR_MODEL=anthropic:claude-opus-4-8
CODER_MODEL=openai:gpt-5-codex
REVIEWER_MODEL=xai:grok-4
```

Uncomment `langchain-openai` / `langchain-xai` in `requirements.txt` for the
providers you use (they're imported lazily, so a Claude-only deploy needs neither).

---

## Minimal-HITL behavior

The system is tuned to run end-to-end without a human in the loop:

* Agents never pause to ask the human questions mid-run; they make the reasonable
  call and proceed.
* The orchestrator always prefers **opening a PR** over abandoning a task.
* The only optional human gate is `REQUIRE_HUMAN_APPROVAL=true`, which opens PRs
  as **drafts** for a human to promote — the run still completes autonomously.
* A human reviews/merges the PR. Coordinator3000 never auto-merges.

---

## Security notes

This system runs model-authored code. Treat it accordingly:

* **Filesystem containment** — all file/shell tools resolve paths through
  `safe_join`, which refuses any path that escapes the run's cloned workspace.
* **Sandboxed execution** — `SANDBOX_MODE=subprocess` pins the cwd to the
  workspace with a scrubbed environment and a hard timeout. For less-trusted
  input, set `SANDBOX_MODE=docker` to run with `--network none`, dropped
  capabilities, and memory/pid limits. For hostile input, layer on stronger
  isolation (gVisor / Firecracker / a disposable build VM).
* **Secret hygiene** — the GitHub token is injected into the remote URL only at
  clone/push time and never written to `.git/config`, keeping it out of the
  workspace that sandboxed code can read. LLM keys live only in the app process.
* **Webhook authenticity** — every delivery is HMAC-verified against
  `GITHUB_WEBHOOK_SECRET`.
* Run the container as the provided non-root user and scope the GitHub PAT to the
  specific repositories you want automated.

---

## Reliability

* **Retries + backoff** — GitHub API calls and `git push` retry on transient
  failures with exponential backoff + jitter (2s → 4s → 8s → 16s, via tenacity).
* **Error handling** — a failing run posts the error back to the issue and is
  isolated so it never takes down a worker.
* **Durable state** — LangGraph Postgres checkpoints persist each run's state;
  inspect or resume by `thread_id`.
* **Logging** — structured, per-run-id-tagged logs across the API, workers, and
  agent/tool layers (`LOG_LEVEL`).

---

## Testing

```bash
make test        # offline unit tests: webhook parsing/verification + path guard
```

---

## Deploy notes

* Build the image (`docker build -t coordinator3000 .`) and run it behind HTTPS
  with `DATABASE_URL` pointing at a managed Postgres.
* Mount a writable volume at `WORKSPACE_ROOT` (the compose file does this).
* Scale autonomous throughput with `WORKER_CONCURRENCY`; the Postgres pool sizes
  itself to `max(4, 2 × concurrency)`.
* The in-process queue is simple and resets on restart. For cross-process
  durability or horizontal scale, swap `app/worker/queue.py` for Redis/Celery/SQS
  — the rest of the pipeline is unchanged.

---

## License

See repository.
