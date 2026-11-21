## 14:31 · action · — — Tasks 3.5 and 3.6 merged

Tasks 3.5 and 3.6 merged to main.

3.5: the worktree-removal deny now separates dirty files from ignored blockers. For the ignored ones it advises looking first, keeping what matters, and deleting what is disposable in a separate command. A delete chained in front of the removal stays denied, and the deny says it was not counted. The agent's first wording said only "delete X first". I changed it to look first and keep what matters, because the guard exists so work is never lost, and scratch can hold real notes.

3.6: the installer removes its settings backup when the merge left the file byte-identical to it. The escalated and no-interpreter paths keep the backup, because their warnings name it.

The rc review round-3 fix (false startup notice on a clone without a local default branch, side-effect-free stale check in the upgrade, warning when the notice has no recipient) is still in progress on its branch.
