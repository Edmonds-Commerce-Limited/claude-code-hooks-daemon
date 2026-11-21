# Post-merge minor items, handoff

Worktree `/workspace/.claude/worktrees/agent-acff915e4bf3b86e6-0a26f829`, branch
`agent-acff915e4bf3b86e6-0a26f829`.

## Step 1: merge

`origin/main` (662750cf4) was a strict descendant of the branch, so the merge was a
fast-forward with no conflicts. Every integration fix is kept exactly as main has
it. The daemon was restarted and is RUNNING.

## Step 2: done (each commit pushed)

There was no written text for the two minor F-BYPS items in the plan folder. They
were read from the code as follows.

- **998aac2dd: the prompt count is binding.**
  - The `--apply` question names `pressured_count` of the pre-consent
    classification. `apply_sweep` then re-classifies, so an entry that turned
    idle (or appeared) while the question waited was packed beyond the number
    the human agreed to. `test_the_run_packs_no_entry_beyond_the_count_consented_to`
    was RED before the fix: the prompt said 0 and the run packed 3.
  - New `consent_to(report, pressure)` sets `Pressure.consented` to the counted
    `<report root>/<name>` set, covering the root and session children.
    `_pressured` refuses a not-due entry outside that set. `_scratch_pressure`
    in the CLI always binds. `None` (unbound) remains only for core tests.
  - The count and the set come from one function (`_pressured_paths`).
  - DESIGN section 13 row updated.
- **dbacaec56: a skipped TTL-held entry reports its held verdict.**
  - `_apply_row` reported `row.verdict`, so a TTL-held skip read `LIVE`. It now
    reads `"<ttl_hold> (not yet due: within its TTL)"`.
  - A liveness LIVE still reads `LIVE`.
  - The DESIGN section 8 pressure bullet was updated.
- **68f32fb6c: hold tests under pressure.**
  - `TestHoldsStillProtectUnderPressure` in `tests/unit/daemon/test_cli_scratch_worktrees.py`
    runs the real classifier and `--apply` at block. Each of these leaves the
    entry in place and gives an exact reason:
    - entry keep marker: `KEPT`
    - tracked reference: `REFERENCED`
    - session keep marker: `KEPT`
    - process in the session: `LIVE`
  - Positive controls pack the same entry when there is no hold, in the root
    and in a session.
  - Core tests in `TestPressureMode` cover the claim-time re-checks under
    pressure: a reference read at the claim, and a session keep marker added
    after classification. Each has a positive control.
- **Mutation check.** These hold tests went RED under each of these mutants,
  then were reverted (19 failures; a clean revert was confirmed by an empty
  `git diff src/`):
  - `_safe` forced True
  - `_pressured` accepting any `ttl_hold`

## Observation (not changed)

Children of a session directory that is still within its own TTL are held
LIVE whole (`_carried_down`). Pressure therefore reaches session children only
after the session directory itself is past its TTL. This is consistent with the
"a young session directory is held whole" design, but an owner may want to
know that pressure barely reduces session-directory load.

## QA

The following are green:

- black, ruff, mypy and pyright on the touched files
- the touched modules' tests, 254 passed:
  - `test_scratch_archive_apply`
  - `test_scratch_archive_adversarial`
  - `test_scratch_sweep`
  - `test_cli_scratch_apply`
  - `test_cli_scratch_worktrees`
  - `test_cli_scratch_status`

`llm_qa.py error_hiding semgrep pyright` reported 0 error_hiding and 0 semgrep
violations. Pyright found 2 type errors in the new test code: a lambda returning
int assigned to `after_first`, and `len()` of an Optional. Both are fixed in the
final commit, and pyright on both test files now gives 0 errors.

## Not touched

Task 6.2, Task 6.3 and Phase 8 (owner decisions).
