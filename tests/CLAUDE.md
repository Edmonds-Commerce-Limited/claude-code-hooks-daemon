# DO NOT EDIT - Hooks Daemon Internal Tests

**IF YOU ARE WORKING ON A PROJECT THAT HAS HOOKS DAEMON INSTALLED — YOU MUST NOT EDIT ANYTHING IN THIS FOLDER.**

This directory contains the test suite for the Claude Code Hooks Daemon. It is an upstream dependency, not part of your project. Editing files here will:

- Break your daemon installation
- Be overwritten on the next daemon update
- Create conflicts that prevent future upgrades

## What You Should Do Instead

### Need Tests for Custom Handlers?

Project-level handlers support **co-located tests**. When you scaffold project handlers, each handler gets a test file next to it:

```
.claude/project-handlers/
  pre_tool_use/
    my_handler.py
    test_my_handler.py    # Co-located test
  post_tool_use/
    my_other_handler.py
    test_my_other_handler.py
```

Run your project handler tests:
```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli test-project-handlers --verbose
```

See the full guide: [Project-Level Handlers Guide](../CLAUDE/PROJECT_HANDLERS.md)

### Found a Bug?

**Do NOT fix it here.** Write a detailed bug report and ask your human to submit it upstream:

1. Generate a diagnostic report:
   ```bash
   .claude/hooks-daemon/scripts/debug_info.py /tmp/hooks-daemon-bug-report.md
   ```

2. Save your bug report to an untracked location:
   ```bash
   mkdir -p untracked/bug-reports
   # Write report to untracked/bug-reports/YYYY-MM-DD-description.md
   ```

3. **Ask your human** to submit it:
   - GitHub Issues: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues

See the full guide: [Bug Reporting Guide](../BUG_REPORTING.md)
