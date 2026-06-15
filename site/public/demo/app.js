"use strict";

// ---- mock data (static demo, no backend) -----------------------------------
const RUNS = [
  { id:"a91f3c0e", owner:"iamfatness", repo:"CoreVideo", issue:142, title:"Add HLS output toggle to the streaming panel",
    status:"completed", iter:2, duration:"6m 12s", trigger:"webhook",
    coder:"claude", reviewer:"claude", review_passed:true, pr:"#218", pr_url:"#",
    steps:["done","done","done","done"],
    plan:"Add an `hls_enabled` flag to the output config, surface a toggle in the streaming panel, thread it through the native-core command, and cover it with a renderer + native test.",
    changes:"4 files changed (+118 -9): src/output/config.ts, src/panels/StreamingPanel.tsx, native-core/commands.ts, tests/output.test.ts. Added HLS toggle wired through the typed command boundary; all 37 tests green.",
    diff:[["ctx"," src/panels/StreamingPanel.tsx"],["add","+ <Toggle label=\"HLS output\" checked={cfg.hlsEnabled}"],["add","+   onChange={v => send({type:'set_hls', enabled:v})} />"],["ctx","  src/output/config.ts"],["add","+ hlsEnabled: boolean;"]],
    review:"Approved. Toggle is correctly debounced, the native command is covered, and the snapshot round-trips. Matches existing panel conventions.",
    required:"",
    timeline:[
      ["Orchestrator","23:41:02","Planned 4-step change; routed to Coder"],
      ["Coder","23:41:48","Read 6 files, edited 4, ran `npm test` -> 37 passed"],
      ["Coder","23:43:10","Committed: feat(output): add HLS toggle"],
      ["Orchestrator","23:43:12","Routed to Reviewer"],
      ["Reviewer","23:44:30","Ran tests + lint, inspected diff -> approved"],
      ["Finalize","23:45:01","Pushed branch, opened PR #218, commented on issue"]],
    logs:"INFO clone iamfatness/CoreVideo (main)\nINFO branch ai-task/issue-142-add-hls-output-toggle\nINFO coder: npm test -> 37 passed\nINFO reviewer: verdict approved\nINFO opened PR #218 (draft=false)" },

  { id:"7d2b14aa", owner:"iamfatness", repo:"resonance", issue:88, title:"Fix audio buffer underrun on device switch",
    status:"running", iter:1, duration:"2m 03s", trigger:"manual",
    coder:"grok", reviewer:"claude", review_passed:null, pr:null, pr_url:null,
    steps:["done","active","todo","todo"],
    plan:"Reproduce the underrun on output-device change, add a ring-buffer prefill on the audio engine restart path, and add a regression test around the device-switch transition.",
    changes:"In progress - Coder is editing engine/audio_stream.cpp and running the test harness.",
    diff:[["ctx"," engine/audio_stream.cpp"],["del","- restart_stream();"],["add","+ prefill_ring_buffer();"],["add","+ restart_stream();"]],
    review:"-", required:"",
    timeline:[
      ["Orchestrator","01:03:40","Planned 3-step fix; routed to Coder"],
      ["Coder","01:04:18","Reproduced underrun via test harness"],
      ["Coder","01:05:02","Editing engine/audio_stream.cpp ..."]],
    logs:"INFO clone iamfatness/resonance (main)\nINFO branch ai-task/issue-88-fix-audio-buffer-underrun\nINFO coder: running device-switch repro ..." },

  { id:"c5e9f7b1", owner:"iamfatness", repo:"CoreVideoPro", issue:57, title:"Wire chroma key strength into the native core",
    status:"needs_human", iter:4, duration:"11m 49s", trigger:"webhook",
    coder:"claude", reviewer:"claude", review_passed:false, pr:"#94 (draft)", pr_url:"#",
    steps:["done","done","done","done"],
    plan:"Thread a `chromaStrength` float through the renderer->native-core command/snapshot protocol with a paired test at each layer.",
    changes:"6 files changed (+204 -21). Renderer + command wired; native model added. One snapshot test still failing on clamp bounds after 4 iterations.",
    diff:[["ctx"," native-core/chroma.ts"],["add","+ clampStrength(v) { return Math.min(1, Math.max(0, v)); }"],["del","- this.strength = v;"],["add","+ this.strength = clampStrength(v);"]],
    review:"Not approved after 4 iterations. Clamp logic added but `chroma.snapshot.test.ts` still fails at the upper bound (1.0 maps to 0.99). Opened as a draft for a human to finish.",
    required:"Fix the off-by-epsilon in the snapshot serializer so strength=1.0 round-trips exactly.",
    timeline:[
      ["Orchestrator","00:50:10","Planned; routed to Coder"],
      ["Coder","00:52:31","Wired command + snapshot (iter 1)"],
      ["Reviewer","00:54:02","Rejected: missing clamp"],
      ["Coder","00:57:20","Added clamp (iter 2-4)"],
      ["Reviewer","01:00:55","Still failing upper-bound test"],
      ["Finalize","01:01:59","Max iterations hit -> opened draft PR #94 for human"]],
    logs:"WARN reviewer: chroma.snapshot.test.ts FAILED (1.0 -> 0.99)\nINFO max iterations (4) reached -> finalize\nINFO opened PR #94 (draft=true)" },

  { id:"e0aa28d4", owner:"iamfatness", repo:"IamfatnessWebsite", issue:12, title:"Migrate site worker to new wrangler config",
    status:"failed", iter:1, duration:"0m 51s", trigger:"manual",
    coder:"codex", reviewer:"claude", review_passed:null, pr:null, pr_url:null,
    steps:["done","active","todo","todo"],
    plan:"Update wrangler.jsonc to the v4 schema and adjust the worker entrypoint.",
    changes:"Run failed before completing.", diff:[], review:"-", required:"",
    timeline:[
      ["Orchestrator","23:12:01","Planned; routed to Coder"],
      ["Coder","23:12:40","npm install failed: registry timeout"],
      ["System","23:12:52","Run errored - posted failure comment to issue #12"]],
    logs:"ERROR sandbox: npm install exited 1 (ETIMEDOUT registry.npmjs.org)\nERROR run e0aa28d4 failed\nINFO posted failure comment to issue #12" },

  { id:"b3140a9c", owner:"iamfatness", repo:"Coordinator3000", issue:3, title:"Add GET /version endpoint returning app version",
    status:"completed", iter:1, duration:"3m 27s", trigger:"manual",
    coder:"codex", reviewer:"grok", review_passed:true, pr:"#4", pr_url:"#",
    steps:["done","done","done","done"],
    plan:"Add a small FastAPI route returning {version}. One file, one test.",
    changes:"2 files changed (+14): app/main.py (new /version route), tests/test_version.py. Test passes.",
    diff:[["ctx"," app/main.py"],["add","+ @app.get('/version')"],["add","+ async def version(): return {'version': __version__}"]],
    review:"Approved. Minimal, matches existing route style, test covers it.", required:"",
    timeline:[
      ["Orchestrator","00:31:05","Planned 1-step change; routed to Coder"],
      ["Coder","00:32:10","Added route + test, pytest green"],
      ["Reviewer","00:33:40","Approved"],
      ["Finalize","00:34:32","Opened PR #4"]],
    logs:"INFO coder: pytest -> 1 passed\nINFO reviewer(grok): approved\nINFO opened PR #4 (draft=false)" },

  { id:"f8c61d22", owner:"iamfatness", repo:"CoreVideo", issue:150, title:"Add SRT ingest source",
    status:"queued", iter:0, duration:"-", trigger:"webhook",
    coder:"claude", reviewer:"claude", review_passed:null, pr:null, pr_url:null,
    steps:["todo","todo","todo","todo"],
    plan:"-", changes:"Waiting for an available worker.", diff:[], review:"-", required:"",
    timeline:[["Queue","01:05:00","Queued behind 1 running job"]],
    logs:"INFO enqueued run f8c61d22 for iamfatness/CoreVideo#150" },
];

const METRICS = [
  {v:"1", l:"Active runs", s:"<span class='muted'>1 queued</span>"},
  {v:"3", l:"Completed &middot; 24h", s:"<span class='up'>&#9650; 2 vs prev</span>"},
  {v:"4", l:"PRs opened", s:"<span class='muted'>1 draft</span>"},
  {v:"75%", l:"Auto-merge rate", s:"<span class='down'>&#9660; review caught 1</span>"},
  {v:"2.2", l:"Avg iterations", s:"<span class='muted'>coder&harr;reviewer</span>"},
  {v:"$14.20", l:"LLM spend &middot; 24h", s:"<span class='muted'>1.84M tokens</span>"},
];

const STEP_NAMES = ["Plan","Code","Review","PR"];
const MODEL_LABEL = { claude:"Claude", grok:"Grok", codex:"Codex" };
const TABS = ["Overview","Timeline","Changes","Review","Logs"];

let filter = "all", openId = null, tab = "Overview";

// ---- helpers ----------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const esc = (s) => (s == null ? "" : String(s)).replace(/[&<>]/g, (c) => ({ "&":"&amp;","<":"&lt;",">":"&gt;" }[c]));
const mbadge = (m) => `<span class="mbadge m-${m}">${MODEL_LABEL[m] || m}</span>`;
const badge = (s) => `<span class="badge b-${s}">${s.replace("_", " ")}</span>`;

function stepper(steps) {
  let h = '<div class="stepper">';
  steps.forEach((st, i) => {
    const cls = st === "done" ? "done" : st === "active" ? "active" : "";
    const ic = st === "done" ? "&#10003;" : (i + 1);
    h += `<div class="step ${cls}"><span class="ic">${ic}</span><span class="nm">${STEP_NAMES[i]}</span></div>`;
    if (i < steps.length - 1) h += `<span class="seg ${st === "done" ? "done" : ""}"></span>`;
  });
  return h + "</div>";
}

// ---- rendering --------------------------------------------------------------
function renderMetrics() {
  $("metrics").innerHTML = METRICS.map((m) =>
    `<div class="metric"><div class="v">${m.v}</div><div class="l">${m.l}</div><div class="s">${m.s}</div></div>`).join("");
}

function renderChips() {
  const counts = { all: RUNS.length };
  RUNS.forEach((r) => { counts[r.status] = (counts[r.status] || 0) + 1; });
  const defs = [["all","All"],["running","Running"],["queued","Queued"],["completed","Completed"],["needs_human","Needs human"],["failed","Failed"]];
  $("chips").innerHTML = defs.map(([k, lbl]) =>
    `<div class="chip ${filter === k ? "active" : ""}" data-filter="${k}">${lbl} <span class="muted">${counts[k] || 0}</span></div>`).join("");
}

function render() {
  renderChips();
  const q = ($("search").value || "").toLowerCase();
  const list = RUNS.filter((r) =>
    (filter === "all" || r.status === filter) &&
    (!q || `${r.owner}/${r.repo}#${r.issue} ${r.title}`.toLowerCase().includes(q)));
  $("count").textContent = list.length;
  $("rows").innerHTML = list.map((r) => `
    <tr class="run" data-id="${r.id}">
      <td>${badge(r.status)}</td>
      <td class="issue"><b>${r.owner}/${r.repo}#${r.issue}</b><div class="sub">${esc(r.title)}</div></td>
      <td>${stepper(r.steps)}</td>
      <td>${mbadge(r.coder)} <span class="muted small">&rarr;</span> ${mbadge(r.reviewer)}</td>
      <td>${r.iter}</td>
      <td class="muted">${r.duration}</td>
      <td>${r.pr ? `<a href="${r.pr_url}">${esc(r.pr)}</a>` : '<span class="muted">-</span>'}</td>
    </tr>`).join("") || `<tr><td colspan="7" class="muted" style="padding:24px">No runs match.</td></tr>`;
}

// ---- drawer -----------------------------------------------------------------
function openDrawer(id) { openId = id; tab = "Overview"; paintDrawer(); $("drawer").classList.add("show"); $("scrim").classList.add("show"); }
function closeDrawer() { $("drawer").classList.remove("show"); $("scrim").classList.remove("show"); }

function paintDrawer() {
  const r = RUNS.find((x) => x.id === openId);
  if (!r) return;
  $("d-title").innerHTML = `${badge(r.status)} &nbsp;${r.owner}/${r.repo}#${r.issue}`;
  $("d-meta").textContent = r.title;
  const ctrls = [];
  if (r.status === "running") ctrls.push(`<button class="btn btn-ghost">&#9209; Cancel</button>`);
  if (r.status === "failed" || r.status === "needs_human") ctrls.push(`<button class="btn btn-ghost">&#8635; Retry</button>`);
  if (r.pr) ctrls.push(`<button class="btn btn-ghost">&#8599; Open PR</button>`);
  ctrls.push(`<button class="btn btn-ghost">View issue</button>`);
  $("d-ctrls").innerHTML = ctrls.join("");
  $("d-tabs").innerHTML = TABS.map((t) => `<div class="tab ${tab === t ? "active" : ""}" data-tab="${t}">${t}</div>`).join("");
  $("d-body").innerHTML = bodyFor(r, tab);
}

function bodyFor(r, t) {
  if (t === "Overview") return `
    <div class="kv">
      <b>Run id</b><span>${r.id}</span>
      <b>Branch</b><span><code>ai-task/issue-${r.issue}-...</code></span>
      <b>Trigger</b><span>${r.trigger}</span>
      <b>Models</b><span>${mbadge(r.coder)} coder &middot; ${mbadge(r.reviewer)} reviewer</span>
      <b>Iterations</b><span>${r.iter} / 4</span>
      <b>Review</b><span>${r.review_passed === true ? "passed" : r.review_passed === false ? "not passed" : "-"}</span>
    </div>
    <h4>Plan</h4><pre>${esc(r.plan)}</pre>`;
  if (t === "Timeline") return `<ul class="tl">${r.timeline.map(([w, ts, what]) =>
    `<li><span class="who">${esc(w)}</span><span class="ts">${ts}</span><div class="what">${esc(what)}</div></li>`).join("")}</ul>`;
  if (t === "Changes") {
    const diff = r.diff.length ? `<h4>Diff (excerpt)</h4><pre class="diff">${r.diff.map(([k, l]) => `<span class="${k}">${esc(l)}</span>`).join("\n")}</pre>` : "";
    return `<h4>Coder report</h4><pre>${esc(r.changes)}</pre>${diff}`;
  }
  if (t === "Review") return `<h4>Verdict</h4><pre>${esc(r.review)}</pre>${r.required ? `<h4>Required changes</h4><pre>${esc(r.required)}</pre>` : ""}`;
  if (t === "Logs") return `<h4>Run log</h4><pre>${esc(r.logs)}</pre>`;
  return "";
}

// ---- modal ------------------------------------------------------------------
function openModal() { $("modal").classList.add("show"); }
function closeModal() { $("modal").classList.remove("show"); }

// ---- events (delegated — CSP-clean, no inline handlers) ---------------------
document.addEventListener("click", (e) => {
  const actionEl = e.target.closest("[data-action]");
  if (actionEl) {
    const a = actionEl.getAttribute("data-action");
    if (a === "new-run") return openModal();
    if (a === "close-modal") return closeModal();
    if (a === "close-drawer") return closeDrawer();
    if (a === "fake-start") { closeModal(); alert("Demo only — in the live app this POSTs /api/runs and the run appears in the table."); return; }
  }
  const chip = e.target.closest(".chip[data-filter]");
  if (chip) { filter = chip.getAttribute("data-filter"); return render(); }
  const tabEl = e.target.closest(".tab[data-tab]");
  if (tabEl) { tab = tabEl.getAttribute("data-tab"); return paintDrawer(); }
  const row = e.target.closest("tr.run[data-id]");
  if (row && !e.target.closest("a")) return openDrawer(row.getAttribute("data-id"));
});

document.addEventListener("keydown", (e) => { if (e.key === "Escape") { closeDrawer(); closeModal(); } });

$("search").addEventListener("input", render);

renderMetrics();
render();
