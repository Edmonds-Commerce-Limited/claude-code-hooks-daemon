# Plan 00158: agent thread navigation statusline

**Status**: Dormant
**Blocker**: Phases 2 and 4 target the `subagentStatusLine` surface, whose rendering pipeline is still at design stage in Plan 00174 (status-line artefact cadence redesign). Building against it now would be rework once that design settles.
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

- Lets the user **arrow-key between threads** in a single view. Two *distinct* thread
  kinds share this view (see Confirmed Truth #4 for the full split):
  - **Task-tool subagents** — workers inside the current session, rendered as **rows**
    in the agent panel (`subagentStatusLine`); no bottom bar.
  - **Background agents** — full independent sessions (`/background`, `claude --bg`),
    each with its own `session_id`/transcript, rendered with the **full bottom
    `statusLine` bar** when attached; may run in isolated git worktrees.
- Ships in current stable Claude Code (research-preview from the v2.1.139 line; this
  session runs v2.1.207, which has it).

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
- [x] ✅ **Task 1.5**: Disambiguate Task-tool subagents (panel rows) vs background-agent
  sessions (own bar) — the actual cause of the bar-vs-no-bar symptom (Confirmed Truth #4).

### Phase 1b: Dogfooding instrumentation — payload capture (DONE, redesigned)

Initial attempt (commit `aaa552c`) put capture in the forwarder behind the
`CLAUDE_HOOKS_CAPTURE_DIR` env var. **Superseded** on user feedback: the forwarder
is dumb transport, the toggle belongs in the *tracked* daemon config, and a
*daemon* restart (never a Claude Code relaunch) should apply it. Reimplemented
daemon-side:

- [x] ✅ **Task 1b.1**: `daemon.payload_capture` config (`enabled`/`dir`/`events`) in
  `src/claude_code_hooks_daemon/config/models.py`; daemon-side capture in
  `src/claude_code_hooks_daemon/daemon/payload_capture.py` (pure helpers) wired into
  `server._process_request` via `_capture_payload_best_effort` (fail-open, skips
  `_system`, warns-not-swallows on write failure).
- [x] ✅ **Task 1b.2**: Reverted the forwarder env-var capture in `init.sh` + its tests;
  new unit tests `tests/unit/daemon/test_payload_capture.py` (9 cases: disabled, writes
  JSONL, `_system` skipped, events filter, append, filename sanitisation, dir resolve).
- [x] ✅ **Task 1b.3**: Enabled it in tracked `.claude/hooks-daemon.yaml`
  (`events: [Status]`) and **live-verified**: daemon restart → a Status event was
  captured to `untracked/payload-capture/Status.jsonl` with the correct `session_id`,
  no Claude Code relaunch. Docs updated (`CLAUDE/DEBUGGING_HOOKS.md`); QA 13/13.

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

### Phase 5: Thread-safety audit under concurrent sessions (DONE — verdict recorded)

Motivated by the user's concern that recent perf memoisation must be safe now that
multiple background sessions hit ONE shared daemon. Handed off by Thread B with an
interim (and, it turns out, mistaken) premise. Verdict recorded as Confirmed Truth #6.

- [x] ✅ **Task 5.1**: Trace the dispatch path — found handler dispatch runs via
  `await loop.run_in_executor(None, controller.process_request, …)` (`server.py:958-970`),
  i.e. the default MULTI-threaded pool, so concurrent sessions DO run handlers on
  parallel OS threads. (Corrects Thread B's "single event loop → synchronous → safe".)
- [x] ✅ **Task 5.2**: Assess corruption risk — none: CPython's GIL makes the module
  caches' individual dict/list ops atomic, `functools.lru_cache` is internally locked,
  and the named caches (`git_branch` cwd cache, `settings_reader` mtime cache,
  `stats_cache_reader`) are keyed correctly → at worst redundant compute under a race.
- [x] ✅ **Task 5.3**: Assess cross-session contamination — the status bar render is safe
  (handlers read the per-event `hook_input`, empirically 12% vs 33%). The only shared
  mutable per-session global, `get_data_layer().session` (updated on EVERY StatusLine
  event, `controller.py:673`), has **no production reader** (grep: only a docstring
  example) → latent trap, not a live bug.

### Phase 6: "🧵 Y/X" multithread indicator status handler (DONE — live-verified)

From Thread B's working prototype (`untracked/multithread_yofx_proto.py`). Shows the
focused thread's stable rank among live sibling threads sharing the daemon.

- [x] ✅ **Task 6.1**: RED — pure count/rank helpers unit-tested in
  `tests/unit/handlers/status_line/test_thread_registry.py` (17 cases: stem safety,
  first_seen preservation, atomic write leaves no tmp, stale prune, window boundary,
  garbled-file skip, single→"", stable rank by first_seen, tie-break, unknown→"").
- [x] ✅ **Task 6.2**: GREEN — pure registry in
  `src/claude_code_hooks_daemon/handlers/status_line/thread_registry.py` +
  `MultithreadIndicatorHandler` (`multithread_indicator.py`, priority 13, default-ON
  opt-out — silent when X≤1). Per-session heartbeat under
  `daemon_untracked_dir()/thread-registry/<safe_session_id>.json`, atomic
  (tmp + `os.replace`), keyed by `session_id` NEVER the global SessionState (Truth #6);
  fail-open on `RuntimeError`/`OSError`. Handler tests
  (`test_multithread_indicator.py`, 15 cases). Registered across HandlerID/HandlerKey/
  Priority + `status_line/__init__.py`; drift-guard test still green (opt-out ⇒ no
  template entry). Docs regenerated (`.claude/HOOKS-DAEMON.md` → Status 12 handlers).
- [x] ✅ **Task 6.3**: Freshness window `_FRESH_WINDOW_S = 45.0` = 4.5× the installed
  `refreshInterval` (10s, delivered below) so an idle background thread keeps pinging on
  the timer and is never falsely pruned, while a genuinely-closed thread ages out within
  one window.
- [x] ✅ **Task 6.4 (live dogfood)**: With capture off and the daemon restarted, feeding a
  synthetic second Status session through the live `.claude/hooks/status-line` rendered
  the REAL bar as `… | 🧵 2/2 | …` — this session (`2b651a46…`) + the synthetic sibling,
  both counted from `untracked/thread-registry/`. Confirms the feature works end-to-end
  against the running daemon, not just in unit tests.

### Phase 3b: `refreshInterval` on the emitted `statusLine` (DONE)

Split out of Task 3.3 and delivered independently of the (still-unstarted)
`subagentStatusLine` surface, because it is the prerequisite that keeps Phase 6's count
accurate AND fixes the "bar goes stale/absent while idle on a background agent" symptom.

- [x] ✅ Verified the field against the primary source
  (<https://code.claude.com/docs/en/statusline>): `refreshInterval` is an integer in
  **seconds**, minimum 1, re-running the command on a timer in addition to events.
- [x] ✅ Added `"refreshInterval": 10` to the dogfood `.claude/settings.json` statusLine
  block, and to the `suggest_statusline` handler's recommended snippet + rationale
  (constant `_RECOMMENDED_REFRESH_INTERVAL_S`), with a new test asserting the suggestion
  includes it and explains the 🧵 idle-under-count motivation.

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
- **CONFIRMED TRUTH #4 (corrects an earlier conflation)**: "subagent" and the
  directly-created "agent thread" are **two different mechanisms**, and this — not a
  daemon bug — is why *some threads show a bar and some show only a row*:
  - **Task-tool subagent** — a worker *inside* one session; shares the parent's
    `session_id`/transcript; surfaces as a **row** in the agent panel governed by
    `subagentStatusLine` (or the built-in `name · description · token count` default).
    **No bottom bar.**
  - **Background agent** (docs: "background session" / "session in agent view";
    `/background`, `claude --bg`) — a **full independent session** with its **own**
    `session_id`/transcript; when attached it renders the **full bottom `statusLine`
    bar**, same as any session.
    So the daemon already drives the bar for every background-agent session (each is just
    another session hitting our `statusLine`); the gap is only the subagent *rows*
    (`subagentStatusLine`, unimplemented). Earlier plan prose that lumped background
    agents in with subagents is superseded by this entry.
- **DELIVERED (dogfooding tooling requested by user)**: a toggleable raw-payload
  capture, **daemon-side and config-driven** (`daemon.payload_capture` in the tracked
  `hooks-daemon.yaml`; `enabled`/`dir`/`events`). Applied by a **daemon restart** —
  never a Claude Code relaunch — because the forwarder is dumb transport and the daemon
  receives every `{event, hook_input}`. Off by default. Implemented in
  `daemon/payload_capture.py` (pure helpers) + `server._capture_payload_best_effort`
  (fail-open); unit tests in `tests/unit/daemon/test_payload_capture.py`; docs in
  `CLAUDE/DEBUGGING_HOOKS.md`. The earlier forwarder/env-var attempt (commit `aaa552c`)
  was superseded and reverted (commit `09b35b6`). This is the instrument to
  **empirically** confirm Truth #4 — a background agent's bar captures a `Status`
  payload with a *different* `session_id` than the main session.
- **LIVE EXPERIMENT in progress**: capture dogfooded ON here (`events: [Status]`). The
  user is running the two-thread test — background THIS session (Thread A,
  `b2b6dcb4-…`), start a new background thread (Thread B), and confirm B's Status
  renders land in `untracked/payload-capture/Status.jsonl` with a distinct
  `session_id`. Cross-thread coordination via `untracked/bg-thread-debug-messaging.md`
  (both files are untracked/gitignored). Pre-experiment baseline: 43 captured Status
  renders, all Thread A's session_id.
- **CONFIRMED TRUTH #5 (live two-thread experiment — DONE)**: ran Thread A (backgrounded)
  - Thread B (new background thread) concurrently. Results, from `Status.jsonl` + both
    agents + human observation:
  * **Distinct sessions, one daemon**: capture accumulated ≥4 distinct `session_id`s
    (Thread A pre-bg `b2b6dcb4`, A post-bg `2b651a46` = its job id, Thread B `c8031d41`,
    plus transients), all `cwd=/workspace`, all written to the SAME `Status.jsonl` →
    background threads are full independent sessions sharing one daemon. Backgrounding a
    thread gives it its own session identity (this thread's renders moved from `b2b6dcb4`
    to its job id `2b651a46`).
  * **The bar is per-focused-thread**: viewing Thread B, the human saw the bottom bar at
    **12%** (== `c8031d41`'s captured `used_percentage`); viewing Thread A, **~33%**
    (== `2b651a46`'s captured 34%). 12% ≠ 33%, each matching that thread's OWN captured
    data → each background thread renders its own `statusLine` bar with its own session's
    data. This resolves the original "whose data is the bar showing?" — it's the
    **currently-focused** thread's. The "some threads show no bar" case is Task-tool
    subagents (shared session → agent-panel row only, no bar).
  * **Cross-thread file coordination works**: the two sessions (which cannot message each
    other) coordinated entirely through the shared `bg-thread-debug-messaging.md`
    (append via `cat >>`, not Read/Edit, to avoid concurrent-write conflicts).
- **Post-experiment close-out**: capture flipped back to the shipped default
  (`daemon.payload_capture.enabled: false`) and daemon restarted — confirmed OFF (a
  Status render wrote no new line). Thread B released via the messaging file and closed
  by the user. Capture files remain under `untracked/payload-capture/` for reference.
  Re-enable anytime by flipping the flag + daemon restart (no Claude Code relaunch).
- **`agent` / `agent_type` payload fields discovered (Truth #1 amended)**: the
  captured `Status.jsonl` now carries top-level `agent` and `agent_type` keys.
  Thread B reported these as a way to tell a background thread apart — but that
  framing is **wrong**, and the capture disproves it: BOTH of Thread A's session
  ids, including the *backgrounded* one (`2b651a46`), captured `agent_type: null`.
  So `agent_type` flags **"this session was launched as an explicit agent"**
  (`--agent NAME` / an Agent-View-created thread), NOT "background vs. main". A
  backgrounded main thread stays `agent_type: null`. Correction to Truth #1: the
  main `statusLine` payload still carries **no field that distinguishes which
  Agent-View thread is focused** among plain (non-agent) threads — `agent`/
  `agent_type` only separate *named-agent* threads from plain ones. This is why a
  reliable multi-thread indicator (Phase 6 🧵 Y/X) must be built from a
  daemon-side per-session registry, not from any single payload field.
- **Confirmed Truth #6 — thread-safety audit verdict (Phase 5, DONE)**: Thread B
  raised a "single event loop → all dispatch is synchronous → inherently safe"
  premise and flagged possible races for any new per-session feature. Audited the
  real code and the premise is **wrong in its reasoning but right in its
  conclusion, with one caveat**:
  - **Dispatch IS concurrent, not synchronous.** `server.py` offloads every
    request via `result = await loop.run_in_executor(None, self.controller.process_request, request)`
    (the default `None` executor = a multi-threaded `ThreadPoolExecutor`). Parallel
    sessions sharing one daemon therefore run handler chains on **different OS
    threads simultaneously**. Thread B's "single-threaded" claim is false.
  - **No live corruption bug today.** Per-event handlers read only their own
    `hook_input` and write per-key artifacts; CPython's GIL makes the dict/list
    ops atomic and `lru_cache` is internally locked. The status-bar render is safe
    because it is a pure function of the per-event payload.
  - **Latent trap:** `controller.py` updates a **global** `get_data_layer().session`
    on *every* Status event (`update_from_status_event`). A grep found **no
    production reader** of that global state — so it is currently harmless — but it
    is a shared-mutable-singleton that WOULD corrupt under concurrent multi-session
    Status events if a reader were ever added.
  - **Verdict / mandate for Phase 6:** no fix required now; but any new
    per-session feature (the 🧵 Y/X registry) MUST key every artifact by
    `session_id` and write atomically (`tmp` + `os.replace`) — never lean on the
    global SessionState. Recorded as a hard constraint on Task 6.2.
- **DELIVERED — Phase 6 (🧵 Y/X indicator) + Phase 3b (`refreshInterval`)**: shipped
  the `MultithreadIndicatorHandler` (status priority 13, default-ON/opt-out, silent when
  X≤1) backed by the pure `thread_registry` helpers (atomic per-`session_id` heartbeat,
  stale-prune, stable rank by `first_seen`). Honoured the Truth #6 mandate: every artifact
  is keyed by `session_id` and written `tmp`+`os.replace`, never via the global
  SessionState. Added `"refreshInterval": 10` to the dogfood `.claude/settings.json` and
  the `suggest_statusline` recommendation (verified against the primary source: integer
  seconds, min 1). Registered across HandlerID/HandlerKey/Priority + `status_line/__init__`,
  the dogfood + example configs, and the handler-instantiation exemption list; docs
  regenerated. New/updated tests: `test_thread_registry.py` (19), `test_multithread_indicator.py`
  (16), plus a `suggest_statusline` case — both new src files at **100% coverage**.
  Authoritative QA (`llm_qa.py`) green: lint/format/type/magic/error_hiding 0.
  **Live-verified**: the real bar rendered `… | 🧵 2/2 | …` for this session + a synthetic
  sibling before the sibling aged out. Daemon restarted RUNNING after every code change.
  Phases 2 & 4 (the `subagentStatusLine` per-thread ROW surface, and its release
  truth-changes/config-changes manifests) remain **Not Started** — a separate larger surface.
- **FOLLOW-UP FIXES (user feedback) — moved to first + spare over-count fixed**:
  - *"Showing 🧵 1/2 but only 1 thread"* — root-caused empirically via payload capture:
    Claude Code keeps **pre-warmed background "spare" PTY hosts** (`--bg-spare` / `bg-pty-host`
    in `ps`) ready to be claimed. A spare renders `statusLine` (warming) but is NOT a
    navigable thread. Its payload is distinguishable: `agent={"name":"claude"}`,
    `agent_type="claude"`, and **no** `session_name`/`prompt_id`/`rate_limits` — whereas a
    real interactive thread (incl. this backgrounded+forked one) reports `agent=null`,
    `agent_type=None`, and carries those fields. Fix: the handler now **skips any session
    with a truthy `agent_type`** (no heartbeat, no render), so an unclaimed spare can never
    inflate a real session's count. Live-verified: a spare payload writes no heartbeat and
    shows no 🧵; the lone real session correctly shows nothing.
  - *"Move it to the first item"* — dropped the priority from 13 to **2** (before
    `git_repo_name` at 3). No render-format change was needed: the Status join
    (`hook_result.py`) strips each fragment's outer `|` and re-joins with `|`, so a
    reorder is separator-safe by design. Live-verified: with two real sessions the bar
    renders `🧵 2/2 | 📁 repo | …` (🧵 leads). New src files stay at **100% coverage**;
    QA green; daemon restarted RUNNING.
