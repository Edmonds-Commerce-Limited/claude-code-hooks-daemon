# Task 6.2 build: handoff 2

Ruling: `/workspace/untracked/agent-reports/261121-task-6-2-ruling.md`. Handoff 1: `261121-task-6-2-build-handoff-1.md`.
Worktree: `/workspace/.claude/worktrees/agent-acff915e4bf3b86e6-0a26f829`, branch `agent-acff915e4bf3b86e6-0a26f829`, head `e77c7b87c` (pushed).
Run tests with the worktree's own venv: `untracked/py/bin/python -m pytest ...` (`/workspace/.venv` imports main's `src/` and the conftest refuses it).

## Coordinator decision (binding): option 3

Evacuation in `worktree-reap --reap` handles ROOT-LEVEL entries only. Any worktree whose scratch holds a session directory (`s-*`, even one holding only its manifest) is KEPT, with the human's next step named. Restore's destination rules are not changed in this plan. Record the limit and the follow-up (restore creating the session directory) as a niggle in the open ledger and in DESIGN.md.

## Done

- `e77c7b87c`: `tests/unit/daemon/test_cli_scratch_restore_after_worktree_gone.py`. It archives an entry through a linked-worktree `scratch-sweep --apply`, removes the worktree, then restores from main. A root entry restores byte for byte. A session child is refused: `the session directory 's-...'` is not a directory here. Both pass; the second pins the refusal, which is the gap. Its docstring says why evacuation excludes session children, and that the test flips the day restore creates the directory. I read "write the red test first" as: observe that the restore does not happen, then commit the test pinned to the refusal.
- Unit 2 and Unit 3 are not started. No source change since Unit 1.

## Build order for the next agent (wire last, so every commit keeps the worktree)

1. **Core gate**, a new module (test file first for the TDD gate), e.g. `core/worktree_evacuation.py` plus `tests/unit/core/test_worktree_evacuation.py`. A pure function from `SweepReport` to blocker strings:
   - the report is incomplete: blocker;
   - `report.sessions` is non-empty, or any row's name satisfies `is_session_dir_name`: blocker, "a session directory: evacuation handles root-level entries only; restore cannot recreate it (DESIGN section 13)";
   - each row must be `walk_complete` and either due with verdict in `ACTIONABLE`, or not due with `ttl_hold in ACTIONABLE`. Anything else is a blocker, listed by name and `pending_verdict`. Minimum age is a liveness reason, so it gives LIVE with no `ttl_hold`, which is a blocker, as the ruling wants.
   - A consent constructor: `consent_to(report, Pressure(idle_hours=0, ttl_hours=ttl))`.
   - Birth stamp check: the bound `consented` must equal the set of not-due rows' keys. A mismatch is the "no birth stamp" blocker.
   - Due rows: pre-check `birth_stamp` readability, and a foreign owner with `walk_tree` and `refuse_foreign_owner` (from `scratch_archive_claim` and `scratch_archive_pack`), so the gate stays all-or-nothing BEFORE any pack.
2. **`ApplySettings.expire: bool = True`.** `apply_sweep` skips `_expire` when it is False. Test: a due archive of the main checkout's root survives an evacuation-style run.
3. **`confirm_evacuate_interactively`** in `daemon/cli.py`, beside `confirm_apply_interactively` (line ~7089), with the same TTY rules. The phrase is `evacuate <worktree path relative to the main checkout>`. The prompt names the worktree, the entry count, the not-due count, the counts by verdict, that archives go to the main store with their restore commands, and that the worktree is then removed. Test seam: a keyword parameter.
4. **Wiring in `cmd_worktree_reap`** (`daemon/cli.py` ~10966; the blockers check is at ~11120). Offer evacuation only when the blockers are exactly `("untracked/scratch/",)` (`_expand` opens `untracked/` one level only).
   - Preconditions: `repo_root/.git` is a directory and `GitRepo.resolve_for(repo_root).main_worktree_root() == repo_root`; the target is from this run's porcelain listing, not prunable or locked; `<wt>/untracked/scratch` is a real directory; `resolve_sweep_root(..., project_root=wt)` has no `refusal` or `apply_refusal`; `ttl_hours` is not None.
   - Classify with `_ScratchSources(repo=wt, store_checkout=repo_root, ...)`. Liveness must read BOTH checkouts' `background-processes.jsonl`: add a field to `_ScratchSources` (e.g. `extra_background: tuple[Path, ...]`), read it in `classify` and in the `entry_live` closure.
   - Find tar with `find_gnu_tar` before the store opens. Run the gate, then the question. No TTY means KEEP, naming `hooks-daemon worktree-reap --reap --only <name>` (build it with `daemon_cli_command_for_docs`).
   - Then `ArchiveStore.open(<main>/untracked/scratch-archive)` with `store.lock()`, and `apply_sweep` ONLY (no `apply_sessions`). Settings: `root=Path(sweep_root.path)` (the SAME path the report root uses, or `_consent_holds` keys miss), `original_prefix="untracked/scratch"`, `checkout=str(wt)`, `pressure=bound consent`, `expire=False`, `empty_session_hours=None`.
   - Re-judge: every outcome must be `archived`. Then `worktree_blockers` again; only `()` reaches `reap_worktree`. If the empty scratch root still blocks, STOP and hand off; do not widen a guard.
   - The dry run (no `--reap`) prints what would be packed and never asks.
   - New seams are needed for the scratch wall clock and process cwds (fresh entries sit under `min_age_minutes`), and for the confirm function.
5. **Tests on a real repository** (`tests/support/scratch_tree.build_git_project` plus `git worktree add` under `.claude/worktrees/agent-*`, or use the Unit 1 fixture style). Cover the ruling's Unit 2 list minus its three session-directory tests, which option 3 replaces with one: session children present means no question, zero archives, KEEP, next step named. Also: restore byte for byte from main after the reap, expire skipped, both background files block, no TTY, wrong phrase, end of input, a replaced not-due inode, an entry created after the question, `after_step` failures converging, retention, the `"*"`/link/locked/prunable/linked-run refusals, store busy, no tar, the housekeeping step, and a dry run that changes no inode. Include the deletion-surface inventory test in targeted runs: `grep -rln "deletion" tests/unit | grep -i surface`.
6. **Unit 3** as the ruling says (`core/branch_cleanup.py` `cleanup_after_merge`, the `held_by is not None` branch, ~line 719). See how the handler renders `commands`, so the line reads as "a human at a terminal" and not as an agent instruction. Word it so it stays true for a worktree with session children, which the command keeps.
7. **Documents:**
   - DESIGN.md section 11 and section 13: the Unit 1 finding, the evacuate gate, option 3's limit and its niggle, and evacuation added to the F-BYPS F2 row.
   - PLAN.md Task 6.2: "evacuate from `worktree-reap --reap` only; `cleanup_after_merge` advises".
   - The niggle in the open ledger (see `CLAUDE/Plan/README.md`). Name the existing exposure too: a linked-worktree `scratch-sweep --apply` already archives session children that become unrestorable once the worktree is removed. The human's next step must therefore be filing or deleting by hand, never "run `--apply` in the worktree".
   - The `--reap` help text, a release note, the `get_claude_md` of `cleanup_after_merge`, HANDLER_REFERENCE (regenerate it with the generator), and a journal entry through `mkplan.bash --journal`.
8. At the end, run `scripts/qa/llm_qa.py changed` on a quiet tree. Add `--allow-unmapped` only if the sole failures are the too-broad unmapped files.

## Checks run in this session

- `untracked/py/bin/python -m pytest -q -p no:cacheprovider tests/unit/daemon/test_cli_scratch_restore_after_worktree_gone.py`: 2 passed.
- No `llm_qa.py` run (no source change).
