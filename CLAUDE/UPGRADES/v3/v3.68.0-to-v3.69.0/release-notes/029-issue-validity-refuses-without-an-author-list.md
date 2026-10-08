# Callout: `issue-validity` refuses to run when no `approved_issue_authors` list is configured

**Plan**: 00490
**Audience**: operators

`bin/hooks-daemon issue-validity` (a single issue number, with or without `--claim`, and `--list-eligible`) now exits 4 with a message naming the missing `approved_issue_authors` option instead of treating every issue as eligible, so the issue-sdlc selection never fails open. The opt-in `github_issue_assignment_guard` hook is unchanged: with no list, its author check does not apply.
