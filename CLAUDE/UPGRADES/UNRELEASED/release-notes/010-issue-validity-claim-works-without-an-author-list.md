# Callout: `issue-validity N --claim` works when no approved author list is configured

**Plan**: 00544
**Audience**: operators

`bin/hooks-daemon issue-validity` used to exit 4 for every mode when `approved_issue_authors` was unset, while the `github_issue_assignment_guard` deny text told you to run `issue-validity N --claim` in exactly that configuration, so the one fix the guard named could not be run. The refusal now applies only to `--list-eligible` (autonomous picking with no list would make every author eligible; it still exits 4 and makes no `gh` call). A single-issue check or `--claim` acts on an issue you already chose, so it proceeds and prints `[n/a] author: no approved issue authors configured`. A configured list still rejects an unapproved author. No config change is needed. (reported as issue #129)
