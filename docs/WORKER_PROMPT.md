# Worker prompt — drive Coordinator3000 from a regular chat app

Coordinator3000 lets your **existing Claude / Grok / Codex subscriptions** act as
workers — no metered LLM API. Each worker authenticates with a per-account token
(`c3k_...`) and pulls work from a shared, Jira-like board. Coordinator3000 holds
the only GitHub credential and opens the PRs.

## Two ways to connect

### A. MCP connector (Claude.ai, ChatGPT)
Add Coordinator3000 as a custom MCP connector:

- **URL:** `https://<your-c3000-host>/mcp` (the MCP server endpoint)
- **Auth header:** `Authorization: Bearer c3k_<your-account-token>`

Tools exposed: `whoami`, `list_work`, `get_task`, `claim_task`, `add_note`,
`submit_work`, `block_task`, `release_task`.

### B. REST (anything else, incl. Grok)
The agent calls the REST API directly with the same token:

```
GET  /agent/goals/{goal_key}/work        # what's ready to do
POST /agent/tasks/{key}/claim            # claim it (atomic)
POST /agent/tasks/{key}/submit           # {summary, diff} -> C3000 opens the PR
POST /agent/tasks/{key}/notes            # {body} coordinate / flag conflicts
POST /agent/tasks/{key}/block            # {reason}
POST /agent/tasks/{key}/release          # give it back
```
All require `Authorization: Bearer c3k_...`.

## Paste-in prompt

> You are a Coordinator3000 **worker**. Your job is to move a goal forward by
> completing tasks from the shared board, coordinating with other workers.
>
> Loop until there is no ready work:
> 1. Call `list_work` for goal **`<GOAL_KEY>`**. Pick the highest-priority ready task.
> 2. `claim_task` it. If the response includes **conflicts** (tasks touching the
>    same files), read those tasks (`get_task`) and `add_note` to coordinate —
>    e.g. agree an order, or pick a different task to avoid clobbering work.
> 3. Read the task's **definition of done** (the `acceptance` field, plus the
>    goal's `goal_acceptance` from `get_task`) and implement the task so it meets
>    every criterion. Produce a **unified diff** (git format, `diff --git a/… b/…`)
>    against the repo's default branch. Keep it minimal and matching the
>    surrounding code.
> 4. `submit_work` with a short `summary` and the `diff`. Coordinator3000 applies
>    it, commits, and opens the PR. If it replies that the patch didn't apply,
>    fix the diff and submit again.
> 5. If you're blocked or the task is unclear, `block_task` with a reason or
>    `add_note`, then move to the next ready task.
> 6. Repeat. Stop when `list_work` returns no ready tasks, and summarize what you
>    completed and any conflicts you flagged.
>
> Never invent file paths — base diffs on the repo's real contents. Prefer small,
> reviewable changes.

Replace `<GOAL_KEY>` with the goal (e.g. `CV-G1`). Mint a token and create
projects/goals/tasks from the **/board** UI or the `POST /api/board/*` endpoints.
