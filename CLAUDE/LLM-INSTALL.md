# Claude Code Hooks Daemon - LLM Installation Guide

**IMPORTANT**: This document is optimized for Large Language Models (LLMs) to install the hooks daemon system into a Claude Code project. Follow these instructions sequentially.

## Prerequisites Check

**CRITICAL**: Before starting installation, you MUST have a clean git state with all changes committed and pushed. This allows you to rollback if needed.

```bash
# 1. Check git status is clean
git status --short
# MUST show nothing - commit/push all changes first!

# 2. Commit current .claude/ configuration (if it exists)
if [ -d ".claude" ]; then
    git add .claude/
    git commit -m "Save current hooks configuration before daemon install"
    git push
    echo "✅ Current .claude/ configuration saved to git"
fi

# 3. Verify clean state again
git status --short
# Should show: nothing to commit, working tree clean

# 4. Check you're in a Claude Code project (should have .claude directory)
ls -la .claude/

# 5. Check Python 3.8+ is available
python3 --version

# 6. Check you have write permissions
test -w .claude && echo "✅ Write access OK" || echo "❌ No write access"
```

**If git status shows uncommitted changes**:
```bash
# Commit everything first
git add -A
git commit -m "Commit before hooks daemon installation"
git push
```

**Why this is critical**:
- Installation backs up `.claude/hooks/` to `.claude/hooks.bak.TIMESTAMP/`
- If something goes wrong, you can `git restore .claude/` to get back to pre-install state
- Without git commit, there's no way to recover your previous hooks configuration
- The daemon installation is reversible, but ONLY if you commit first

## Installation Process

### Step 1: Verify Clean Git State

**The install.py script will automatically back up your hooks**, but you need a clean git state first so you can rollback if needed.

```bash
# Verify git status is clean
git status --short

# If NOT clean, commit everything:
git add -A
git commit -m "Pre-daemon-install checkpoint"
git push

# Verify clean state
git status
# Should show: nothing to commit, working tree clean
```

**Why this matters**:
- `install.py` automatically backs up `.claude/hooks/` to `.claude/hooks.bak.TIMESTAMP/`
- But if installation fails, you can only rollback with: `git restore .claude/`
- Without a git commit, you lose your previous hooks configuration permanently

**If you skip this step**: You won't be able to restore your original hooks if something goes wrong!

### Step 2: Clone and Install Daemon

```bash
# Clone daemon to .claude/hooks-daemon/
# IMPORTANT: Must be named "hooks-daemon" to match default paths
mkdir -p .claude
cd .claude
git clone https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git hooks-daemon
cd hooks-daemon

# Install daemon dependencies
pip install -e .
```

**Verification**:
```bash
# Should output module path without errors
python3 -c "import claude_code_hooks_daemon; print(claude_code_hooks_daemon.__file__)"
```

### Step 3: Run Automated Installer

The installer will create all necessary files in your project.

```bash
# Already in .claude/hooks-daemon/ from Step 2
# Run installer
python3 install.py

# Return to project root
cd ../..
```

**Files Created**:
- `.claude/init.sh` - Daemon lifecycle functions
- `.claude/hooks/*` - Forwarder scripts (one per hook type)
- `.claude/settings.json` - Hook registration
- `.claude/hooks-daemon.yaml` - Handler configuration
- `.claude/hooks/handlers/` - Directory for custom handlers

**Directory Structure After Installation**:
```
project/
├── .claude/
│   ├── .gitignore                 # Excludes hooks-daemon/ from git
│   ├── init.sh                    # Copied from daemon (commit this)
│   ├── hooks-daemon.yaml          # Configuration (commit this)
│   ├── settings.json              # Hook registration (commit this)
│   ├── hooks/                     # Forwarder scripts (commit these)
│   │   ├── pre-tool-use
│   │   ├── post-tool-use
│   │   └── handlers/              # Custom handlers (commit these)
│   └── hooks-daemon/              # Daemon source (DO NOT COMMIT - excluded by .gitignore)
│       ├── src/
│       ├── untracked/venv/
│       └── install.py
```

**What to Commit to Git**:
- ✅ `.claude/.gitignore` - Excludes daemon from project
- ✅ `.claude/init.sh` - Daemon lifecycle functions
- ✅ `.claude/hooks-daemon.yaml` - Your handler configuration
- ✅ `.claude/settings.json` - Hook registration
- ✅ `.claude/hooks/*` - Forwarder scripts
- ✅ `.claude/hooks/handlers/*` - Your custom handlers
- ❌ `.claude/hooks-daemon/` - Daemon repo (excluded by .gitignore)
- ❌ `.claude/hooks.bak*` - Backup directories (excluded by .gitignore)

**Verification**:
```bash
# Check all files were created
ls -la .claude/.gitignore
ls -la .claude/init.sh
ls -la .claude/hooks/pre-tool-use
ls -la .claude/hooks/post-tool-use
ls -la .claude/settings.json
ls -la .claude/hooks-daemon.yaml
ls -la .claude/hooks/handlers/
ls -la .claude/hooks-daemon/src/

# Verify .gitignore is working (daemon should be excluded)
cd .claude
git status --short
# Should NOT show hooks-daemon/ as untracked
```

### Step 4: Verify Daemon Functionality

Test that the daemon starts and responds correctly.

```bash
# Test daemon can start
python3 -m claude_code_hooks_daemon.daemon.cli start

# Check daemon status
python3 -m claude_code_hooks_daemon.daemon.cli status

# Test a hook manually (should block destructive git command)
echo '{"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}' | .claude/hooks/pre-tool-use

# Expected output: {"result": {"decision": "deny", ...}, "handlers_matched": ["prevent-destructive-git"]}
```

**If test passes (command is blocked)**: ✅ Daemon is working correctly!

**If test fails (command is allowed)**: ⚠️ See Troubleshooting section below.

### Step 5: Configure Handlers for Your Project

Edit `.claude/hooks-daemon.yaml` to enable/disable handlers based on your project needs:

```bash
# Open configuration file
nano .claude/hooks-daemon.yaml
# or
code .claude/hooks-daemon.yaml
```

**Key configuration options**:

```yaml
daemon:
  idle_timeout_seconds: 600  # Auto-shutdown after 10 min idle
  log_level: INFO           # DEBUG, INFO, WARNING, ERROR

handlers:
  pre_tool_use:
    # SAFETY HANDLERS - Recommended to keep enabled
    destructive_git:
      enabled: true   # Blocks git reset --hard, git clean -f, etc
      priority: 10

    sed_blocker:
      enabled: true   # Blocks sed (use Edit tool instead)
      priority: 10

    # WORKFLOW HANDLERS - Enable based on your project
    tdd_enforcement:
      enabled: false  # Set true to enforce test-first development
      priority: 35

    british_english:
      enabled: false  # Set true to warn on American spellings
      priority: 60
```

After editing, restart daemon:
```bash
python3 -m claude_code_hooks_daemon.daemon.cli restart
```

## Migrating Project-Specific Hooks

If you had custom hooks in the backup, you need to convert them to handlers.

### Step 6A: Identify Custom Hooks

```bash
# List backed up hooks
BACKUP_DIR=$(ls -d .claude/hooks.bak.* 2>/dev/null | tail -1)
if [ -n "$BACKUP_DIR" ]; then
    echo "Backed up hooks:"
    find "$BACKUP_DIR" -type f -executable | grep -v "\.bak"
fi
```

### Step 6B: Create Custom Handler Template

For each custom hook, create a handler:

```bash
# Create handler file
mkdir -p .claude/hooks/handlers/pre_tool_use
touch .claude/hooks/handlers/pre_tool_use/my_custom_handler.py
chmod +x .claude/hooks/handlers/pre_tool_use/my_custom_handler.py
```

**Handler Template**:
```python
"""My Custom Handler - Brief description of what it does."""

from typing import Any
from claude_code_hooks_daemon.core import Handler, HookResult, Decision


class MyCustomHandler(Handler):
    """Detailed description of handler purpose."""

    def __init__(self) -> None:
        super().__init__(
            name="my-custom-handler",  # Lowercase with hyphens
            priority=50,                # Lower = runs earlier
            terminal=True               # True = stops chain if matched
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this handler should process the hook.

        Args:
            hook_input: Dict with keys:
                - tool_name: str (e.g., "Bash", "Write", "Edit")
                - tool_input: dict (tool-specific data)
                - session_id: str (optional)

        Returns:
            True if this handler should run
        """
        # Example: Match Bash commands containing 'npm'
        if hook_input.get("tool_name") != "Bash":
            return False

        command = hook_input.get("tool_input", {}).get("command", "")
        return "npm" in command

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Process the matched hook.

        Args:
            hook_input: Same as matches()

        Returns:
            HookResult with decision (allow/deny) and reason
        """
        command = hook_input.get("tool_input", {}).get("command", "")

        # Example: Block direct npm install, suggest using project script
        if "npm install" in command:
            return HookResult(
                decision=Decision.DENY,
                reason="Use './scripts/install-deps.sh' instead of direct npm install"
            )

        return HookResult(decision=Decision.ALLOW)
```

### Step 6C: Enable Custom Handler

Add to `.claude/hooks-daemon.yaml`:

```yaml
handlers:
  pre_tool_use:
    # ... existing handlers ...

    my_custom_handler:  # Snake_case version of class name (without "Handler")
      enabled: true
      priority: 50
```

Restart daemon to load:
```bash
python3 -m claude_code_hooks_daemon.daemon.cli restart
```

### Step 6D: Test Custom Handler

```bash
# Test that your handler matches and blocks/allows as expected
echo '{"tool_name": "Bash", "tool_input": {"command": "npm install lodash"}}' | .claude/hooks/pre-tool-use
```

## Verification Checklist

After installation, verify everything works:

- [ ] **Daemon starts**: `python3 -m claude_code_hooks_daemon.daemon.cli status` shows "RUNNING"
- [ ] **Destructive git blocked**: Test command returns `"decision": "deny"`
- [ ] **sed blocked**: `sed -i` command returns `"decision": "deny"`
- [ ] **Safe commands allowed**: `echo hello` command returns `"decision": "allow"`
- [ ] **Custom handlers work**: Your project-specific hooks execute correctly
- [ ] **Configuration loads**: No errors in daemon logs
- [ ] **Performance acceptable**: Hooks respond in <100ms

Check daemon logs if any issues:
```bash
python3 -m claude_code_hooks_daemon.daemon.cli logs
```

## Troubleshooting

### Problem: Daemon won't start

**Check Python version**:
```bash
python3 --version
# Should be 3.8 or higher
```

**Check installation**:
```bash
python3 -c "import claude_code_hooks_daemon; print('OK')"
```

**Check for port conflicts**:
```bash
# Daemon uses Unix socket, check if socket file is stale
ls -la /tmp/claude-hooks-*.sock
# If exists and daemon not running, remove it
rm /tmp/claude-hooks-*.sock
```

### Problem: Handlers not matching (all commands allowed)

**Check handler configuration**:
```bash
# Verify handlers are enabled
grep -A 2 "enabled:" .claude/hooks-daemon.yaml
```

**Check daemon logs for errors**:
```bash
python3 -m claude_code_hooks_daemon.daemon.cli logs | grep ERROR
```

**Verify hook_input format**:
```bash
# Test with debug logging
echo '{"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}' \
  | .claude/hooks/pre-tool-use 2>&1
```

### Problem: Custom handler not loading

**Check file naming**:
- File: `my_custom_handler.py` (snake_case)
- Class: `MyCustomHandler` (PascalCase, ends with "Handler")
- Config key: `my_custom_handler` (snake_case, without "Handler")

**Check imports**:
```bash
cd .claude/hooks/handlers/pre_tool_use
python3 -c "from my_custom_handler import MyCustomHandler; print('OK')"
```

**Check handler registration**:
```bash
# Should list your handler
python3 -c "
from claude_code_hooks_daemon.daemon.controller import DaemonController
from claude_code_hooks_daemon.config import Config
from pathlib import Path

config = Config.find_and_load(Path.cwd())
controller = DaemonController()
handler_config = {
    'pre_tool_use': {k: v.model_dump() for k, v in config.handlers.pre_tool_use.items()}
}
controller.initialise(handler_config)
handlers = controller.get_handlers()
print([h['name'] for h in handlers.get('PreToolUse', [])])
"
```

### Problem: Hooks running slowly

**Check number of enabled handlers**:
```bash
grep -c "enabled: true" .claude/hooks-daemon.yaml
```

**Disable unused handlers** in `.claude/hooks-daemon.yaml`:
```yaml
handlers:
  pre_tool_use:
    unused_handler:
      enabled: false  # Disable if not needed
```

**Check daemon logs for slow handlers**:
```bash
python3 -m claude_code_hooks_daemon.daemon.cli logs | grep "took"
```

### Problem: Need to rollback to old hooks

**Option 1: Git Rollback (Recommended - if you committed before install)**
```bash
# Stop daemon first
python3 -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true

# Restore entire .claude/ directory from git
git restore .claude/

# Remove daemon installation
rm -rf .claude/hooks-daemon/

# Verify restoration
git status .claude/
# Should show: nothing to restore

echo "✅ Fully restored to pre-installation state from git"
```

**Option 2: Backup Directory Restore (If no git commit)**
```bash
# Find backup directory
BACKUP_DIR=$(ls -d .claude/hooks.bak.* 2>/dev/null | tail -1)

if [ -z "$BACKUP_DIR" ]; then
    echo "❌ No backup found! Cannot restore without git commit."
    echo "This is why you should commit before installing."
    exit 1
fi

# Stop daemon
python3 -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true

# Restore backup
rm -rf .claude/hooks
mv "$BACKUP_DIR" .claude/hooks

# Restore old settings if backed up
if [ -f ".claude/settings.json.bak" ]; then
    mv .claude/settings.json.bak .claude/settings.json
fi

echo "✅ Rolled back to backup: $BACKUP_DIR"
echo "⚠️  This only restored hooks, not other .claude/ files"
```

## Raising Issues and Contributing

### Reporting Bugs

When reporting issues, include:

1. **Daemon version**:
   ```bash
   python3 -c "import claude_code_hooks_daemon; print(claude_code_hooks_daemon.__version__)"
   ```

2. **Python version**:
   ```bash
   python3 --version
   ```

3. **Operating system**:
   ```bash
   uname -a
   ```

4. **Daemon logs**:
   ```bash
   python3 -m claude_code_hooks_daemon.daemon.cli logs > daemon-logs.txt
   ```

5. **Configuration** (sanitize sensitive data):
   ```bash
   cat .claude/hooks-daemon.yaml
   ```

6. **Reproduction steps**: Exact commands to reproduce the issue

**Submit issue**: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues/new

### Contributing Fixes

1. **Fork the repository**:
   ```bash
   gh repo fork Edmonds-Commerce-Limited/claude-code-hooks-daemon
   ```

2. **Create feature branch**:
   ```bash
   cd /tmp
   git clone https://github.com/YOUR-USERNAME/claude-code-hooks-daemon.git
   cd claude-code-hooks-daemon
   git checkout -b fix/issue-description
   ```

3. **Make changes and test**:
   ```bash
   # Install dev dependencies
   pip install -e ".[dev]"

   # Run QA checks (auto-fixes formatting/linting)
   ./scripts/qa/run_all.sh

   # All checks must pass:
   # - Black formatting
   # - Ruff linting
   # - MyPy type checking
   # - Pytest (95% coverage required)
   ```

4. **Commit with conventional commit format**:
   ```bash
   git add -A
   git commit -m "fix: brief description of fix

   Detailed explanation of what was broken and how you fixed it.

   Fixes #123"
   ```

5. **Push and create PR**:
   ```bash
   git push origin fix/issue-description
   gh pr create --title "Fix: brief description" --body "Fixes #123

   **Problem**: Description of bug
   **Solution**: How you fixed it
   **Testing**: How you verified the fix"
   ```

### Contributing New Handlers

**General utility handlers** (useful across projects):
- Submit as PR to main repository
- Include comprehensive tests
- Add documentation to README.md
- Follow handler development guide in CONTRIBUTING.md

**Project-specific handlers** (only useful in your project):
- Keep in your project's `.claude/hooks/handlers/`
- Share on discussions/wiki if others might find useful
- No need to submit to main repository

## Advanced Configuration

### Multiple Hook Types

Enable handlers for different hook events:

```yaml
handlers:
  pre_tool_use:
    destructive_git: {enabled: true, priority: 10}

  post_tool_use:
    bash_error_detector: {enabled: true, priority: 50}

  session_start:
    workflow_state_restoration: {enabled: true, priority: 50}
```

### Handler Priority Ranges

Handlers execute in priority order (lower = earlier):

- **5**: Test/debug handlers
- **10-20**: Safety (destructive operations, sed)
- **25-35**: Code quality (ESLint, TDD)
- **36-55**: Workflow (planning, npm)
- **56-60**: Advisory (British English, formatting)

### Per-Handler Configuration

Some handlers accept custom configuration:

```yaml
handlers:
  pre_tool_use:
    absolute_path:
      enabled: true
      priority: 12
      blocked_prefixes:
        - /container-mount/
        - /tmp/claude-code/

    tdd_enforcement:
      enabled: true
      priority: 35
      test_file_patterns:
        - "**/*.test.ts"
        - "**/*.spec.ts"
      source_dirs:
        - src/
        - lib/
```

### Daemon Auto-Start

The daemon starts automatically when first hook is called (lazy startup).

To start manually on system boot:
```bash
# Add to ~/.bashrc or project .envrc
python3 -m claude_code_hooks_daemon.daemon.cli start 2>/dev/null || true
```

### Daemon Auto-Shutdown

Daemon automatically shuts down after `idle_timeout_seconds` (default: 600s / 10 min).

Adjust in `.claude/hooks-daemon.yaml`:
```yaml
daemon:
  idle_timeout_seconds: 1800  # 30 minutes
```

Set to `0` to disable auto-shutdown (daemon runs indefinitely).

## Next Steps

1. ✅ Installation complete
2. ✅ Daemon verified working
3. ✅ Handlers configured for your project
4. ✅ Custom handlers migrated (if needed)

**Optional enhancements**:
- Add project-specific handlers in `.claude/hooks/handlers/`
- Fine-tune handler priorities for your workflow
- Enable additional hook types (post_tool_use, session_start, etc.)
- Contribute improvements back to the project

**Resources**:
- Full documentation: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon
- Handler development: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/blob/main/CONTRIBUTING.md
- Discussions: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/discussions

---

**Installation Date**: `date +%Y-%m-%d`
**Daemon Version**: Check with `python3 -c "import claude_code_hooks_daemon; print(claude_code_hooks_daemon.__version__)"`
