# Callout: a QA gate whose tool errored or scanned nothing now fails

**Plan**: 00466
**Audience**: handler authors

The daemon repository's QA gates no longer read a tool error as a clean pass:
a semgrep rule that times out or reports any `errors[]` entry fails the gate
naming the rule and file, and bandit, ruff, black, deptry, shellcheck, pyright
and the Python checkers now fail when their tool crashed, could not read a
file, or produced no report. The path-scanning checkers (`github_urls`,
`shell_audit`, `skill_refs`, `doc_truth`) also judge skip-listed directories
below the scan root only, so a run from a linked worktree under
`untracked/worktrees/` scans the tree instead of reporting clean over nothing.
