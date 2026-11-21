# Review-findings fixes, handoff 2

Worktree `/workspace/.claude/worktrees/agent-acff915e4bf3b86e6-0a26f829`, branch
`agent-acff915e4bf3b86e6-0a26f829`. Follows `review-fixes-handoff-1.md`. Everything
listed as done is committed and pushed.

## Done

- **50e92580e, F-BYPS F2 (core).** `pressure_for` returns None unless
  `caps.mode == "block"` (advise and off give no pressure). New
  `pressured_count(report, pressure)` counts the not-due entries pressure adds,
  across the root and its session children.

- **ef8c52a14, F-BYPS F1 + F2 (CLI).** `cmd_scratch_sweep --apply` classifies
  once BEFORE the confirmation. `_scratch_pressure(sources, report, ttl)`
  evaluates the caps on that fresh report with `previous=None` (the cached
  inventory is no longer read) and gives None when the reading is incomplete.
  The confirm prompt includes `_scratch_pressure_notice` (names pressure mode and
  the count). The decision is passed into `_scratch_apply(..., pressure)` and
  never re-made after consent. The confirm seam is now `(root, notice) -> bool`;
  the three test call sites were updated. Tests cover a stale cached BLOCK with a
  fresh under-cap reading, an incomplete walk, advise mode, and the prompt text.
  The F1 and F2 CLI parts share one function, so they are one commit; the core
  part is separate.

- **1e3a3b27a, scratch_unowned_entry review.** Three defects were found and fixed:

  - `..` evasion: `scratch/<session>/../x` was judged as inside the session.
    Paths are now normpath'd.
  - Bash `mkdir`, `install -d` and `cp -r` were unseen. `directory_creating_targets`
    now feeds the handler.
  - A non-str `file_path` raised TypeError.

  `touch` is still unseen, and the module docstring says so. That is acceptable
  for an advisory.

Targeted QA is green: the scratch tests in `tests/unit/daemon` and
`tests/unit/core/test_scratch_archive_apply.py`, and the unowned-entry tests;
`bash untracked/qa.sh <files>` gives QA-OK.

## Finding to decide (not fixed, possibly a design defect)

**Pressure mode is inert in a real run.** `scratch_verdict` returns
`LIVE "within its TTL"` for every entry that is not due (scratch_verdict.py
~line 357). `_actionable` requires `verdict in ACTIONABLE`, so `_pressured`
never matches a real row, and `pressured_count` is 0 in practice. The core tests
of pressure use hand-built DISPOSABLE rows that are not due, which real
classification never produces. Either the classification must give pressure
candidates their underlying verdict, or Task 5.5 does nothing. The F1/F2 safety
fixes stand either way. This needs a coordinator or owner decision; record it in
DESIGN section 13.

## Left

1. **Review the SessionStart `scratch_sweep` handler**
   (`src/claude_code_hooks_daemon/handlers/session_start/scratch_sweep.py`) for
   evasion, fail-open and crashes on odd input. It has not been read yet.
2. **Docs.**
   - DESIGN.md section 8: the creation scan peels wrappers, follows `cd`, reads
     `-c` bodies, and treats unresolved as detected. `mv`/`ln` count only when a
     source is a directory. The unowned-entry advisory now uses the same scan.
   - DESIGN.md section 13: record the outcomes of D-RULE 1-3, F1/F2 and the
     unowned-entry review, plus the finding above.
   - PLAN.md: add a task row.
   - Journal: write a journal entry via `CLAUDE/Plan/mkplan.bash --journal`.
