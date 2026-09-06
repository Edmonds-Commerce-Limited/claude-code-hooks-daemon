# DO NOT EDIT - Hooks Daemon Internal Tests

**IF YOU ARE WORKING ON A PROJECT THAT HAS HOOKS DAEMON INSTALLED — YOU MUST
NOT EDIT ANYTHING IN THIS FOLDER.**

This is the daemon's own test suite: an upstream dependency, not part of your
project. Editing files here breaks your installation, is overwritten on the
next daemon update, and creates conflicts that prevent future upgrades.

## Do This Instead

- **Tests for your custom handlers** — project-level handlers support
  co-located tests (`test_*.py` next to each handler under
  `.claude/project-handlers/`); run them with
  `.claude/hooks-daemon/bin/hooks-daemon test-project-handlers --verbose`.
  See [Project-Level Handlers Guide](../CLAUDE/PROJECT_HANDLERS.md).
- **Found a bug** — do NOT fix it here. Write a report to
  `untracked/scratch/` and ask your human to submit it upstream, following
  the [Bug Reporting Guide](../BUG_REPORTING.md). That directory is inside the
  working tree, so the report survives a container restart, and it is
  gitignored, so it never reaches review. A path outside the repository is
  refused by `project_containment`.
