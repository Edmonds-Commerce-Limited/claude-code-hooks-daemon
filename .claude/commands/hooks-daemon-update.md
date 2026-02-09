# Hooks Daemon Update Command

**Usage**: `/hooks-daemon-update`

**Purpose**: Guide the LLM through upgrading the Claude Code Hooks Daemon to the latest version.

---

## Instructions for LLM

When this command is invoked, follow these steps:

### Step 1: Fetch Latest Update Guide

Fetch the latest upgrade documentation from GitHub:

```bash
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-UPDATE.md
```

**CRITICAL**: Read the ENTIRE document - do NOT summarize or truncate.

### Step 2: Verify Prerequisites

Before proceeding, check:

1. **Context window**: Ensure at least 50,000 tokens remaining
2. **Working directory**: Must be clean (`git status` should show no uncommitted changes)
3. **Project root**: Verify you're at the project root (`.claude/hooks-daemon.yaml` exists)

If any prerequisite fails, inform the user and STOP.

### Step 3: Execute Upgrade

Follow the **RECOMMENDED: Automated Upgrade** section from the fetched guide.

The primary method is:

```bash
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/scripts/upgrade.sh | bash
```

### Step 4: Verify Upgrade

After upgrade completes, verify:

1. **Daemon status**: Check daemon is running
2. **Version check**: Confirm new version installed
3. **Hook test**: Test that hooks still work

### Step 5: Report New Handlers

Run the handler status report to show what's available:

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python
cd .claude/hooks-daemon && $VENV_PYTHON scripts/handler_status.py
```

Inform the user of any new handlers they may want to enable.

### Step 6: Summary

Provide a concise summary:
- Previous version → Current version
- Any new handlers available
- Whether daemon is running
- Next steps (if any)

---

## Error Handling

If the upgrade fails:

1. Check the fetched guide for troubleshooting steps
2. Review daemon logs for errors
3. Follow rollback instructions if needed
4. Report the specific error to the user

---

**Note**: This command always fetches the LATEST documentation from GitHub to ensure you have the most up-to-date upgrade instructions, regardless of the project's current daemon version.
