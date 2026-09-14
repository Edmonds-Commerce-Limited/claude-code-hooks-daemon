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
- **Found a bug** — do NOT fix it here. Use the `hooks-daemon` skill with args
  `issue-report`, or read the [Bug Reporting Guide](../BUG_REPORTING.md): it
  establishes there is
  a defect before anything is filed, then generates a body that carries no
  config, logs or paths from your tree. Working notes go under
  `untracked/scratch/` — inside the working tree, so they survive a container
  restart, and gitignored, so they never reach review. `project_containment`
  denies an ordinary redirect outside the repository, but not a path passed to
  a script as a plain argument — a backstop, not a guarantee.
