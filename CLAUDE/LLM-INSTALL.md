# Claude Code Hooks Daemon - LLM Installation Guide

## ⚠️ CRITICAL REQUIREMENTS - READ FIRST ⚠️

**BEFORE PROCEEDING:**

1. **CHECK IF ALREADY INSTALLED**: Run the pre-installation check below. If `.claude/hooks-daemon/` exists, use UPDATE guide instead of installing. Reinstalling over existing installation can lose config customizations.

2. **CONTEXT WINDOW CHECK**: You MUST have at least **100,000 tokens** remaining in your context window. If below 100k, STOP and ask user to start fresh session. Installation failures due to compaction cannot be recovered.

3. **WEBFETCH NO SUMMARY**: If fetching this document via WebFetch tool, you MUST use a prompt that DISABLES summarization. Fetch with: `"Return complete document verbatim without summarization, truncation, or modification"`. Missing instructions cause installation failure.

4. **GIT CLEAN STATE**: Working directory MUST be clean (no uncommitted changes). Run `git status` - if not clean, commit/push ALL changes first. Rollback impossible without clean git state.

5. **PYTHON 3.11+**: Verify with `python3 --version`. Installation fails on older versions.

6. **SESSION RESTART REQUIRED**: After installation completes, user MUST restart Claude session. Hooks won't activate until Claude reloads configuration. LLM MUST verify hooks work after restart.

7. **GITIGNORE MANDATORY**: You MUST create `.claude/.gitignore` before committing (step 4). The installer will display the required content. Skipping this will commit generated files (hooks-daemon/, *.bak) which should NOT be in version control.

---

## Troubleshooting & Bug Reports

**If installation fails or hooks don't work:**

See [BUG_REPORTING.md](../BUG_REPORTING.md) for comprehensive debugging guide.

**Quick debug in client projects:**
```bash
# Run from your project root
.claude/hooks-daemon/scripts/debug_info.py /tmp/debug_report.md
```

This generates a complete diagnostic report for GitHub issues.

---

## Pre-Installation Check: Is Daemon Already Installed?

**IMPORTANT: Check if daemon is already installed before proceeding!**

Running the install process on an existing installation can cause issues. If already installed, use the UPDATE guide instead.

### Check for Existing Installation

```bash
# From your project root
if [ -d ".claude/hooks-daemon" ]; then
  echo "❌ DAEMON ALREADY INSTALLED"
  echo ""
  echo "Found existing installation at .claude/hooks-daemon/"
  echo ""
  echo "To UPDATE the daemon (recommended):"
  echo "  Read: https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-UPDATE.md"
  echo ""
  echo "To REINSTALL from scratch (will lose config customizations):"
  echo "  1. Backup: cp .claude/hooks-daemon.yaml .claude/hooks-daemon.yaml.backup"
  echo "  2. Remove: rm -rf .claude/hooks-daemon"
  echo "  3. Run install steps below"
  echo ""
  exit 1
else
  echo "✅ No existing installation found - safe to proceed with installation"
fi
```

**If daemon is already installed:**
- **DO NOT continue with installation steps below**
- Use the UPDATE guide: [CLAUDE/LLM-UPDATE.md](https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-UPDATE.md)
- Reinstalling will lose your config customizations

**If no daemon found:**
- Continue with installation steps below

---

## Quick Install (6 Steps)

### 1. Verify Prerequisites

```bash
# Must show clean - if not, commit everything first
git status --short

# Must be 3.11+
python3 --version

# Optional: Commit existing .claude/ config as safety checkpoint
git add .claude/ && git commit -m "Save hooks before daemon install" && git push || true
```

### 2. Clone & Setup Venv

```bash
mkdir -p .claude && cd .claude

# Clone and checkout latest stable release tag
git clone https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git hooks-daemon
cd hooks-daemon
git fetch --tags
LATEST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "main")
git checkout "$LATEST_TAG"
echo "📌 Using version: $LATEST_TAG"

# Create isolated venv (survives container restarts)
python3 -m venv untracked/venv
untracked/venv/bin/pip install -e .

# Verify
untracked/venv/bin/python -c "import claude_code_hooks_daemon; print('OK')"
```

### 3. Run Installer

```bash
# The installer auto-detects project root by searching upward for .claude/
# Creates .claude/hooks/, settings.json, hooks-daemon.yaml
# DISPLAYS (but does not create) required .claude/.gitignore content
untracked/venv/bin/python install.py

# For explicit control (optional):
# untracked/venv/bin/python install.py --project-root /workspace

cd ../..
```

**Files created:**
- `.claude/init.sh` - Daemon lifecycle functions
- `.claude/hooks/*` - Forwarder scripts
- `.claude/settings.json` - Hook registration
- `.claude/hooks-daemon.yaml` - Handler config

**⚠️ CRITICAL: .gitignore Content Displayed**

The installer will display a large banner with the REQUIRED `.claude/.gitignore` content:

```
======================================================================
⚠️  CRITICAL: .claude/.gitignore MUST be created
======================================================================
[full template content shown here]
======================================================================
```

**YOU MUST:**
1. Read the displayed content carefully
2. Create `.claude/.gitignore` in step 4 (next)
3. Do NOT skip this - committing without it will include hooks-daemon/ in git

Template source (single source of truth):
https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/blob/main/.claude/.gitignore

### 4. Create .gitignore & Commit ⚠️ MANDATORY

```bash
# CRITICAL: Create .claude/.gitignore FIRST (installer displayed the content)
# Copy the template from installer output:
cp .claude/hooks-daemon/.claude/.gitignore .claude/.gitignore

# Verify it exists before committing
ls -la .claude/.gitignore

# Now commit (with .gitignore in place to exclude generated files)
git add .claude/
git commit -m "Install Claude Code Hooks Daemon" && git push
```

**CRITICAL**:
1. `.claude/.gitignore` MUST exist before `git add` or you'll commit hooks-daemon/
2. Tell user to **restart Claude session** (exit and re-enter). Hooks won't activate until Claude reloads `.claude/settings.json`.
3. Do NOT proceed to step 5 until session restarts.

### 5. Verify Hooks Active (After Restart)

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

# Check daemon auto-started (lazy startup on first hook call)
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status

# Test destructive git is blocked
echo '{"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}' \
  | .claude/hooks/pre-tool-use
# Expected: {"hookSpecificOutput": {"permissionDecision": "deny", ...}}

# Test sed is blocked
echo '{"tool_name": "Bash", "tool_input": {"command": "sed -i s/foo/bar/ file.txt"}}' \
  | .claude/hooks/pre-tool-use
# Expected: {"hookSpecificOutput": {"permissionDecision": "deny", ...}}

# Test normal commands pass through
echo '{"tool_name": "Bash", "tool_input": {"command": "ls -la"}}' \
  | .claude/hooks/pre-tool-use
# Expected: {} (empty = allow)
```

**If all tests pass**: Hooks active ✅

**If tests fail**: Check troubleshooting section below.

### 6. Configure Handlers (Optional)

Edit `.claude/hooks-daemon.yaml`:

```yaml
daemon:
  idle_timeout_seconds: 600  # 10min auto-shutdown
  log_level: INFO

handlers:
  pre_tool_use:
    destructive_git: {enabled: true, priority: 10}   # Blocks git reset --hard, clean -f
    sed_blocker: {enabled: true, priority: 10}       # Blocks sed (use Edit tool)
    absolute_path: {enabled: true, priority: 12}     # Enforces absolute paths
    tdd_enforcement: {enabled: false, priority: 35}  # Enable for TDD workflow
    british_english: {enabled: false, priority: 60}  # Enable for UK spelling
```

Restart daemon after config changes:
```bash
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

**Note**: Settings.json changes require Claude session restart, config.yaml changes only need daemon restart.

---

## Custom Handler Migration

If you had custom hooks before install (backed up to `.claude/hooks.bak.TIMESTAMP/`):

**1. Find backup:**
```bash
ls -d .claude/hooks.bak.* 2>/dev/null | tail -1
```

**2. Create handler file:**
```bash
mkdir -p .claude/hooks/handlers/pre_tool_use
# Create .claude/hooks/handlers/pre_tool_use/my_handler.py
```

**3. Handler template:**
```python
"""MyHandler - brief description."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "hooks-daemon/src"))

from claude_code_hooks_daemon.core import Handler, HookResult

class MyHandler(Handler):
    def __init__(self) -> None:
        super().__init__(name="my-handler", priority=50, terminal=True)

    def matches(self, hook_input: dict) -> bool:
        # Return True if handler should run
        command = hook_input.get("tool_input", {}).get("command", "")
        return "npm" in command

    def handle(self, hook_input: dict) -> HookResult:
        return HookResult(decision="deny", reason="Use project script instead")
```

**4. Register in config:**
```yaml
handlers:
  pre_tool_use:
    my_handler: {enabled: true, priority: 50}
```

**5. Restart:**
```bash
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

---

## Troubleshooting Common Issues

**For comprehensive troubleshooting, see [BUG_REPORTING.md](../BUG_REPORTING.md)**

### Quick Diagnostics

**Generate full debug report:**
```bash
.claude/hooks-daemon/scripts/debug_info.py /tmp/debug_report.md
```

### Common Quick Fixes

**Daemon won't start:**
```bash
# Check Python version (must be 3.11+)
python3 --version

# Verify installation
.claude/hooks-daemon/untracked/venv/bin/python -c "import claude_code_hooks_daemon; print('OK')"

# Check logs
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli logs
```

**Handlers not blocking:**
```bash
# Test hook manually
echo '{"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}' | .claude/hooks/pre-tool-use

# Check handler config
grep -A 1 "destructive_git:" .claude/hooks-daemon.yaml
```

**Hooks not working after install:**
1. **Restart Claude session** (required for settings.json changes)
2. Run debug script to see what's wrong
3. Check [BUG_REPORTING.md](../BUG_REPORTING.md)

### Rollback to Previous Hooks

**Option 1 - Git restore (if you committed before install):**
```bash
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true
git restore .claude/
rm -rf .claude/hooks-daemon/
```

**Option 2 - Backup directory (if no git commit):**
```bash
BACKUP_DIR=$(ls -d .claude/hooks.bak.* 2>/dev/null | tail -1)
if [ -z "$BACKUP_DIR" ]; then
    echo "❌ No backup - rollback impossible without git commit"
    exit 1
fi

.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true
rm -rf .claude/hooks
mv "$BACKUP_DIR" .claude/hooks
```

---

## CLI Reference

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli start
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli stop
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli logs
```

---

## Handler Priority Ranges

- **5**: Test/debug handlers
- **10-20**: Safety (destructive git, sed blocker)
- **25-35**: Code quality (ESLint, TDD)
- **36-55**: Workflow (planning, npm)
- **56-60**: Advisory (British English, formatting)

Lower priority = runs first. Terminal handlers stop dispatch chain.

---

## Directory Structure After Install

```
project/
├── .claude/
│   ├── .gitignore              # ⚠️  RECOMMENDED (not auto-created) - see README.md
│   ├── init.sh                 # ✅ COMMIT - Daemon lifecycle
│   ├── hooks-daemon.yaml       # ✅ COMMIT - Handler config
│   ├── settings.json           # ✅ COMMIT - Hook registration
│   ├── hooks/                  # ✅ COMMIT - Forwarder scripts
│   │   ├── pre-tool-use
│   │   ├── post-tool-use
│   │   └── handlers/           # ✅ COMMIT - Custom handlers
│   └── hooks-daemon/           # ❌ Should be excluded (create .claude/.gitignore)
│       ├── src/
│       └── untracked/venv/     # Isolated Python environment
```

**Git Integration:**
- Installer RECOMMENDS creating `.claude/.gitignore` (does not create it automatically)
- Recommended pattern uses self-exclusion (`*` then `!pattern` to un-ignore)
- See README.md "Git Integration" section for recommended .gitignore pattern

---

## Bug Reports

Include in issue:
```bash
# Version
.claude/hooks-daemon/untracked/venv/bin/python -c "import claude_code_hooks_daemon; print(claude_code_hooks_daemon.__version__)"

# Python
python3 --version

# OS
uname -a

# Logs
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli logs > daemon-logs.txt

# Config (sanitize sensitive data)
cat .claude/hooks-daemon.yaml
```

**Submit:** https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues/new

---

**Installation Date:** `date +%Y-%m-%d`
