# Plan 00158: agent thread navigation statusline

**Status**: In Progress
**Created**: 2026-07-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Recent Claude Code versions introduced **Agent View** — arrow-key navigation between
multiple agent threads (main session + background/subagent threads) inside one Claude
Code session. Our daemon-driven status line does not play well with it: the bar is
sometimes absent, and when present it is unclear whether it reflects the "default"
(main) thread or the thread the user is currently viewing.

This plan (a) documents the current, dogfood-verified truth of the two relevant Claude
Code surfaces — the main `statusLine` and the newer `subagentStatusLine` — so we stop
guessing about the contract, and (b) scopes the daemon work to make our status line
consistent and correct under Agent View: keep the main bar live while background
threads run, and render a first-class per-thread row via `subagentStatusLine` (a
surface our daemon currently ignores entirely).

The research and the live-session dogfooding are **done** (see Notes & Updates —
Confirmed Truths #1–#3, plus the Research Findings and Root-Cause sections below).
The implementation phases are scoped but **Not Started**.

## Research Findings (Claude Code surfaces)

Primary source: <https://code.claude.com/docs/en/statusline> (fetched 2026-07-13,
Claude Code v2.1.207). Where the initial research-agent summary conflicted with the
official docs, **the docs win** and are recorded here.

### A. Agent View (multi-agent thread navigation)

- Lets the user **arrow-key between agent threads** in a single session (main thread
  - background agents / Task-tool / Agent-tool subagents). Threads render in an
    **agent panel** below the prompt; background agents can run in isolated git worktrees.
- Ships in current stable Claude Code (research-preview from the v2.1.139 line; this
  session runs v2.1.207, which has it). Dispatch is via the Task/Agent tools,
  `/background`, or `claude --bg`.

### B. Main `statusLine` (the bottom bar)

- Config: top-level `statusLine` key (NOT inside `hooks`):
  `{"statusLine": {"type": "command", "command": "…", "padding": 0, "refreshInterval": N}}`.
- **Invocation / update triggers** (docs "How status lines work"): runs after each new
  assistant message, after `/compact`, on permission-mode change, and on vim-mode
  toggle. **Debounced 300ms**; if a new update fires while the script is still running,
  **the in-flight execution is cancelled**. It **temporarily hides** during autocomplete
  suggestions, the help menu, and permission prompts. Triggers **go quiet while the main
  session is idle** (e.g. a coordinator waiting on background subagents).
- `refreshInterval` (seconds, min 1) re-runs the command on a fixed timer *in addition*
  to event triggers — the documented fix for idle staleness while background agents work.
- **Full stdin field set** (docs "Available data"): `model.{id,display_name}`, `cwd`,
  `workspace.{current_dir,project_dir,added_dirs,git_worktree,repo.*}`,
  `cost.{total_cost_usd,total_duration_ms,total_api_duration_ms,total_lines_added,total_lines_removed}`,
  `context_window.{total_input_tokens,total_output_tokens,context_window_size,used_percentage,remaining_percentage,current_usage}`,
  `exceeds_200k_tokens`, `effort.level`, `thinking.enabled`,
  `rate_limits.{five_hour,seven_day}.{used_percentage,resets_at}`, `session_id`,
  `session_name`, `prompt_id` (v2.1.196+), `transcript_path`, `version`,
  `output_style.name`, `vim.mode`, `agent.name`, `pr.{number,url,review_state}`,
  `worktree.{name,path,branch,original_cwd}`.
- **Agent-thread identity: NO.** The only agent-ish field is `agent.name`, which is the
  top-level `--agent`/agent-settings name — NOT the Agent-View thread being viewed. The
  main bar has no field naming which thread it renders for, and (dogfooded) always
  renders the **main** session's identity regardless of which thread is focused.

### C. `subagentStatusLine` (per-thread rows in the agent panel)

- Config: sibling top-level key `{"subagentStatusLine": {"type": "command", "command": "…"}}`.
  Plugins may ship a default. Same trust / `disableAllHooks` gates as `statusLine`.
- **Purpose**: replaces the built-in default subagent row (`name · description · token count`) with your own formatting. If unset, Claude Code shows that built-in
  default — the row is **not blank**.
- **Invocation**: runs **once per refresh tick with ALL visible subagent rows in a
  single JSON object** on stdin (not once per row).
- **stdin**: the common base hook fields + `columns` (usable row width) + a `tasks[]`
  array. Each task: `id`, `name`, `type`, `status`, `description`, `label`, `startTime`,
  `model`, `contextWindowSize`, `tokenCount`, `tokenSamples`, `cwd`. `model` +
  `contextWindowSize` require **v2.1.205+** and are omitted until the task's model
  resolves. → **This surface DOES carry per-thread identity** (`id`/`name`/`type`/
  `status`/`cwd`/per-task tokens) that the main bar lacks.
- **Output**: one JSON line per row to override — `{"id":"<task id>","content":"<row body>"}`
  (ANSI allowed). Also reads `COLUMNS`/`LINES` env (v2.1.153+).

## Root-Cause Analysis (the three reported symptoms)

1. **"Sometimes there is no status line."** Documented behaviour, not a daemon bug per
   se: the bar hides during autocomplete/help/permission prompts, and its event triggers
   go quiet while the session idles waiting on background agents. We set **no**
   `refreshInterval`, so during long background-agent runs the bar can look stale/absent.
   The 300ms in-flight-cancellation can also drop a render under rapid updates.
2. **"Unclear whose data the bar shows."** The main `statusLine` has **no** thread
   identity and always renders the **main** session (dogfooded: `session_id`,
   `prompt_id`, `transcript_path` identical across 27 live renders). Arrowing into a
   background thread does **not** re-point the bottom bar; per-thread data lives in the
   **agent-panel rows**, which are governed by `subagentStatusLine` — a surface we do
   not implement, so those rows fall back to Claude Code's built-in default. Result:
   the rich daemon bar (main) and the plain built-in rows (threads) look inconsistent.
3. **"Does the statusline data give context we could use?"** Yes. The main payload
   already carries fields we do **not** yet use (`rate_limits.*`, full `cost.*`,
   `pr.*`, `worktree.*`, `prompt_id`, `thinking.enabled`). And `subagentStatusLine`'s
   `tasks[]` gives exactly the per-thread identity + token/model data needed to render
   consistent per-agent rows.

## Goals

- Establish and record the dogfood-verified contract for `statusLine` and
  `subagentStatusLine` (DONE — Research Findings + Confirmed Truths).
- Add daemon support for `subagentStatusLine`: a new hook entry point + Status-style
  event + handler(s) that render one row per `tasks[]` entry, so agent-panel rows match
  the main bar's look.
- Keep the main bar live while background agents run by adding a `refreshInterval` to
  the installed `statusLine` config (and teaching the installer/docs to emit it).
- Capture these as durable project truths (docs / truth-changes / config-changes) so
  upgrading users get the new surface and the `refreshInterval` recommendation.

## Non-Goals

- Re-pointing the **main** bottom bar to a focused background thread — Claude Code does
  not expose that identity to `statusLine`, so it is not achievable and out of scope.
- Building Agent View itself or changing how threads are dispatched.
- Any change to the 11 existing main-bar Status handlers' content beyond wiring reuse.

## Tasks

### Phase 1: Research & dogfood the contract (DONE)

- [x] ✅ **Task 1.1**: Capture the real live `statusLine` stdin payload in-session and
  confirm the field set + absence of thread identity (Confirmed Truth #1).
- [x] ✅ **Task 1.2**: Audit our config/repo for `subagentStatusLine` support
  (Confirmed Truth #2).
- [x] ✅ **Task 1.3**: Map our Status handler wiring + fields consumed (Confirmed Truth #3).
- [x] ✅ **Task 1.4**: Verify the `statusLine`/`subagentStatusLine` contract against the
  official docs primary source; reconcile against the research-agent summary.

### Phase 2: Design the `subagentStatusLine` surface (Not Started)

- [ ] ⬜ **Task 2.1**: Decide the daemon event name + hook script name for the new
  surface (e.g. `SubagentStatus` event, `.claude/hooks/subagent-status-line`
  forwarder) and how `send_request_stdin` distinguishes it (multi-row response,
  not single `{"text":...}`).
- [ ] ⬜ **Task 2.2**: Design the row-rendering Strategy: one row per `tasks[]` entry →
  `{"id","content"}` lines, reusing existing segment formatters (model, context %,
  cwd) where sensible. Define behaviour when `model`/`contextWindowSize` are absent
  (pre-v2.1.205 / unresolved task).
- [ ] ⬜ **Task 2.3**: Decide whether/how to reuse per-thread state keyed by
  `transcript_path` (cf. `disclosure_tracker`) vs the panel's own `tasks[].id`.

### Phase 3: TDD implementation (Not Started)

- [ ] ⬜ **Task 3.1**: RED — handler + response-shape unit tests for the multi-row
  subagent status output (positive rows, empty `tasks[]`, missing model fields).
- [ ] ⬜ **Task 3.2**: GREEN — implement handler(s) + response wiring + forwarder script.
- [ ] ⬜ **Task 3.3**: Add `subagentStatusLine` to the installer-emitted settings and to
  dogfooding config; add the `refreshInterval` to the emitted `statusLine`.
- [ ] ⬜ **Task 3.4**: Daemon restart verification (RUNNING) + `run_all.sh` green.

### Phase 4: Dogfood live + document truths (Not Started)

- [ ] ⬜ **Task 4.1**: In a live session with real background agents, arrow into a thread
  and confirm the panel rows now render our formatting consistently.
- [ ] ⬜ **Task 4.2**: Record a `truth-changes` entry (status line now spans two
  surfaces) and a `config-changes` entry (`subagentStatusLine` + `refreshInterval`,
  `recommended: true`) for the next release.

## Success Criteria

- [ ] The `statusLine` / `subagentStatusLine` contract is documented from the primary
  source with dogfood-verified fields (Phase 1 — met).
- [ ] Daemon renders per-thread agent-panel rows via `subagentStatusLine` that visually
  match the main bar, verified live in Agent View.
- [ ] Installed config carries a `refreshInterval` so the bar stays live during
  background-agent runs.
- [ ] `truth-changes` + `config-changes` manifests staged so upgraders adopt both.
- [ ] `./scripts/qa/run_all.sh` green and daemon restarts RUNNING.

## Notes & Updates

### 2026-07-13

- Plan scaffolded.
- Failsafe recovery cron created: ID `3b0a5760` (hourly at :37, non-durable, session-only).
  A duplicate advisor-created cron (`219a8c62`, identical) was pruned via CronDelete.
- Primary-source provenance: research reconciled against
  <https://code.claude.com/docs/en/statusline> (v2.1.207). The initial research-agent
  claim that `subagentStatusLine` carries no agent identity was **wrong** — the docs
  show its `tasks[]` array exposes per-thread `id`/`name`/`type`/`status`/`model`/
  `tokenCount`/`cwd`. Docs treated as authoritative over the agent summary.
- Dogfooding: temporarily instrumented `.claude/hooks/status-line` to tee the raw
  Status stdin payload to `scratchpad/statusline-capture.jsonl` so we could confirm
  the real JSON schema in a live session (esp. any agent-thread identity field).
  **REVERTED** — `git diff .claude/hooks/status-line` is clean; capture kept 27
  renders before revert.
- **CONFIRMED TRUTH #1 (live capture, 7 renders, Claude Code v2.1.207)**: the main
  `statusLine` stdin payload has these top-level keys ONLY:
  `context_window, cost, cwd, effort, exceeds_200k_tokens, fast_mode, model, output_style, prompt_id, rate_limits, session_id, session_name, thinking, transcript_path, version, workspace`. There is **NO** `agent`/`thread`/`parent`/
  `subagent`/`tab`/`fleet` field. Across all 7 renders `session_id`, `prompt_id`
  and `transcript_path` were **identical** — the main statusLine cannot tell which
  agent thread is being viewed; it always renders the main session's identity.
- **CONFIRMED TRUTH #2 (config audit)**: our `.claude/settings.json` wires ONLY
  `statusLine`. There is NO `subagentStatusLine` key in settings, NO reference to
  `subagentStatusLine` anywhere in `src/` or `docs/`, and NO `subagent-status-line`
  hook script (only `status-line` exists under `.claude/hooks/`). The daemon has
  zero support for the per-subagent status line surface — the prime suspect for the
  "sometimes no status line in Agent View" symptom.
- **CONFIRMED TRUTH #3 (code map + runtime)**: status line is wired via the
  top-level `statusLine` key (not the `hooks` block) → `.claude/hooks/status-line`
  → `send_request_stdin "Status" "status"`. 11 Status handlers live in
  `src/claude_code_hooks_daemon/handlers/status_line/`. Our code reads only:
  `session_id`, `model.{id,display_name}`, `context_window.*`, `workspace.*`,
  `cost.total_cost_usd`, `effort.level`. Feeding a captured payload back through the
  live hook renders correctly:
  `📁 claude-code-hooks-daemon | 📦 podman | 👤 … | 🤖 Opus 4.8 ▌▌▌▌▌ | ◔ 12% | 🕐 … | ⎇ main | 🪝 …`.
  Notably `context_sidecar` keys state by `session_id`, and `disclosure_tracker`
  keys per-agent by `transcript_path` (not the shared `session_id`) — relevant if a
  future subagent status line needs per-thread state.
