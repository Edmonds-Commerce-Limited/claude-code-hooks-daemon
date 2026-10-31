# Fact check: N563 status and bare-repository limit

Diff: untracked/plan-fact-check/00474-niggles-ledger-seventeen.diff (NIGGLES.md N563). Tree: main at 3076124b0.

## REFUTED

None.

## Table

| #   | Claim                                                                                                 | Verdict                              | Evidence                                                                                                                                                                                                                                           |
| --- | ----------------------------------------------------------------------------------------------------- | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Fixed in `dc45486fa`, merged to main                                                                  | VERIFIED                             | `git merge-base --is-ancestor dc45486fa HEAD` succeeds; commit message names N563                                                                                                                                                                  |
| 2   | `GitRepo.main_worktree_root()` anchors the handler to the main checkout                               | VERIFIED                             | src/claude_code_hooks_daemon/utils/git_repo.py:555-566; worktree_create_handler.py:170 returns `str(repo.main_worktree_root())`                                                                                                                    |
| 3   | WorktreeRemove does not share the defect                                                              | VERIFIED                             | worktree_remove_handler.py:55-68 takes the path from the payload and uses cwd only as the directory to run `git worktree remove`/`prune` from, as the report states                                                                                |
| 4   | Report `subagent-reports/261031-n563-worktree-create-anchor.md` exists                                | VERIFIED                             | present in subagent-reports/ and added by dc45486fa                                                                                                                                                                                                |
| 5   | Bare-repo limit: the first `worktree list` record is the bare directory, so the handler anchors there | VERIFIED (by code and git behaviour) | main_worktree_root returns `records[0].path` unconditionally (git_repo.py:566); git lists a bare repository first in `worktree list --porcelain`. I did not build a bare repo to observe it, so the git-side half rests on git's documented output |
| 6   | "That layout has no main checkout to hold seed files, so seeding could not succeed either way"        | VERIFIED (reasoning)                 | follows from the absence of a work tree; not tested                                                                                                                                                                                                |

Minor: the diff's fix report says 337 tests passed; not re-run.
