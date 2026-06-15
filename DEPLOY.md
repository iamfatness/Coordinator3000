# Go-Live Deployment

Two surfaces deploy differently:

| Surface | What | Where |
|---|---|---|
| **Marketing/docs site** | `site/` static assets | Cloudflare Worker → `c3000.iamfatness.us` (auto-deploys on merge — already live) |
| **The app** | FastAPI: board, agent API, MCP, autonomous engine + Postgres | A container host (this doc) → e.g. `api.c3000.iamfatness.us` |

Cloudflare Workers can't run the long-lived Python app, so the app needs a real
host + managed Postgres. The repo already ships a production `Dockerfile`.

## Required configuration (host env / secrets)
- `DATABASE_URL` — managed Postgres (Neon, Supabase, Fly Postgres, RDS…).
- `GITHUB_TOKEN` — the **one** token that commits + opens PRs.
- `GITHUB_WEBHOOK_SECRET` — for the autonomous-engine webhook.
- `ADMIN_TOKEN` — **set this** so board-admin/token-minting isn't open.
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `XAI_API_KEY` — only for the autonomous
  engine (the bring-your-own-agent board needs none).

## Path A — Fly.io (chosen)
Configs are committed: [`fly.toml`](fly.toml) (app) and
[`deploy/fly.mcp.toml`](deploy/fly.mcp.toml) (MCP server) — both build from the
existing `Dockerfile`. CI: [`.github/workflows/deploy-app.yml`](.github/workflows/deploy-app.yml)
deploys both on push to `main` once `FLY_API_TOKEN` is a repo secret.

**One-time setup**
```bash
# 1. create both apps (from the committed configs)
fly launch --no-deploy --copy-config --name coordinator3000
fly launch --no-deploy --copy-config --config deploy/fly.mcp.toml --name coordinator3000-mcp

# 2. managed Postgres, attached to BOTH apps (sets DATABASE_URL)
fly postgres create --name coordinator3000-db
fly postgres attach coordinator3000-db -a coordinator3000
fly postgres attach coordinator3000-db -a coordinator3000-mcp

# 3. secrets
fly secrets set -a coordinator3000     GITHUB_TOKEN=... ADMIN_TOKEN=... GITHUB_WEBHOOK_SECRET=...
fly secrets set -a coordinator3000-mcp GITHUB_TOKEN=...        # for submit_work

# 4. first deploy
fly deploy -c fly.toml
fly deploy -c deploy/fly.mcp.toml

# 5. custom domains + CF DNS (DNS-only CNAMEs to the .fly.dev hosts)
fly certs add -a coordinator3000     api.c3000.iamfatness.us
fly certs add -a coordinator3000-mcp mcp.c3000.iamfatness.us
```
After setup, every push to `main` redeploys via the workflow — add `FLY_API_TOKEN`
(from `fly tokens create deploy`) as a repo secret.

## Recommended path B — Cloudflare-native (keep everything on CF)
Run the container anywhere you control (VPS, home server, CI runner) and expose it
with **Cloudflare Tunnel** — no open ports, TLS handled by CF:

```bash
docker compose up -d                                # app + postgres
cloudflared tunnel create c3000
cloudflared tunnel route dns c3000 api.c3000.iamfatness.us
cloudflared tunnel run --url http://localhost:8000 c3000
```
(Cloudflare Containers, currently in beta, is the future fully-managed option.)

## After deploy — wire the integrations
- **Autonomous engine:** GitHub repo → Webhooks → `https://api.c3000.iamfatness.us/webhooks/github`, event = Issues, secret = `GITHUB_WEBHOOK_SECRET`.
- **MCP connector (Claude.ai / ChatGPT):** URL `https://mcp.c3000.iamfatness.us/mcp`, header `Authorization: Bearer c3k_<worker token>`.
- **Board:** `https://api.c3000.iamfatness.us/board` (set `ADMIN_TOKEN` first).

## Go-live checklist
- [ ] Managed Postgres provisioned; `DATABASE_URL` set.
- [ ] `ADMIN_TOKEN` set; board-admin endpoints reject unauthenticated writes.
- [ ] App reachable over HTTPS at `api.c3000.iamfatness.us`.
- [ ] MCP endpoint reachable; one real connector round-trip (claim → diff → PR).
- [ ] Webhook delivers (ping → pong) and an `ai-task` label triggers a run.
- [ ] Secrets only in the host's secret store — never committed.
