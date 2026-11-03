## 11:30 · finding · —

DESIGN.md merged to main and fact-checked (report: subagent-reports/261103-design-fact-check.md): 40 claims, 33 verified, 5 refuted, 2 unverifiable here. All five refutations are corrected in DESIGN.md:

- the stop-guard priorities are per event (Stop: after release_blocker 8 and the priority-9 recorders, before auto_continue_stop 10; SubagentStop: after subagent_handoff_gate 11);
- the optimiser's strict-preset suggestion is new work (the checklist judges handlers only and has no OPTIONAL verdict);
- no existing parser returns a created branch name, so the creation-route parser is new work;
- `worktree-reap --base-branch` is at cli.py:12440;
- `for-each-ref --merged` lists the target ref itself, which the inventory drops.

Unverifiable here: whether `check-config-migrations` warns on a renamed key, and whether a non-zero WorktreeCreate exit aborts the creation. Both are to be proven by a test in the build task that relies on them.
