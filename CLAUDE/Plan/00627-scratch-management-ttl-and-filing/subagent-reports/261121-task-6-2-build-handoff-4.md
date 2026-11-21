# Task 6.2 build: handoff 4

Ruling: `/workspace/untracked/agent-reports/261121-task-6-2-ruling.md`. Previous: `261121-task-6-2-build-handoff-3.md`. Worktree `/workspace/.claude/worktrees/agent-acff915e4bf3b86e6-0a26f829`, branch `agent-acff915e4bf3b86e6-0a26f829`. Tests: `untracked/py/bin/python -m pytest -q -p no:cacheprovider <files>`.

## Done (steps 3-5, minimum set)

- `8daa1f302`: red tests `tests/unit/daemon/test_worktree_evacuate.py`.
- `176696728`: `daemon/worktree_evacuate.py` plus the wiring.
  - `confirm_evacuate_interactively(relative, gate, *, stdin, stdout, prompt_stream)`: both streams must be TTYs, and the phrase is exactly `evacuate <relative path>`.
  - `evacuate_scratch(main, state, *, reap, seams) -> Evacuation(evacuated, lines)`.
    - Order: preconditions, then tar (`--reap` only), then a fresh classification and `evacuation_gate`, then the question, then `ArchiveStore.open` + lock, then one `apply_sweep` (`expire=False`, `empty_session_hours=None`, `pressure=gate.consent`).
    - The preconditions: main checkout, a fresh porcelain listing, not prunable or locked, the path is relative to main, a real scratch directory, no refusal from `resolve_sweep_root`, and a finite TTL.
    - Every outcome must be `archived`, the run complete, and there must be no fewer outcomes than gate entries. Otherwise it KEEPs, and the `ARCHIVED ... restore` lines are still printed.
    - A dry run prints `OFFER <name>: ...` with the entry names. It never asks and never opens the store.
  - `EvacuateSeams(confirm, wall_clock, process_cwds, git_runner, tar_path)`, passed to `cmd_worktree_reap(evacuate_seams=...)`.
  - `cmd_worktree_reap`: when `worktree_evacuate.only_scratch(blockers)` holds, it calls the evacuation, prints its lines, and re-runs `worktree_blockers` if `evacuated` is true. The existing `KEEP ... blockers_line` still prints whenever blockers remain.
  - `_ScratchSources.extra_background` plus `background()` merge the record files, and an error in any one file is an error for all. Both `classify` and `_scratch_apply`'s `live_in` use it. The evacuation passes main's `background_file` as the extra file.
- 13 new tests are green.
  - The four minimum tests: the happy path with a not-due entry, each archive restored byte for byte from main after the reap; no TTY; session children (never asked, no store); a dry run with an inode snapshot.
  - The question's TTY and phrase matrix, the prompt text, and a check that no argparse key contains `confirm` or `yes`.
- Unit 1 test `_line_for` now takes the LAST line naming the worktree. The evacuation KEEP detail lines print first; behaviour is unchanged.
- Checks run: `test_cli_worktree_reap*.py`, `test_cli_scratch*.py`, `test_scratch_archive_remove.py` (deletion surface) are green; black, ruff and pyright are clean; error-hiding and semgrep are clean on the new module.

## Test-writing trap (important)

An entry's activity is the later of its mtime and its ctime, and a ctime cannot be set. So the only way to have a not-due entry beside a due one is an mtime a few seconds in the future. GNU tar warns on a future mtime, and restore refuses that warning. `_due_and_young` returns `now = base + 24h + 1s` and sets `young.txt` to `base + 3s`. `_wait_for_young_mtime` sleeps until that time has passed before restoring. Reuse these helpers.

## Not done (the ruling's remaining test list)

Each is a real-repository test in `test_worktree_evacuate.py`. Use the `_reap(..., confirm=...)` seam.

- Wrong phrase and end of input through the real default confirm, using monkeypatched TTY `_Stream`s.
- Background records: one in the main file and one in the worktree file, each naming the entry, each blocking. The file path is `_daemon_untracked_dir(repo) / "background-processes.jsonl"`.
- A not-due inode replaced inside `confirm` (delete and recreate `young.txt`): not packed, the worktree kept.
- An entry created inside `confirm`: not packed, and the re-judge keeps the worktree.
- `after_step` failures converging. There is no seam yet; one would need adding to `EvacuateSeams` and passing to `apply_sweep`.
- Retention: a not-due entry gets the TTL remainder plus its verdict's retention.
- Refusals before the store exists: a `"*"` root, a linked scratch root, a locked or prunable worktree, and a run from a linked worktree.
- Store busy; no tar (`EvacuateSeams(tar_path="/nonexistent")`); the housekeeping step with no terminal; and a due main-store archive that survives an evacuation.
- The property test.
- Superseded by the root-only decision, so do not build them: the session-evacuation tests (an emptied session directory removed, a session-only worktree reaped, a session child restored).

## For the documents builder

- The printed restore command needs `main/untracked/scratch` to exist (`_scratch_store_refusal`).
- Unit 1's dry-run output for a scratch-only worktree now carries an `OFFER` or `KEEP ... evacuation refused:` line before the KEEP line.
- Name the future-mtime trap only if DESIGN.md discusses testing.
