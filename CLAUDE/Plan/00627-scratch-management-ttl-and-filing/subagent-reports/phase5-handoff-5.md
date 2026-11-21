# Phase 5 handoff 5 (docs regenerated; Tasks 5.6 and 5.8 done)

## Done

- Docs: `bin/hooks-daemon restart` + `regenerate-docs` in this worktree regenerated `CLAUDE.md` and
  `.claude/HOOKS-DAEMON.md`; `docs/guides/HANDLER_REFERENCE.md` gained a hand-written `scratch_cap_guard` section and a
  blocking-table row (that file is not generated; `scripts/qa/check_handler_reference.py` passes).
  `tests/integration/test_claude_md_guidance_coverage.py` passes. Commit 2344f3c9f.
- Task 5.6: `ScratchSweepHandler` is `SessionStartVerifiable` (declared INFO). `sweep_action_required(reading, caps)`
  (module-level, `handlers/session_start/scratch_sweep.py`) is true when an entry is due or any cap is at warn; a
  missing inventory is false. `verify_still_needed` reads the cached inventory only. Tests:
  `tests/unit/handlers/session_start/test_scratch_sweep_must_do.py`. Commit 2c0a97b0d.
- Task 5.8: `CLAUDE/Routine/00004-scratch-sweep/` (schedule 7 days, grace 3 days, chosen by the agent: owner to
  confirm), index row in `CLAUDE/Routine/README.md`. `hooks-daemon routine-qa` now reports it "never run". Commit
  87372e754.

## Next

- Task 5.5 (pressure mode for `scratch-sweep --apply`, DESIGN section 8 line ~283): only at block; also pack entries
  NOT yet due, largest directory count first; never LIVE/KEPT/PROTECTED; only those idle for
  `scratch.caps.pressure_idle_minutes` (config field exists, default 30); such an archive expires no sooner than the
  entry's TTL plus its verdict's retention. The TTY-confirm gate stays; no other safety rule is relaxed. Not started.
- Task 5.7: `daemon/housekeeping.py` `HOUSEKEEPING_STEPS` + `UNCONFIRMED_STEP_NAMES`; amend the Decision 6 module
  docstring (DESIGN R13, X8). Coordinator ruling: while the interim TTY-confirm gate on `--apply` exists,
  `scratch-sweep-apply` must NOT apply unattended; implement it as report-only/advisory (prints the dry run and the
  apply command for a human) and say so in DESIGN section 10 and PLAN until the owner removes the gate. Not started.
- Note: running pytest on `tests` with `-k` is denied in a sub-agent (R-SUBAGENT-FULL-QA); name test files/dirs.
- Note: Edit/Write from a sub-agent launched in another worktree is denied (R-SUBAGENT-CROSS-WORKTREE-WRITE) until
  `EnterWorktree` with `path` switches the agent into this worktree.
