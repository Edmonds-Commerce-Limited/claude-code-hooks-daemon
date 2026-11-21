# Task 6.2 build: handoff 5

Ruling: `/workspace/untracked/agent-reports/261121-task-6-2-ruling.md`. Previous: `261121-task-6-2-build-handoff-4.md` (the future-mtime trap and the `_due_and_young` helpers). Worktree `/workspace/.claude/worktrees/agent-acff915e4bf3b86e6-0a26f829`. Tests: `untracked/py/bin/python -m pytest -q -p no:cacheprovider tests/unit/daemon/test_worktree_evacuate.py` (26 green).

## Done in this session

- `073235fb6` adds two things.
  - **Real bug fixed.** A rerun after a kill that landed after the record append was refused forever. The leftover `.sweeping-<name>` claim is a gate row, but `apply_sweep` finishes it through `_resume` and never lists it in `entries`. `_pack` counted it as "not acted on".
  - The fix: a resumed claim with outcome `removed` now counts as archived and prints its `ARCHIVED ... restore` line. `renamed-back` is accepted, and that entry must then come back `archived` as an entry. Any other resume outcome keeps the worktree.
  - New seam `EvacuateSeams.after_step`, passed to `apply_sweep`.
  - `TestConvergence` covers a kill after claim, pack, append, and after the last archive. The append and after-the-last-archive cases were seen red before the fix.
- Next commit (after `073235fb6`) adds these tests:
  - `TestThroughTheRealPrompt`: wrong phrase, bare word, empty line, end of input. The streams are monkeypatched to TTY `_Stream`s and the test asserts the prompt was written. A positive control (the right phrase reaps) is included.
  - `TestBackgroundRecords`: a record in the main or the worktree file. These call `evacuate_scratch` directly, because through the CLI the worktree's own record file sits under its `.claude/`, which is itself a non-scratch blocker.
  - `TestChangedWhileAsked`: an entry replaced by a rename-over while the question is open, and an entry created while it is open.
  - New helpers: `_state`, `_seams(now, confirm=..., **overrides)`, `_store_records`, `_store_ids`, `_restore_all`, `_all_due`, `_due_clock`, `_keep_text`.
- Mutations seen red, each reverted:
  - The phrase check always true: the 4 prompt tests fail.
  - `extra_background=()`: the main background test fails.
  - `_pack` ignoring entries that are not archived: both changed-while-asked tests fail.
  - `_consent_holds` returning True: the replaced test fails.

## Left (the ruling's list)

- Retention: a not-due entry's `expires_at` is the TTL remainder plus its verdict's retention; a due entry's is the verdict retention alone (`scratch_archive_apply.py` around line 782). Read the records with `_store_records`.
- Refusals before the store exists. Call `evacuate_scratch` directly with `_state`, because the CLI's `ownership_refusal` shadows a locked worktree:
  - a `"*"` root (a config in main's `.claude/hooks-daemon.yaml`)
  - a linked scratch root
  - locked or prunable, through the `git_runner` porcelain seam
  - a run from the linked worktree
- Store busy: hold `ArchiveStore.open(...).lock()` during the run, after checking it raises rather than waits.
- No tar: pass `_reap(..., tar_path="/nonexistent")`.
- The housekeeping step `worktree-reap-reap` with no terminal. Check how age is satisfied, and assert that a scratch-free worktree is REAPED and that a worktree with scratch is kept with the `--only` command.
- A due main-store archive survives an evacuation. Use `_all_due`, run the evacuation clock past the main archive's expiry, and mutate `expire=False` to `True` to see it red.
- The property test: seeded `random.Random` over 10-15 seeds, with no hypothesis package. The oracle comes from an independent fresh classification. Assert that at least one seed reaps.
- Not built, superseded: the session-evacuation tests.

## Notes

- A kill after the last archive leaves an archive whose id no run ever printed (the first run died before printing). It is in the store, and `scratch-sweep status` lists it. The rerun prints only the resumed one.
