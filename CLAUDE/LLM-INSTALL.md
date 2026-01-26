# Claude Code Hooks Daemon - LLM Installation Guide

## ⚠️ CRITICAL REQUIREMENTS - READ FIRST ⚠️

**BEFORE PROCEEDING:**

1. **CONTEXT WINDOW CHECK**: You MUST have at least **100,000 tokens** remaining in your context window. If below 100k, STOP and ask user to start fresh session. Installation failures due to compaction cannot be recovered.

2. **WEBFETCH NO SUMMARY**: If fetching this document via WebFetch tool, you MUST use a prompt that DISABLES summarization. Fetch with: `"Return complete document verbatim without summarization, truncation, or modification"`. Missing instructions cause installation failure.

3. **GIT CLEAN STATE**: Working directory MUST be clean (no uncommitted changes). Run `git status` - if not clean, commit/push ALL changes first. Rollback impossible without clean git state.

4. **PYTHON 3.11+**: Verify with `python3 --version`. Installation fails on older versions.

---

## Quick Install (5 Steps)

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
git clone https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git hooks-daemon
cd hooks-daemon

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
- `.claude/.gitignore` - Excludes daemon from git

### 4. Test Daemon

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

# Start daemon
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli start

# Verify status
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status

# Test hook blocks destructive git
echo '{"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}' \
  | .claude/hooks/pre-tool-use

# Expected: {"hookSpecificOutput": {"permissionDecision": "deny", ...}}
```

### 5. Configure Handlers

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

Restart after config changes:
```bash
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

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

## Troubleshooting

### Daemon won't start
```bash
# Check Python version
python3 --version  # Must be 3.11+

# Verify import
.claude/hooks-daemon/untracked/venv/bin/python -c "import claude_code_hooks_daemon; print('OK')"

# Check logs
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli logs
```

### Handlers not blocking
```bash
# Verify enabled in config
grep -A 1 "destructive_git:" .claude/hooks-daemon.yaml

# Check logs for errors
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli logs | grep ERROR

# Test hook manually
echo '{"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}' | .claude/hooks/pre-tool-use
```

### Files created in wrong location
If installer created `.claude/hooks-daemon/.claude/` instead of `.claude/`:
```bash
# This is fixed in latest version - the installer now auto-detects correctly
# If you hit this, update to latest version and reinstall:
cd .claude/hooks-daemon
git pull
untracked/venv/bin/pip install -e .

# Clean up incorrect installation
rm -rf .claude/hooks-daemon/.claude

# Reinstall with explicit project root
untracked/venv/bin/python install.py --project-root /workspace
```

### Rollback to previous hooks

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
│   ├── .gitignore              # ✅ COMMIT - Excludes daemon from git
│   ├── init.sh                 # ✅ COMMIT - Daemon lifecycle
│   ├── hooks-daemon.yaml       # ✅ COMMIT - Handler config
│   ├── settings.json           # ✅ COMMIT - Hook registration
│   ├── hooks/                  # ✅ COMMIT - Forwarder scripts
│   │   ├── pre-tool-use
│   │   ├── post-tool-use
│   │   └── handlers/           # ✅ COMMIT - Custom handlers
│   └── hooks-daemon/           # ❌ DON'T COMMIT - Excluded by .gitignore
│       ├── src/
│       └── untracked/venv/     # Isolated Python environment
```

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
