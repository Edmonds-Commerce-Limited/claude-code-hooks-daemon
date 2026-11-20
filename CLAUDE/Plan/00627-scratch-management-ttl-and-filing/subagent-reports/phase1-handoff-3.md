# Plan 00627 Phase 1: handoff after Task 1.7

Branch `agent-acff915e4bf3b86e6-0a26f829` (worktree `.claude/worktrees/agent-acff915e4bf3b86e6-0a26f829`), pushed. Not merged to main. Read [phase1-handoff-2.md](phase1-handoff-2.md) for Tasks 1.2 to 1.4. The venv and test-helper notes in [phase1-handoff-1.md](phase1-handoff-1.md) still apply.

## Done: Phase 1 is complete (Tasks 1.1 to 1.7)

- Task 1.5, `core/scratch_liveness.py`. `read_background_records` reports any read defect as an error and never skips a line. `entry_liveness` checks process cwds (by path equality or ancestry, never by string prefix), tracked background commands (absolute or project-relative path), and minimum age (newest of root ctime and birth).
- Task 1.6, `core/scratch_verdict.py`. `judge(walk, age=, liveness=) -> Judgement`. Order: LIVE, STUCK, REPOSITORY ("repository, not judged", never DISPOSABLE, never the R7 route), then DISPOSABLE by P1/P2/P5, else UNCERTAIN. `RepositoryMarker` is tri-state (found, none, unknown) and is set on every verdict. `NOT_EVALUATED = ("KEPT", "PROTECTED", "REFERENCED")`.
- Task 1.7, `core/scratch_sweep.py` plus `cmd_scratch_sweep` in `daemon/cli.py`: `hooks-daemon scratch-sweep [--json] [--root PATH] [--budget-seconds N] [--max-inodes N]`. A dry run that always exits 0. One budget covers the whole run, and node lists are dropped per entry. A missing root is reported and not created. A root that is a link is not followed. A root that cannot be listed produces an INCOMPLETE report. The table is bounded by `scratch.sweep.max_listed`; `--json` lists every row.
- Tests: `tests/unit/core/test_scratch_{liveness,verdict,sweep}.py` and `tests/unit/daemon/test_cli_scratch_sweep.py`. The three new core modules have 100% line and branch coverage. The read-only test snapshots every inode under the test base, project directory included, around both a table run and a `--json` run. The test tree holds an outside link, a FIFO, a refused directory and a `.git` marker.
- Smoke-tested through the real entry point (real `/proc`, real state file) with `--root tests/support`. Nothing changed on disk. The real scratch tree was not walked.

## Remaining, carried forward

- `--entry` (DESIGN.md section 10) and `scratch.sweep.extra_roots` are not wired; extra roots belong with Task 6.1.
- A missing background-records file reads as "no records". A sweep run from a worktree may read a different `untracked/` from the one the daemon writes, which silently turns that signal off. Settle this in Phase 6.
- The default budget (300 seconds, 5,000,000 inodes) is a set of flags, not a measurement. Task 8.1 should measure it on the real tree.
- For Task 3.9: the walker lists a directory by path after `lstat`, so the removal path must use descriptors (see handoff 2).
- Next: Phase 2 (git proofs). The REPOSITORY verdict is where PROTECTED, P4 and the R7 route will plug in.

## QA state

pytest, black, ruff and `mypy --strict` pass on every changed file. `./scripts/qa/llm_qa.py changed`: see the journal entry that records its result. The first attempt timed out after 600 s waiting behind another worktree's host-wide QA lock.
