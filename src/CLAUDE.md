# DO NOT EDIT - Hooks Daemon Internal Source Code

**IF YOU ARE WORKING ON A PROJECT THAT HAS HOOKS DAEMON INSTALLED — YOU MUST
NOT EDIT ANYTHING IN THIS FOLDER.**

This is the daemon's own source code: an upstream dependency, not part of your
project. Editing files here breaks your installation, is overwritten on the
next daemon update, and creates conflicts that prevent future upgrades.

**Unless this repository IS the daemon.** In self-install (dogfood) mode the
daemon's source and the project are the same checkout, so there is no upstream
to be overwritten by and editing here is the normal way to work — see
[SELF_INSTALL.md](../CLAUDE/SELF_INSTALL.md). The heading above is addressed to
a CLIENT project that installed the daemon under `.claude/hooks-daemon/`; it is
not a claim that these files are untouchable everywhere. Check which case you
are in before concluding an instruction to edit `src/` is a mistake: two
sub-agents working on daemon source have now read this page as forbidding their
assigned task, and one classified it as injected content.

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
  is gitignored, so it never reaches review. `project_containment` denies an
  ordinary redirect outside the repository (`echo x > /tmp/f`), but it judges
  redirects and destination-bearing constructs — not a path handed to a script
  as a plain argument — so treat it as a backstop, not a guarantee that
  nothing can be written outside the tree.
- **Change handler configuration** — edit your project's
  `.claude/hooks-daemon.yaml` (that IS yours: enable/disable handlers, set
  priorities and options).
- **Understand how something works** — read the docs, not the source:
  [ARCHITECTURE.md](../CLAUDE/ARCHITECTURE.md),
  [HANDLER_DEVELOPMENT.md](../CLAUDE/HANDLER_DEVELOPMENT.md),
  [PROJECT_HANDLERS.md](../CLAUDE/PROJECT_HANDLERS.md),
  [DEBUGGING_HOOKS.md](../CLAUDE/DEBUGGING_HOOKS.md).
