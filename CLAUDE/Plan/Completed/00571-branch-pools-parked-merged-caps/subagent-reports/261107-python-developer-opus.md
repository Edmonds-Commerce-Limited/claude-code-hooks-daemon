# Plan 00571 Phases 1 and 2: sub-agent report (python-developer, Opus)

Branch `worktree-plan-00571-branch-pools`. One commit per task, each says "Addresses #165".

| Task                                    | Commit      | State                                                 |
| --------------------------------------- | ----------- | ----------------------------------------------------- |
| 1.1 DESIGN.md                           | `548196299` | done                                                  |
| 2.1 accumulating `delete-branch` bundle | `8503fc0c6` | done                                                  |
| 2.2 `branch-sweep --clean --remote`     | `b0aaf25ec` | done (see 2.7)                                        |
| 2.3 merged listings name `--clean`      | `ccaac42f4` | done                                                  |
| 2.4 reap reports its skips              | `3bac85d8b` | done                                                  |
| release note `005-...`                  | `6c9ac0787` | done                                                  |
| 2.5 N581 work-queue hand-over           | `6ed2f590a` | done                                                  |
| 2.6 IssueSdlc doc                       | none        | skipped (the coordinator is doing it)                 |
| 2.7 route through `utils/remote_refs`   | none        | NOT done: 00570 was not on main yet                   |
| Phase 3 pools                           | none        | not started, as instructed; DESIGN.md is the hand-off |

## Decisions, and where I differed from the brief

- **Remote proof is ancestry only, not patch-equivalence.** The brief asked for both the
  local path's patch-equivalence and "the guard's own check so they never disagree". These
  two asks conflict. The guard (`destructive_git`) accepts ancestry only, so an agent's
  `git push --delete` of a patch-equivalent branch is denied. I kept the guard's rule:
  `--remote` lists a patch-equivalent remote branch as skipped. The coordinator's later
  message confirms that ancestry is the rule.
- **The guard's proof moved to `core/remote_branch_proof.py`.** Both the guard and
  `clean_sweep` call `prove_remote_merged`. The guard's messages and their order are
  unchanged. Two guard test fixtures now patch `remote_branch_proof.run_git` as well.
- **`--bundle PATH` refuses an existing file**, with exit 2 before classifying. With that
  rule, the existing "git refused every delete, unlink the bundle" path only ever removes
  the run's own file, and the CLI now says that no bundle was kept because nothing was
  deleted.
- **Remote deletes push under `--force-with-lease=refs/heads/<n>:<proven tip>`**, and the
  result is read per ref from `--porcelain`. The remote tips are bundled as
  `refs/remotes/<remote>/<n>` in the same bundle as the local branches
  (`delete_branches(extra_bundle_refs=...)`). That bundle is kept even when no local branch
  was deleted.
- **2.5 is in the gate, not the guard.** `decide_stop` drops findings for branches named by
  a `running` record in `<daemon untracked>/work-queue.json`, but only on the main thread.
  It adds a "handed over" context line. A sub-agent's own stop is still judged.

## Task 2.7 (for the reconcile at merge)

`remote_branch_proof.live_remote_tips` is the only `ls-remote` call. It is the guard's
existing chunked, per-name `ls-remote`, moved here with no change in behaviour, so it is
not a second module design. To route it through the shared helper, replace its body with
`list_remote_refs(directory, remote)` filtered to `refs/heads/<name>`. Treat a `failure` as
"nothing confirmed", which fails closed exactly as today. Then delete `LS_REMOTE_CHUNK` and
update `test_destructive_git_remote_delete_batched.py`, whose fakes answer per-name
patterns and assert the chunk size.

## RED evidence (quoted from each run before its fix)

- 2.1: `ImportError: cannot import name 'new_bundle_path'`. Then, after the helper alone:
  `6 failed, 3 passed`. These include \`test_an_existing_file_is_refused_and_nothing_is_deleted
  - AssertionError: assert 0 == 2`(the old default silently overwrote the file) and`TypeError`on a`None\` default bundle.
- 2.2: `ModuleNotFoundError: No module named 'claude_code_hooks_daemon.core.remote_branch_proof'`,
  then `TypeError: clean_sweep() got an unexpected keyword argument 'remote'` (x9),
  `CleanupReport.__init__() got an unexpected keyword argument 'deleted_remote'`, and the CLI
  `KeyError: 'remote'`.
- 2.3: `8 failed`, for example the sweep `StopIteration` (no `--clean` line),
  `assert '.claude/hooks-daemon/bin/hooks-daemon branch-sweep --clean' in ...` (cap deny),
  and `StopFinding.__init__() got an unexpected keyword argument 'on_remote'`.
- 2.4: `ImportError: cannot import name 'collect_skipped_merged_branches'`.
- 2.5: `test_the_coordinator_is_not_held_on_a_running_agents_branch - assert 'BRANCHES LEFT BEHIND: ...` (the stop was denied).

## Verification

- pytest on every touched file is green. Last runs: 137 passed (core cleanup, proof, CLI
  sweep, delete-branch), 684 passed (all `destructive_git` tests), 259 passed (sweep,
  creation, stop gate/guard, stop handlers), 79 passed (reap), 20 passed (stop gate after
  2.5).
- ruff, black and `mypy --strict` are clean on every changed source file.
- `llm_qa.py changed` did NOT complete within this dispatch. Both attempts waited on the
  host-wide QA lock, held by other worktrees. The coordinator's gate needs to cover it.
- Not done: PLAN.md task checkboxes. PLAN.md was being edited on main (Tasks 2.5 and 2.7
  added there), so I left it to avoid a conflict.
