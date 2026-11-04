## 19:55 · action · —

Merged `worktree-558-force` into main: Task 4.1 (lossless force removal) and the same-command half of Task 4.5 (`R-GIT-EVACUATE-THEN-DESTROY`). Its QA on 47fc9b859 was green apart from the accepted "too-broad" notice. The one later commit, an import reorder, passed ruff, black and 167 targeted tests on main. Release notes 097 and 098 are renumbered to 028 and 029.

Dogfood: removing the force worktree was refused by the new R-GIT-WORKTREE-REMOVE-FORCE, which listed 8 ignored capture files (`untracked/scratch-*.txt`). I inspected them (QA, pytest, mypy and explain-rule captures, nothing unique), deleted them deliberately, and the plain removal then passed. A single command that deletes and then removes is still refused, because the guard judges before the command runs. That is correct: the deletion is a separate, deliberate act.

Task 4.3 dispatched as `p558-dormancy` on `worktree-558-dormancy` (brief `untracked/scratch/brief-558-dormancy.md`): the 30-day block and 14-day context line in `creation_verdict`, the `branch-park` CLI, the optimiser OPTIONAL line and the docs. The per-Stop noisy line goes with Task 4.4.
