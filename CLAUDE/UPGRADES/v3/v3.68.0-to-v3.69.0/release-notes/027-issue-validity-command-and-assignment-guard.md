# Callout: `issue-validity` checks and claims a GitHub issue in code, and an opt-in guard enforces it

**Plan**: 00490
**Audience**: operators

`bin/hooks-daemon issue-validity N [--claim] [--json]` now answers, deterministically and with one `gh` call, whether an issue may be worked on: assigned to the signed-in account (and, with `--claim`, claims it when unassigned) and opened by an approved author, with exit codes the issue-sdlc runbook acts on; `--list-eligible` lists open issues by approved authors and refuses to list when no list is configured. The author list is the `approved_issue_authors` option of the new, opt-in `github_issue_assignment_guard` handler, which denies issue-tied work on an unclaimed, foreign or unapproved-author issue and only advises when `gh` cannot answer. The hard-coded author table in the issue-sdlc runbook is gone.
