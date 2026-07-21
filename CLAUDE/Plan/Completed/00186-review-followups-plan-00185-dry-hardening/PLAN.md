# Plan 00186: Review follow-ups from Plan 00185 (DRY + hardening)

**Status**: Complete
**Created**: 2026-07-21
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The v3.48.0 release code-review gate (Plan 00185) returned **0 blocking**
findings but **3 non-blocking** DRY/hardening follow-ups. Per
`CLAUDE/development/RELEASING.md` "Review Early, Never Drop Findings", every
review finding must be either fixed before ship or captured as a tracked
MUST-FIX and fixed immediately after. v3.48.0 shipped clean; this plan closes
the loop on the three items so the review value is not lost as silent tech debt.

## Goals

- Make the settings.json self-heal write **atomic** (temp + `os.replace`) so a
  crash mid-write can never leave a truncated `settings.json`.
- Convert the install.py ↔ hook_registration.py timeout duplication from a
  **silently-drifting** pair into a **drift-guarded** one (value + command
  shape), so the SSoT drift test would catch a future divergence.
- Resolve the redundant double-reconcile in `cmd_reconcile_settings` (fix or
  document as an intentional reuse of the fail-safe writer).

## Non-Goals

- No behaviour change to the reconciler's merge semantics (additive, idempotent,
  preserve-everything-else) — these are internal robustness/DRY improvements.
- Not re-opening any v3.48.0 shipped behaviour; this is post-release close-out.

## Findings (from the v3.48.0 code-review gate)

| #   | Severity | Location                                                                                 | Issue                                                                                                                                                                                              | Remediation                                                                                                                                                                                                                        |
| --- | -------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| F1  | Low      | `src/claude_code_hooks_daemon/utils/settings_repair.py:93`                               | `settings_path.write_text(...)` is non-atomic; a crash mid-write truncates `settings.json` (recoverable via the one-shot backup, but not clean).                                                   | Write to a sibling temp file then `os.replace` (atomic rename on the same filesystem).                                                                                                                                             |
| F2  | Low      | `src/claude_code_hooks_daemon/utils/hook_registration.py:277,281` ↔ `install.py:315,650` | Timeout value (`60`) and the timeout-bearing event set are duplicated; the drift test guards only the event **key set**, not the timeout value or command shape.                                   | Extend `test_settings_sources_ssot_drift.py` to assert install.py's timeout value **and** the timeout event set **and** the command template agree with `hook_registration.py`.                                                    |
| F3  | Low      | `src/claude_code_hooks_daemon/daemon/cli.py` `cmd_reconcile_settings` (~3143 + ~3161)    | On the exists+write path the settings are reconciled twice — once for the decision (`reconcile_settings_hooks`) and again inside `repair_settings_registrations` (which re-reads + re-reconciles). | Resolve: reuse the audited fail-safe writer (`repair_settings_registrations`) is intentional; the second reconcile is O(events) and negligible. Document the tradeoff in-code rather than duplicating the backup logic in the CLI. |

## Tasks

### Phase 1: F1 — atomic self-heal write

- [x] ✅ **Task 1.1**: RED — tests that `repair_settings_registrations` leaves no
  temp residue on success and, if `os.replace` fails, leaves the live
  `settings.json` byte-for-byte intact (never truncated).
- [x] ✅ **Task 1.2**: GREEN — stage the merged JSON in a sibling
  `.tmp.registration-repair` file then `os.replace` it into place (atomic on the
  same filesystem); temp unlinked on failure; one-shot backup unchanged.

### Phase 2: F2 — drift-guard the timeout duplication

- [x] ✅ **Task 2.1**: Extended `test_settings_sources_ssot_drift.py` — asserts
  install.py's `_HOOKS_WITH_TIMEOUT` == `_BASH_KEYS_WITH_TIMEOUT`, the inline
  timeout literal == `_DEFAULT_HOOK_TIMEOUT_SECONDS`, and install.py's `_hook_cmd`
  template == `_HOOK_COMMAND_TEMPLATE`. 3 new guards.

### Phase 3: F3 — document the intentional double-reconcile

- [x] ✅ **Task 3.1**: Added an in-code comment in `cmd_reconcile_settings`
  explaining the exists+write branch deliberately reuses the fail-safe writer so
  the backup/atomic-write/malformed guards live in one audited place.

### Phase 4: verify

- [x] ✅ **Task 4.1**: Full QA `llm_qa.py all` 13/13 (10520 tests, 95.2% cov);
  daemon restart RUNNING. (First run flagged `error_hiding` on the F1 temp
  cleanup; fixed by matching `utils/retention.py`'s no-cleanup atomic pattern.)

## Success Criteria

- [x] Self-heal write is atomic; regression test proves no partial write.
- [x] The timeout duplication is drift-guarded (a divergence fails the test).
- [x] F3 resolved (documented); no double-reconcile confusion for future readers.
- [x] QA 13/13; daemon RUNNING.

## Dependencies

- Follows Plan 00185 (Completed) — these are its review follow-ups.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Blow-by-blow log lives in JOURNAL/00186-Journal-YY-MM-DD.md. -->

- Plan created to capture the 3 non-blocking v3.48.0 review findings — `e5f02f4d`.
- F1 atomic self-heal write + F2 timeout drift guard + F3 documented reconcile;
  QA 13/13 (10520 tests, 95.2% cov) — delivered in the `Plan 00186: Complete`
  closure commit.
