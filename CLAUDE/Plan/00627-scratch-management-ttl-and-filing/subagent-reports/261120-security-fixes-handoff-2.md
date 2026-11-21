# Handoff 2: remaining security-review fixes (F-BYPS 1 and 2), probes, cleanup

Branch `agent-acff915e4bf3b86e6-0a26f829`, head `85d88ca41` (pushed). Supersedes the "Left"
list of `261120-security-fixes-handoff.md` (read that file's item 1 and 2 designs: they still
stand). origin/main was merged at the start (already up to date).

## Done since handoff 1 (each journalled, committed, pushed)

- D-EXEC unit journalled (it was committed in 8b7095442).
- F-BYPS 4 (`ee7d1ec53`, `scratch_verdict.py`): P2-by-venv needs regular `pyvenv.cfg` +
  `bin/python*` or `Scripts/` + `lib/` or `Lib/` tree; covers only `pyvenv.cfg`, `.gitignore`,
  `CACHEDIR.TAG` and the layout dirs (`VENV_LAYOUT_DIRECTORIES`); a top-level regular file
  named like a layout dir is a sibling. DESIGN 3.2 updated.
- F-BYPS low (`77cb92a80`): `scratch_liveness.read_process_cwds` (skips only exited pids, names
  unreadable ones), `LivenessInputs.unreadable_pids`, `scratch_sweep.liveness_unknown_reason`
  (incomplete reason), `judge(liveness_unknown=...)` -> STUCK after the TTL rung. CLI uses it.
  DESIGN section 4 updated. `worktree_reaping.default_process_cwds` untouched.
- F-BYPS 3 (`85d88ca41`, `scratch_references.py`), coordinator's ruling: for a root deeper than
  `untracked/<name>` the pattern is `<root>[class]*`; a match equal (stripped/normpath) to the root
  goes to `ReferenceSet.root_sites`, added to every entry by `for_entry`. Ancestor and prefix-
  sibling mentions name nothing; default root unchanged. DESIGN 3.4 updated.

## Left

1. F-BYPS 1 + classifier half of F-BYPS 2 in `core/scratch_repos.py`, exactly as handoff 1
   item 1 (admin dirs `<common>/worktrees/<id>/gitdir` read with `read_small_regular_file`;
   outside target or missing worktree dir -> PROTECTED, unreadable -> BROKEN/STUCK; also for
   STANDALONE; each admin HEAD added to a RELATED clone's tip set). Tests: `--detach` outside
   worktree with unpushed commit on a clone; standalone `sa` with a linked worktree elsewhere;
   in-entry detached worktree whose dir was removed.
2. F-BYPS 2 cross-entry post-pass in `core/scratch_sweep.py`, as handoff 1 item 2.
3. DESIGN 3.3 (new rows: linked worktrees of a nested repo, cross-entry pass) and 13 (F1/F2 rows;
   mark the reflog/ORIG_HEAD row still open). Journal each unit.
4. Re-run probes under `timeout`, `PYTHONPATH=<worktree>/src`:
   `/workspace/untracked/scratch/fbyps-00627/bin/probe.py` and the `d-exec-probe-627*` scripts.
   Expected after all fixes: `cl` PROTECTED, `sa` PROTECTED, `probe` UNCERTAIN, `sub` sub-root
   entries REFERENCED. Not yet re-run for 3/4/low.
5. Then `rm -r` only `/workspace/untracked/scratch/d-exec-probe-627*`,
   `/workspace/untracked/scratch/fbyps-00627`, `/workspace/untracked/scratch/lstree`.

Test command: see handoff 1 ("Running tests"). Targeted QA only; do not merge to main.
