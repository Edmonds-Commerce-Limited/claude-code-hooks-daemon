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
extract the upgrade indicator into its own always-on `upgrade_notifier` status
handler and disable `daemon_stats` in this repo's config, keeping the useful
upgrade prompt while dropping the noisy diagnostics.

Two secondary questions from the same investigation are answered inline and
folded into scope where cheap: (a) **cron tasks** — Claude Code provides **no**
scheduled-cron information to the status line, and nothing daemon-side is
reachable either, so there is nothing to surface (Non-Goal); (b) **unused input
fields** — several documented Status-input JSON fields are currently ignored and
are catalogued below for opportunistic use.

## Goals

- Status line wraps onto multiple rows so no segment is lost on a narrow
  terminal, driven by the real terminal width.
- Forward `COLUMNS`/`LINES` from the wrapper environment into the Status payload
  and validate them in the Status input schema.
- Extract the upgrade-available indicator into a dedicated, on-by-default
  `upgrade_notifier` status handler.
- Disable `daemon_stats` in this repo while preserving the upgrade prompt.
- Document the answers to the cron question and the unused-field inventory.

## Non-Goals

- Surfacing scheduled cron/background-agent tasks in the status line — Claude
  Code does not provide this data and no daemon-side source exists.
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

- [ ] ⬜ **Task 2.1**: Write failing tests for a width-aware wrap of the joined
  Status text: split at `" | "` segment boundaries into rows each no wider
  than the terminal width; no width available ⇒ current single-line output
  (backwards-compatible); a single oversize segment occupies its own row.
- [ ] ⬜ **Task 2.2**: Implement the wrap in the `Status` branch of
  `hook_result.py` (or an extracted helper), reading the forwarded width
  from the hook input; account for emoji display width where practical.
- [ ] ⬜ **Task 2.3**: Confirm multi-line rendering in a live Claude Code
  session at several terminal widths (wide = one line, narrow = wrapped).

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

### Phase 4: Config, docs, and verification

- [ ] ⬜ **Task 4.1**: Disable `daemon_stats` and enable `upgrade_notifier` in
  `.claude/hooks-daemon.yaml`; regenerate `.claude/HOOKS-DAEMON.md`.
- [ ] ⬜ **Task 4.2**: Update `handlers/status_line/CLAUDE.md` and
  `CLAUDE/Architecture/StatusLine.md` for the new handler, the wrap
  behaviour, and the forwarded width fields; record the cron answer and the
  unused-field inventory in the architecture doc.
- [ ] ⬜ **Task 4.3**: Run `./scripts/qa/run_all.sh`, restart the daemon, and
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

### Decision 3: Extract the upgrade notifier rather than gate `daemon_stats`

**Context**: The upgrade arrow is entangled with developer health stats.
**Decision**: Give the upgrade prompt its own on-by-default handler (SRP) so it
survives disabling `daemon_stats`, matching the code comment that already calls
the upgrade notifier a "SEPARATE handler". **Date**: 2026-07-16

## Success Criteria

- [ ] On a narrow terminal the status line wraps and no segment is lost.
- [ ] On a wide terminal the status line renders on a single row (unchanged).
- [ ] `COLUMNS`/`LINES` reach a status handler and are schema-validated.
- [ ] `upgrade_notifier` shows `📦 vX → vY` with `daemon_stats` disabled.
- [ ] Developer health stats no longer appear in this repo's status line.
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
