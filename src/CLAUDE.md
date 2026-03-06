# DO NOT EDIT - Hooks Daemon Internal Source Code

**IF YOU ARE WORKING ON A PROJECT THAT HAS HOOKS DAEMON INSTALLED — YOU MUST NOT EDIT ANYTHING IN THIS FOLDER.**

This directory contains the source code for the Claude Code Hooks Daemon. It is an upstream dependency, not part of your project. Editing files here will:

- Break your daemon installation
- Be overwritten on the next daemon update
- Create conflicts that prevent future upgrades

## What You Should Do Instead

### Need Custom Handler Behaviour?

**Create project-level handlers** — they live in YOUR project repo and are auto-discovered:

```bash
# Scaffold project handlers directory
$PYTHON -m claude_code_hooks_daemon.daemon.cli init-project-handlers
```

Project handlers use the same `Handler` ABC as built-in handlers but are scoped to your project. See the full guide: [Project-Level Handlers Guide](../CLAUDE/PROJECT_HANDLERS.md)

### Found a Bug?

**Do NOT fix it here.** Instead, write a detailed bug report and ask your human to submit it upstream:

1. Generate a diagnostic report:
   ```bash
   .claude/hooks-daemon/scripts/debug_info.py /tmp/hooks-daemon-bug-report.md
   ```

2. Write a detailed bug report to an untracked location:
   ```bash
   # Save to untracked/ so it won't be committed to your project
   mkdir -p untracked/bug-reports
   # Write report to untracked/bug-reports/YYYY-MM-DD-description.md
   ```

3. Include in your bug report:
   - What you expected to happen
   - What actually happened
   - Steps to reproduce
   - The diagnostic report from step 1
   - Any relevant hook event logs

4. **Ask your human** to submit the report upstream:
   - GitHub Issues: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues
   - Attach the bug report file

See the full guide: [Bug Reporting Guide](../BUG_REPORTING.md)

### Need to Change Handler Configuration?

Edit your project's `.claude/hooks-daemon.yaml` — that IS part of your project and safe to modify. You can enable/disable handlers, change priorities, and set handler-specific options there.

### Need to Understand How Something Works?

Read the documentation in the `CLAUDE/` directory (not this source code):
- `CLAUDE/ARCHITECTURE.md` — System design
- `CLAUDE/HANDLER_DEVELOPMENT.md` — Handler creation guide
- `CLAUDE/PROJECT_HANDLERS.md` — Project-level handler guide
- `CLAUDE/DEBUGGING_HOOKS.md` — Hook debugging workflow
