# DO NOT EDIT - Hooks Daemon Internal Tests

**IF YOU ARE WORKING ON A PROJECT THAT HAS HOOKS DAEMON INSTALLED — YOU MUST
NOT EDIT ANYTHING IN THIS FOLDER.**

This is the daemon's own test suite: an upstream dependency, not part of your
project. Editing files here breaks your installation, is overwritten on the
next daemon update, and creates conflicts that prevent future upgrades.

**Unless this repository IS the daemon.** In self-install (dogfood) mode the
daemon's tests and the project are the same checkout, so adding a regression
test here is the normal way to work — see
[SELF_INSTALL.md](../CLAUDE/SELF_INSTALL.md). The heading above is addressed to
a CLIENT project that installed the daemon under `.claude/hooks-daemon/`. Same
caution as the sibling note in [../src/CLAUDE.md](../src/CLAUDE.md): check which
case you are in before treating an instruction to add a test here as wrong.

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
  gitignored, so it never reaches review. `project_containment` denies an
  ordinary redirect outside the repository, but it does not cover a path
  passed to a script as a plain argument — treat it as a backstop, not a
  guarantee.
