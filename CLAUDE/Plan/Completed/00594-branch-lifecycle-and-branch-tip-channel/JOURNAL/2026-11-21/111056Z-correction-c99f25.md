## 11:10 · correction · 11:04 — 5.1 moved report lacks the commit count (N690)

Correction to the archive entry: Task 5.1 was ticked on the fixture proof, but DESIGN §3/§7.1 also specify a commit count in the moved-ref report ("moved <old>..<new> (N commits)"). `version_check._tracked_ref_lines` prints the sha range only, and the proof quotes that range with no count. The success criterion ("observes a move") is met; the count is a deviation from the design, recorded as niggle N690 and noted under Task 5.1. The plan stays archived; reopen it if the owner treats the count as required.

The revert-run logs cited by `261121-red-evidence-revert-runs.md` (`untracked/scratch/red-out/`) no longer exist on disk; that tracked report is the only record of those runs.
