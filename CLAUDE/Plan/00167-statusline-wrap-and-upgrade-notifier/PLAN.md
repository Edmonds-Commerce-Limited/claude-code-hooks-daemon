# Plan 00167: statusline wrap and upgrade notifier

**Status**: Not Started
**Created**: 2026-07-16
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The status line is assembled by joining every enabled `status_line` handler's
fragment with `" | "` in `core/hook_result.py` (the `Status` branch,
lines 164-185) and returning `{"text": text}`. There is **zero** terminal-width
awareness — no truncation, no wrapping. On a narrow terminal Claude Code renders
the single long line and the right-hand segments simply run off the edge and
disappear. This plan makes the status line wrap onto multiple rows so nothing is
lost on narrow screens.

Research (2026-07-16) established the enabling facts: Claude Code officially
supports **multi-line** status output — every `\n` in the command's stdout
renders as a separate terminal row — and it exposes the terminal size to the
statusLine command via the `COLUMNS`/`LINES` **environment variables**
(Claude Code v2.1.153+). The daemon is a separate long-running process and does
**not** inherit those vars, but the jq-free transport in `init.sh`
(`send_request_stdin`, the `Status` branch around line 960) runs inside the
wrapper's process — which *does* have them — so it is the correct injection
point to forward width/height into the Status payload.

This plan also separates the **daemon-upgrade notifier** from the developer
**daemon health stats**. Today the `📦 vX → vY` upgrade arrow is rendered inside
`daemon_stats.py` (lines 112-134), so the only way to see the upgrade prompt is
to enable the full health line (uptime/memory/log-level/errors/blocks). We
extract the upgrade indicator into its own **on-by-default** `upgrade_notifier`
status handler so the valuable upgrade prompt reaches every client while the
noisy developer diagnostics stay off. `daemon_stats` already defaults off
(`get_default_enabled() == False`); the client-facing work is the **rollout
messaging** — the upgrade advisory must strongly recommend that any client that
has explicitly enabled `daemon_stats` now turn it off, since the upgrade prompt
no longer depends on it. **This repo is the one exception**: as the daemon's own
development repo it keeps `daemon_stats` enabled (the health line is useful
here).

Two secondary questions from the same investigation are answered inline: (a)
**cron tasks** — Claude Code's Status **input JSON** carries no scheduled-cron
information, but the harness DOES persist self-wake / scheduled-task state on
disk (`~/.claude/jobs/<id>/state.json` records `inFlight.kinds: [session_cron]`
and `selfWake: true`; `CronList` is the live per-session API). So a "crons
scheduled" indicator is **feasible** by reading that on-disk store — reframed
from impossible to a documented future enhancement; (b) **unused input fields**
— several documented Status-input JSON fields are currently ignored and are
catalogued below for opportunistic use.

## Goals

- Status line wraps onto multiple rows so no segment is lost on a narrow
  terminal, driven by the real terminal width.
- Forward `COLUMNS`/`LINES` from the wrapper environment into the Status payload
  and validate them in the Status input schema.
- Extract the upgrade-available indicator into a dedicated, on-by-default
  `upgrade_notifier` status handler so every client keeps the upgrade prompt.
- Ship client rollout messaging (config-changes + post-upgrade guidance) that
  strongly recommends disabling `daemon_stats` where a client enabled it; keep
  `daemon_stats` enabled in THIS repo only (dev-repo exception).
- Document the answers to the cron question and the unused-field inventory.

## Non-Goals

- Actually surfacing a cron indicator in the status line now — the data is not
  in the Status input JSON. It IS persisted on disk (`~/.claude/jobs/*/state.json`,
  `session_cron` / `selfWake`; `CronList` live API), so it is feasible as a
  FUTURE enhancement, but out of scope for this plan.
- Reworking `usage_tracking` (noted separately as needing rework); wiring the
  newly-available `rate_limits` field into it is out of scope here.
- Changing the segment ORDER or the per-segment content of existing handlers.

## Context & Background

### Status input fields: used vs available (research 2026-07-16)

Currently READ by handlers: `model.{id,display_name}`, `context_window.*`,
`workspace.{current_dir,project_dir}`, `cost`, `effort.level`, `session_id`,
`session_name`, `agent_type`.

Documented but currently UNUSED (available via `additionalProperties: True`):
top-level `version`, `cwd`, `output_style`, `exceeds_200k_tokens`,
`rate_limits.*`, `prompt_id`, plus nested `agent.*`, `pr.*`, `worktree.*`,
`vim.*`. Notable: `rate_limits` and `version` are the highest-value unused
fields. `COLUMNS`/`LINES` are NOT in the JSON — they are environment variables
this plan forwards explicitly.

### Key code locations

- Assembly / join: `src/claude_code_hooks_daemon/core/hook_result.py:164-185`.
- Transport / injection point: `init.sh` `send_request_stdin`, Status branch
  (~line 960 sets `hook_input['hook_event_name'] = 'Status'`).
- Status input schema: `src/claude_code_hooks_daemon/core/input_schemas.py:232`.
- Upgrade indicator (to extract): `handlers/status_line/daemon_stats.py:112-134`.
- Version cache producer: `handlers/session_start/version_check.py`.

## Tasks

### Phase 1: Forward terminal size into the Status payload

- [ ] ⬜ **Task 1.1**: Inject `COLUMNS`/`LINES` from `os.environ` into the Status
  `hook_input` inside `init.sh` `send_request_stdin` (Status branch), as
  integer fields (e.g. `terminal_columns`, `terminal_lines`), omitting them
  when unset or non-numeric so behaviour degrades cleanly on older clients.
- [ ] ⬜ **Task 1.2**: Extend `STATUS_LINE_INPUT_SCHEMA` in `input_schemas.py`
  to declare the new integer fields (nullable/optional) and add coverage in
  the input-schema tests.
- [ ] ⬜ **Task 1.3**: Verify end-to-end that the daemon receives the width by
  probing the live socket with a crafted Status payload and confirming a
  handler can read it.

### Phase 2: Wrap the assembled status line

- [x] ✅ **Task 2.1**: Write failing tests for a width-aware wrap of the joined
  Status text: split at `" | "` segment boundaries into rows each no wider
  than the terminal width; no width available ⇒ current single-line output
  (backwards-compatible); a single oversize segment occupies its own row. DONE
  — `TestHookResultStatusWrapping` (10 cases incl. ANSI-not-counted, ZWJ
  zero-width, never-split-mid-segment).
- [x] ✅ **Task 2.2**: Implement the wrap in the `Status` branch of
  `hook_result.py` (or an extracted helper), reading the forwarded width
  from the hook input; account for emoji display width where practical. DONE —
  `_wrap_status_parts` (greedy first-fit at `|` boundaries) + `_display_width`
  (ANSI-stripped; East-Asian wide = 2 cols; combining/format = 0; ±1 tolerance).
  `to_json` gains `terminal_columns`, threaded from all three call sites
  (`controller.py`, `server.py`, `front_controller.py`). Width absent/invalid ⇒
  single-line join (backwards-compatible).
- [x] ✅ **Task 2.3**: Confirm multi-line rendering in a live Claude Code
  session at several terminal widths (wide = one line, narrow = wrapped). DONE —
  live probe of `.claude/hooks/status-line`: `COLUMNS=36` wraps to 5 rows at
  segment boundaries (no segment lost), `COLUMNS=200` stays one line. This also
  confirmed the full transport path (Phase 1 `terminal_columns` → schema →
  `HookInput` → `to_json`) works end-to-end.

### Phase 3: Extract the upgrade notifier

- [ ] ⬜ **Task 3.1**: Write failing tests for a new `UpgradeNotifierHandler`
  (status_line) that reads `version_check_cache.json` and emits
  `📦 vX → vY` only when an upgrade is available and the cache is not stale,
  reproducing the existing `daemon_stats` logic exactly.
- [ ] ⬜ **Task 3.2**: Implement `upgrade_notifier.py` with `get_default_enabled`
  returning `True`; add its `HandlerID`/`Priority` constants and register it.
- [ ] ⬜ **Task 3.3**: Remove the upgrade-indicator block from `daemon_stats.py`
  (lines 112-134) so health stats and the upgrade prompt no longer overlap;
  update `daemon_stats` tests accordingly.

### Phase 4: Client rollout messaging

- [ ] ⬜ **Task 4.1**: Add a `CLAUDE/UPGRADES/UNRELEASED/config-changes/v{X.Y.Z}.yaml`
  entry recording `upgrade_notifier` (added, on by default) AND a
  `recommended: true` note that clients disable `daemon_stats` if they enabled
  it, so the upgrade advisory actively promotes the change.
- [ ] ⬜ **Task 4.2**: Add post-upgrade guidance (and a `truth-changes/` entry if
  a documented truth changed) telling upgrading projects the upgrade prompt is
  now its own handler and `daemon_stats` can be turned off.
- [ ] ⬜ **Task 4.3**: Keep `daemon_stats` ENABLED in THIS repo's
  `.claude/hooks-daemon.yaml` (dev-repo exception) and confirm `upgrade_notifier`
  is enabled; regenerate `.claude/HOOKS-DAEMON.md`.

### Phase 5: Docs and verification

- [ ] ⬜ **Task 5.1**: Update `handlers/status_line/CLAUDE.md` and
  `CLAUDE/Architecture/StatusLine.md` for the new handler, the wrap behaviour,
  and the forwarded width fields; record the cron answer (on-disk feasibility)
  and the unused-field inventory in the architecture doc.
- [ ] ⬜ **Task 5.2**: Run `./scripts/qa/run_all.sh`, restart the daemon, and
  verify `Status: RUNNING`; dogfood the wrapped status line and the
  upgrade-notifier separation.

## Dependencies

- Related: the `version_check` SessionStart handler (produces the cache the new
  `upgrade_notifier` reads) — no change required, only a new reader.

## Technical Decisions

### Decision 1: Wrap via multi-line output, not truncation

**Context**: Narrow terminals drop right-hand segments off the edge.
**Options Considered**:

1. Truncate the line to `COLUMNS` — simplest, but still loses information.
2. Wrap at segment boundaries into multiple rows — preserves every segment.

**Decision**: Option 2. Claude Code renders one terminal row per `\n`, so
wrapping at `" | "` boundaries keeps all information visible while respecting
width. Truncation was rejected because it reintroduces the same data loss.
**Date**: 2026-07-16

### Decision 2: Forward width via the transport, not a daemon-side lookup

**Context**: The daemon process does not inherit the client's `COLUMNS`.
**Options Considered**:

1. Read `COLUMNS` inside the daemon — wrong process; value is absent/stale.
2. Inject `COLUMNS`/`LINES` into the payload in the `init.sh` transport.

**Decision**: Option 2 — the transport's inline Python runs in the wrapper's
environment and already rewrites the Status payload, so it is the single correct
injection point. **Date**: 2026-07-16

### Decision 3: Extract the upgrade notifier; make IT on-by-default, not daemon_stats

**Context**: The upgrade arrow is entangled with developer health stats, and the
valuable part (upgrade prompt) must reach every client while the diagnostics
must not.
**Decision**: Give the upgrade prompt its own **on-by-default** `upgrade_notifier`
handler (SRP), matching the code comment that already calls the upgrade notifier
a "SEPARATE handler". `daemon_stats` stays off-by-default for clients (unchanged
default) and enabled only in THIS dev repo. Rollout messaging then nudges any
client that enabled `daemon_stats` to disable it. **Date**: 2026-07-16

## Success Criteria

- [ ] On a narrow terminal the status line wraps and no segment is lost.
- [ ] On a wide terminal the status line renders on a single row (unchanged).
- [ ] `COLUMNS`/`LINES` reach a status handler and are schema-validated.
- [ ] `upgrade_notifier` shows `📦 vX → vY` on by default, with `daemon_stats` off.
- [ ] Upgrade advisory recommends clients disable `daemon_stats` if enabled.
- [ ] `daemon_stats` remains enabled in THIS repo (dev-repo exception).
- [ ] Full QA passes and the daemon restarts to `RUNNING`.

## Risks & Mitigations

| Risk                                              | Impact | Probability | Mitigation                                                      |
| ------------------------------------------------- | ------ | ----------- | --------------------------------------------------------------- |
| Older Claude Code (\<2.1.153) sends no `COLUMNS`  | Med    | Med         | Absent width ⇒ single-line fallback; never crash                |
| Emoji width miscounted, wrapping slightly off     | Low    | Med         | Wrap at segment boundaries (never mid-segment); tolerate ±1 col |
| Multi-line status disallowed in some client build | Med    | Low         | Verify live before shipping; single-line fallback stays valid   |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00167-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan drafted from status-line investigation (research 2026-07-16).
