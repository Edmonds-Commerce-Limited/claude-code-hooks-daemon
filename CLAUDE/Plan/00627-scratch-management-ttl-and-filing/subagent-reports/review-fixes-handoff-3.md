# Review-findings fixes, handoff 3

Worktree `/workspace/.claude/worktrees/agent-acff915e4bf3b86e6-0a26f829`, branch
`agent-acff915e4bf3b86e6-0a26f829` (origin/main merged, up to date). Follows
`review-fixes-handoff-2.md`. Venv: `untracked/venv-workspace_claude_worktrees_agent-acf-ba30-py313-0d6d49c6/bin`;
targeted lint/types: `bash untracked/qa.sh <files>`.

## Done

- **f97f84f74, item A: pressure mode was inert.** Diagnosis: LIVE "within its
  TTL" is a time-based hold that skipped every later rung. `judge` now runs the
  rest of the ladder for a not-due entry and records the result as
  `Judgement.ttl_hold` / `ttl_hold_proofs` (mirrored on `EntryRow`). A liveness
  LIVE never carries one. `pending_verdict(row)` (scratch_sweep) is used by every
  post-pass gate (dependency, unknown pointers, `_carried_down`,
  `_held_if_session`), and `_overruled` on a TTL-held row rewrites `ttl_hold`
  and keeps LIVE visible. `_pressured` needs `ttl_hold in ACTIONABLE`; `_record`
  archives the held verdict and proofs. Young repositories stay unclassified, so
  their hold is STUCK. Tests: `TestTtlHold` in test_scratch_verdict.py and
  test_scratch_sweep.py (end to end), plus apply tests. The `not_due` helper now
  builds realistic LIVE+hold rows. DESIGN section 8 bullet and a section 13 row
  have been updated.

## Found, not fixed (pre-existing, will fail the gate)

`tests/unit/core/test_scratch_archive_unreachable.py::test_only_the_cli_imports_or_names_archive_modules`
fails. Cause: `core/scratch_inventory.py` imports `scratch_archive_status.StoreStatus`
(commit cda23759c), and handlers import scratch_inventory. Options:

- Move `StoreStatus` (a read-only type) into a non-archive module.
- Inject the status as a callable typed by a protocol in scratch_inventory.

Do not just allowlist it.

## Left

- **B.** Four gate tests (run each file alone first):
  - test_acceptance_negative_case_requirement
  - test_acceptance_tool_payload_agrees_with_prose
  - test_bash_write_blindness_coverage (record the Scratch... handler's verdict)
  - test_documented_commands_are_not_self_denied (fix the docs, not the guard)
- **C.** Everything in handoff 2's "Left" section:
  - Review the SessionStart `scratch_sweep` handler.
  - DESIGN section 8 creation-scan text.
  - DESIGN section 13 outcomes for D-RULE 1-3, F1/F2 and unowned-entry.
  - A PLAN.md task row.
  - A journal entry via `mkplan.bash --journal`.
