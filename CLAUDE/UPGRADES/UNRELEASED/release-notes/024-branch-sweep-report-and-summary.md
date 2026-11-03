# Callout: `hooks-daemon branch-sweep` reports every branch, and the SessionStart branch line now names unpushed work

**Plan**: 00558
**Audience**: operators

`bin/hooks-daemon branch-sweep` lists every local and remote branch by state, the actionable groups first: CONTAINED NOWHERE (commits no remote ref holds, with the `git push -u` that secures them), merged but not deleted (with the `bin/hooks-daemon delete-branch` command, which proves the merge again before it deletes), patch-equivalent, dormant (with age and where the commits live), live work, parked, and not yet classified (with the reason). It ends with the open-work count against `branches.wip.cap`. `--json` prints the full records with the keys listed in `branch-sweep --help`; `--all` adds the default, integration-line, protected and exempt branches. It is a report: exit 0 whatever it finds, 1 only when it cannot run (not a git repository).

The `branch_count_advisor` SessionStart line is replaced by `branch_sweep`. It names a branch contained nowhere on every session start (new, resume, compact), and on a new session the dormant branches, the merged-not-deleted count and the open-work count when it reaches the cap. It is silent when there is nothing to report. The old key still works: `enabled: false` under `branch_count_advisor` silences the new summary, and its `max_open_branches` / `behind_main_threshold` options are read for one release while `branches.wip.cap` / `branches.sweep.behind_threshold` are unset, with a deprecation line until you move them.

`delete-branch --protected-ref` and `worktree-reap --base-branch` now default to the configured default branch (`branches.default`, `auto` asks git) instead of a literal `main`; an explicit flag still wins.

On upgrade: rename `branch_count_advisor` to `branch_sweep` and move its two options under `branches:`. Then run `bin/hooks-daemon branch-sweep` once to see what is there.
