# DO NOT EDIT - Hooks Daemon Internal Source Code

**IF YOU ARE WORKING ON A PROJECT THAT HAS HOOKS DAEMON INSTALLED — YOU MUST
NOT EDIT ANYTHING IN THIS FOLDER.**

This is the daemon's own source code: an upstream dependency, not part of your
project. Editing files here breaks your installation, is overwritten on the
next daemon update, and creates conflicts that prevent future upgrades.

## Do This Instead

- **Custom handler behaviour** — create project-level handlers in YOUR repo
  (`.claude/hooks-daemon/bin/hooks-daemon init-project-handlers` scaffolds
  them; they are auto-discovered). See
  [Project-Level Handlers Guide](../CLAUDE/PROJECT_HANDLERS.md).
- **Found a bug** — do NOT fix it here. Write a report to
  `untracked/scratch/` and ask your human to submit it upstream, following
  the [Bug Reporting Guide](../BUG_REPORTING.md) (it covers the diagnostic
  script, report contents, and the upstream issue tracker). That directory is
  inside the working tree, so the report survives a container restart, and it
  is gitignored, so it never reaches review. A path outside the repository is
  refused by `project_containment`.
- **Change handler configuration** — edit your project's
  `.claude/hooks-daemon.yaml` (that IS yours: enable/disable handlers, set
  priorities and options).
- **Understand how something works** — read the docs, not the source:
  [ARCHITECTURE.md](../CLAUDE/ARCHITECTURE.md),
  [HANDLER_DEVELOPMENT.md](../CLAUDE/HANDLER_DEVELOPMENT.md),
  [PROJECT_HANDLERS.md](../CLAUDE/PROJECT_HANDLERS.md),
  [DEBUGGING_HOOKS.md](../CLAUDE/DEBUGGING_HOOKS.md).
