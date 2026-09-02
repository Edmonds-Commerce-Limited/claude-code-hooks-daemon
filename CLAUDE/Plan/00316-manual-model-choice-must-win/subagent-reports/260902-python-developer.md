# Plan 00316 — python-developer build report

## Outcome

Phases 1–3 implemented with RED-first TDD, full QA 25/25. Not committed
(coordinator commits). PLAN.md tasks ticked; JOURNAL/ has the live-dogfood
checklist and the hot-reload caveat.

## Correction to the task brief

Task 1.3 named `model_fallback_detector` as the daemon-side indicator to
suppress. Reading the actual source showed that handler only ever fires
from the platform's OWN `model_refusal_fallback` transcript record — never
from a rank comparison, so it could never have fired for a manual `/model`
command. The real culprit (confirmed against the field-report's decision
log and code) is the status-line `downgrade_indicator` handler
(`src/claude_code_hooks_daemon/handlers/status_line/downgrade_indicator.py`

- `downgrade_state.py`), which self-detects a rank drop from the model id
  Claude Code reports on every render. Task 1.3 was redirected there.

## What changed

**Supervisor** (`.claude/ccy/claude-supervise.py`):

- `HumanInputLine` now recognises a submitted `/model <family>` or
  `/effort <level>` line (edge-triggered, consume-once — mirrors the
  existing `/compact` detection). New `take_model_submitted()` /
  `take_effort_submitted()`, plumbed through `InputActivity`.
- `TickFacts` gained `human_model_command` / `human_effort_command`
  (`None` by default), round-tripped through the host↔worker JSON protocol
  (`_facts_to_json`/`_facts_from_json`).
- `CompactStateMachine`:
  - `note_manual_model_command(family, now_wall)` records the last typed
    `/model` (family + timestamp; overwritten by each new command — rapid
    successive changes each count). `_MANUAL_MODEL_WINDOW_SECONDS = 120.0`.
  - `note_model_reading` now checks `_manual_model_matches()` before
    opening a downgrade episode: a match clears any stale open episode for
    the session and sets a consume-once note
    (`take_manual_model_note()`) instead of opening one — no auto-restore,
    no forced xhigh floor. `decide_once` surfaces the note into
    `noop_reason_log` as `"manual change (<family>) — no restore"`.
  - `note_manual_effort_command(level, now_wall)` records a latch
    (`_manual_effort_active`, not time-windowed). While set: the per-model
    default floor computation in `note_model_reading` is skipped entirely,
    and `arm_coupled_effort` no-ops (no post-`/model`-switch coupled
    effort). Cleared by the NEXT manual model command or a further manual
    effort command.
  - All four new fields round-trip through `export_state`/`import_state`
    (legacy state without them defaults safely).
- `write_manual_model_marker(daemon_untracked_dir, session_id, family, now)`
  — new atomic-write helper (mirrors `write_model_switch_signal`), called
  from `decide_once` on every observed manual command, writing
  `{daemon_untracked_dir}/manual-model-changes/<session_id>.json`.

**Daemon** (`src/claude_code_hooks_daemon/handlers/status_line/`):

- `downgrade_state.py`: `evaluate_downgrade(..., manual: bool = False)` —
  a manual drop resets the high-water to the manual choice instead of
  reporting a downgrade (closing any open episode as a recovery), so a
  LATER genuine silent substitution below the manual choice is still
  caught. New `is_manual_model_change(dir_path, session_id, family, now=)`
  reads the supervisor's marker, gated through a second `MtimeCachedFile`
  cache (not a direct read — the status-line package enforces this via
  `test_no_ungated_render_reads.py`).
- `downgrade_indicator.py`: `_render_segment` now resolves the manual flag
  via `is_manual_model_change` before calling `evaluate_downgrade`.

**QA fallout fixed** (not suppressed): a new `MtimeCachedFile`-gated read
(not an allowlist bypass) for the ungated-render-reads guard, and a
matching documented exclusion entry in
`scripts/qa/error_hiding_exclusions.json` for `_parse_manual_marker`'s
fail-silent shape (same contract as the neighbouring `_parse_state`, which
already had one).

## Tests added (all TDD, RED confirmed before GREEN during development)

- `tests/unit/supervise/test_manual_model_choice.py` (23 tests): typed-line
  recognition (incl. backspace-correction, bare `/model`), manual-match
  suppression + decision-log wording, silent-substitution unchanged, window
  expiry, rapid successive changes, alias/full-model-id matching, clearing
  a stale open episode, the shared marker write, manual-effort precedence
  over both the per-model floor and the coupled default, latch-clearing
  rules, export/import round-trips (incl. legacy-state defaults), and
  `TickFacts`/JSON round-trips.
- `tests/unit/handlers/status_line/test_downgrade_state.py`: `manual=True`
  suppression + high-water reset + later-silent-drop-still-caught, plus a
  new `TestManualModelChange` class for `is_manual_model_change` (missing/
  matching/wrong-family/stale/corrupt marker).
- `tests/unit/handlers/status_line/test_downgrade_indicator.py`: handler-
  level manual-marker suppression, high-water reset, wrong-family marker
  does NOT suppress, no-marker still reports a silent downgrade.

## Verification

- `tests/unit/supervise/` (611 tests, was 588): all pass.
- `tests/unit/handlers/status_line/` (487 tests): all pass, including the
  ungated-render-reads guard and the error-hiding self-scan.
- `uv run ruff check` / `uv run mypy` clean on every touched file.
- `./scripts/qa/llm_qa.py all`: **25/25 PASSED** (two intermediate rounds
  surfaced and were fixed properly — see JOURNAL 10:50 entry for the
  fallout detail).

## Live verification still needed (cannot be done from this session)

The supervisor's PTY-host tier (`_forward_io`, the new `/model`/`/effort`
line tracking) does **not hot-reload** — it only takes effect in a freshly
started ccy session. The worker-tier logic hot-reloads within the current
session (verify with
`ps -eo pid,lstart,args | grep 'claude-supervise.py --worker' | grep -v grep`).
See the JOURNAL's 11:05 handoff entry for the exact live-dogfood checklist
(manual `/model opus` → no restore, no indicator; manual `/effort low` on a
higher-floor family → no re-raise).

## Files touched

- `.claude/ccy/claude-supervise.py`
- `src/claude_code_hooks_daemon/handlers/status_line/downgrade_state.py`
- `src/claude_code_hooks_daemon/handlers/status_line/downgrade_indicator.py`
- `scripts/qa/error_hiding_exclusions.json`
- `tests/unit/supervise/test_manual_model_choice.py` (new)
- `tests/unit/handlers/status_line/test_downgrade_state.py`
- `tests/unit/handlers/status_line/test_downgrade_indicator.py`
- `CLAUDE/Plan/00316-manual-model-choice-must-win/PLAN.md`
- `CLAUDE/Plan/00316-manual-model-choice-must-win/JOURNAL/00316-Journal-26-09-02.md`
