# Plan 00175: statusline refresh interval first class

**Status**: In Progress
**Created**: 2026-07-17
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The Claude Code status-line `refreshInterval` governs how promptly the
*idle-updated* segments appear: the Ctrl+Z notice (Plan 00173), the clock, and
the multithread indicator (🧵 Y/X). Claude Code re-runs the status command only
on events (new assistant message, `/compact`, permission-mode change, vim-mode
toggle, debounced 300 ms) **plus** an optional `refreshInterval` timer whose
minimum is 1 second. Ctrl+Z is not an event, so during an idle wait the timer is
the *only* thing that repaints the bar.

Every project effectively ran at `refreshInterval: 10` (10 seconds), sourced from
a single recommendation constant, so an idle Ctrl+Z waited up to 10 s (avg ~5 s)
before the notice surfaced. Measurement showed the render itself is ~39 ms and
already git-cached (Plan 00155), so a 1 s timer costs ~4 % of one core while idle
— negligible. The correct value is the documented minimum, `1`.

This plan makes a low `refreshInterval` a **first-class, validated default**
across all hooks-daemon projects: fix the value at every origin (deployed
template, fallback generator, recommendation constant) and add a SessionStart
advisory that warns existing installs whose `refreshInterval` is missing or set
too high, with concrete remediation. It supersedes Plan 00174 (the artefact /
cadence redesign), which is unnecessary — Claude Code's 1 s refresh floor caps
any benefit a cheaper render could unlock.

## Goals

- Deployed default is `refreshInterval: 1` on **every** install path (primary
  verbatim-copy of the daemon's `.claude/settings.json`, and the fallback
  `generate_settings_json()` generator).
- The recommendation constant and the suggestion text advise `1`, not `10`.
- A SessionStart advisory (`statusline_refresh_checker`) warns when a configured
  `statusLine` is missing `refreshInterval` or sets it above an acceptable
  maximum, with the exact remediation — warn-only, never mutating user config.
- Existing installs get the corrected value automatically on upgrade (the
  installer overwrites `.claude/settings.json` with backup) and, between
  upgrades, a clear startup nudge.
- Full TDD coverage, QA green, daemon restart verified RUNNING, docs regenerated.

## Non-Goals

- **No auto-mutation** of the user's `.claude/settings.json` — advisory only. The
  only automated write remains the explicit installer deploy path.
- **No change to Claude Code's refresh semantics** — the 1 s floor and the event
  trigger set are upstream and out of our hands.
- **Not building the Plan 00174 artefact store** — the render is already cheap and
  cached, and the 1 s floor caps any faster-refresh benefit.
- **No sub-1-second Ctrl+Z mechanism** — that would require the supervisor writing
  directly to the terminal on suspend (bypassing the status line), a separate
  Plan-00173-class idea, not in scope here.

## Context & Background

Investigation findings (file:line anchors):

- **Source of `10`**: `src/claude_code_hooks_daemon/handlers/session_start/suggest_statusline.py:21`
  — `_RECOMMENDED_REFRESH_INTERVAL_S = 10`. This constant feeds the suggestion
  text a fresh project copies.
- **Installer primary path**: `scripts/install_version.sh:353-364` backs up then
  copies the daemon's `.claude/settings.json` **verbatim** (overwrite, never
  merge) into the target project. So the daemon's own settings.json IS the
  deployed default — already lowered to `1` (`.claude/settings.json:6`). Fresh
  installs and upgrades both land `1` automatically.
- **Installer fallback**: `scripts/install_version.sh:59-81`
  (`generate_settings_json()`) writes a `statusLine` block with **no**
  `refreshInterval` — a gap. Best-effort path for pre-settings.json daemon
  versions, but should still write `1` for consistency.
- **No validation today**: `suggest_statusline.py` only checks `statusLine`
  *presence* and its `matches()` returns `False` once `statusLine` exists
  (`:92`), so an already-configured project is never nudged about a stale
  `refreshInterval`. This is the gap the new handler closes.
- **Rollout mechanism**: `CLAUDE/UPGRADES/config-changes/` manifests target
  `hooks-daemon.yaml`, not `settings.json`, so there is no existing config-change
  channel for a settings.json value. The installer overwrite covers upgraders;
  the startup validator covers the between-upgrades window and deliberate
  high-setters.
- **Template**: `handlers/session_start/hook_registration_checker.py` is the
  closest clone target — warn-only, reads project settings.json, has
  `get_claude_md`.

## Tasks

### Phase 1: Correct the default at every origin

- [ ] ⬜ **Task 1.1**: Confirm the deployed default `refreshInterval: 1` in
  `.claude/settings.json` (already edited; this file IS the installer template)
  and verify it survives the primary install-copy path.
- [ ] ⬜ **Task 1.2**: Add `"refreshInterval": 1` to the fallback
  `generate_settings_json()` in `scripts/install_version.sh:79-81`; keep
  shellcheck clean.
- [ ] ⬜ **Task 1.3**: Lower `_RECOMMENDED_REFRESH_INTERVAL_S` 10 → 1 in
  `suggest_statusline.py`, update the rationale comment and suggestion body to
  the measured facts (39 ms cached render; idle Ctrl+Z / clock / multithread
  freshness), and update `test_suggest_statusline.py`.

### Phase 2: Startup validator handler (TDD)

- [ ] ⬜ **Task 2.1**: RED — write `test_statusline_refresh_checker.py`: fires on
  a new session when `statusLine` is configured AND `refreshInterval` is missing
  or above the acceptable maximum; silent when `statusLine` absent, when value
  is within range, and on resume sessions; threshold is config-overridable;
  `get_claude_md()` non-None.
- [ ] ⬜ **Task 2.2**: GREEN — implement `StatuslineRefreshCheckerHandler` cloned
  from `hook_registration_checker` (read project settings.json, warn-only
  advisory context with exact remediation).
- [ ] ⬜ **Task 2.3**: Register the handler across the surface —
  `session_start/__init__.py`, `constants/handlers.py` (HandlerID),
  `constants/priority.py`, `daemon/init_config.py` template,
  `.claude/hooks-daemon.yaml` + `.yaml.example`.
- [ ] ⬜ **Task 2.4**: Make the consistency/dogfooding tests green (config
  presence, registration, response validation, priority ordering).

### Phase 3: Rollout, docs, QA, supersede

- [ ] ⬜ **Task 3.1**: Add a `CLAUDE/UPGRADES/UNRELEASED/config-changes` note
  documenting the recommended settings.json value and the new handler, noting the
  rollout path (installer overwrite + startup advisory) since manifests target
  `hooks-daemon.yaml`.
- [ ] ⬜ **Task 3.2**: Regenerate `.claude/HOOKS-DAEMON.md`
  (`generate-docs`); reconcile any docs referencing the old `10`
  (`thread_registry.py:52` comment / Plan 00158 notes / HANDLER_REFERENCE).
- [ ] ⬜ **Task 3.3**: Full QA green (`./scripts/qa/llm_qa.py all`), daemon
  restart RUNNING, acceptance test for the new handler.
- [ ] ⬜ **Task 3.4**: Supersede Plan 00174 atomically (status flip + `git mv`
  into `Completed/` + README row + statistics recount in ONE commit), carrying
  forward its salvage — the scope-keyed per-session cache correctness item
  (shared-daemon leakage) — as a recorded future item.

## Technical Decisions

### Decision 1: New dedicated handler, not an extension of suggest_statusline

**Context**: Both concerns read the same settings.json. Should validation live in
`suggest_statusline` or a new handler?
**Decision**: A NEW handler, `statusline_refresh_checker`. `suggest_statusline`
fires when `statusLine` is **absent**; the validator fires when it is
**present-but-wrong** — opposite trigger conditions, so folding them muddies
`matches()`. `hook_registration_checker` is a clean warn-only + threshold +
`get_claude_md` template to clone (Single Responsibility).

### Decision 2: Advisory only — never auto-mutate settings.json

**Context**: Could the handler rewrite `refreshInterval` itself?
**Decision**: No. The daemon never silently edits the user's Claude Code settings
(matches `hook_registration_checker` / `optimal_config_checker`). The only
automated write is the explicit installer deploy path. The handler warns; the
user (or the next upgrade) applies the change.

### Decision 3: Values — recommend 1, warn above a named maximum

**Context**: What value to recommend, and when to warn?
**Decision**: Recommend `1` (Claude Code's minimum; render ~39 ms + git-cached →
~4 % of one core during idle, negligible). Warn if `refreshInterval` is missing
or `> _MAX_ACCEPTABLE_REFRESH_INTERVAL_S`, proposed `2` (1–2 s feels responsive
for the Ctrl+Z notice; 3 s+ warns). Both are named constants; the threshold is
overridable via a handler `options` key. Final threshold number pending user
confirmation.

### Decision 4: Rollout via installer overwrite + startup advisory

**Context**: `config-changes` manifests only drive `hooks-daemon.yaml`.
**Decision**: Upgraders get `1` automatically through the installer's
settings.json overwrite (with backup). The startup validator covers the
between-upgrades window and anyone who deliberately set a higher value. The
config-changes note documents the change for the upgrade guide even though its
enforcement channel does not touch settings.json.

## Success Criteria

- [ ] Every install path deploys `refreshInterval: 1` (primary verified; fallback
  generator writes it).
- [ ] Recommendation constant and suggestion text advise `1`.
- [ ] `statusline_refresh_checker` warns on missing / too-high `refreshInterval`,
  silent otherwise; warn-only; threshold config-overridable.
- [ ] Handler registered; daemon restarts RUNNING; dogfooding + consistency +
  response-validation tests pass.
- [ ] 95 %+ coverage; full QA green; `.claude/HOOKS-DAEMON.md` regenerated.
- [ ] Plan 00174 superseded in one atomic commit.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Blow-by-blow lives in JOURNAL/00175-Journal-YY-MM-DD.md. -->

- Design + investigation complete (this PLAN.md); implementation pending approval.

## Notes & Updates

- **Recovery cron**: `6ac90b2d` (session-wide non-durable failsafe, created for
  Plan 00174 this session) provides recovery coverage; not duplicated for 00175.
- **Supersedes Plan 00174** (status-line artefact / cadence redesign). Salvage
  carried forward: the scope-keyed per-session cache correctness item
  (shared-daemon per-session segment leakage) — a genuine future correctness
  concern, unrelated to lag, not in this plan's scope.
