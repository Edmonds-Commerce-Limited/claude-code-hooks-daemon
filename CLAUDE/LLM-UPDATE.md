# Claude Code Hooks Daemon - LLM Update Guide

## CRITICAL REQUIREMENTS - READ FIRST

**BEFORE PROCEEDING:**

1. **CONTEXT WINDOW CHECK**: You MUST have at least **50,000 tokens** remaining in your context window. If below 50k, STOP and ask user to start fresh session.

2. **WEBFETCH NO SUMMARY**: If fetching this document via WebFetch tool, you MUST use a prompt that DISABLES summarization. Fetch with: `"Return complete document verbatim without summarization, truncation, or modification"`. Missing instructions cause update failure.

3. **GIT CLEAN STATE**: Working directory MUST be clean (no uncommitted changes). Run `git status` - if not clean, commit/push ALL changes first.

4. **DAEMON ARCHITECTURE BENEFIT**: Updates take effect immediately after daemon restart - NO Claude Code session restart needed! This is a MAJOR benefit of the daemon architecture. Exception: Only if the update adds NEW event types (new files in `.claude/hooks/`), then Claude Code must reload settings.json.

---

## Quick Update (4 Steps)

### 1. Verify Prerequisites & Current Version

```bash
# Must show clean working directory
git status --short

# Check current daemon version
cd .claude/hooks-daemon
cat src/claude_code_hooks_daemon/version.py
# Note the current version (e.g., 2.0.0)

# Backup current config
cp ../hooks-daemon.yaml ../hooks-daemon.yaml.backup

# Return to project root
cd ../..
```

### 2. Fetch & Checkout Latest Version

```bash
cd .claude/hooks-daemon

# Fetch all tags
git fetch --tags

# List available versions
git tag -l | sort -V | tail -10

# Get latest stable tag
LATEST_TAG=$(git describe --tags $(git rev-list --tags --max-count=1) 2>/dev/null || echo "main")
echo "Latest version: $LATEST_TAG"

# Checkout latest version
git checkout "$LATEST_TAG"

# Verify new version
cat src/claude_code_hooks_daemon/version.py
```

### 3. Update Dependencies & Restart Daemon

```bash
cd .claude/hooks-daemon

# Update Python package
untracked/venv/bin/pip install -e .

# Restart daemon (if running)
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart || \
  echo "Daemon not running - will start on first hook call"

cd ../..
```

### 4. Verify Update & Check for Config Changes

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

# Verify daemon works
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status

# Test hooks still work
echo '{"tool_name": "Bash", "tool_input": {"command": "ls -la"}}' | \
  .claude/hooks/pre-tool-use
# Expected: {} (empty = allow)

# Test destructive git still blocked
echo '{"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}' | \
  .claude/hooks/pre-tool-use
# Expected: {"hookSpecificOutput": {"permissionDecision": "deny", ...}}
```

**IMPORTANT: No Claude Code restart needed!** The daemon restart in Step 3 is sufficient. New handlers, config changes, and code updates take effect immediately. This is a MAJOR benefit of the daemon architecture.

**Exception**: Only restart Claude Code if the update added NEW event types (new forwarding scripts in `.claude/hooks/` directory). This is rare - most updates only change handler code or add handlers to existing event types.

---

## Step 5: Discover New Handlers (After Update)

After updating, you should check for new handlers that weren't in the previous version.

### Method 1: Discover All Available Handlers (Programmatic)

This discovers ALL handlers by scanning the codebase (source of truth):

```bash
cd .claude/hooks-daemon

VENV_PYTHON=untracked/venv/bin/python

$VENV_PYTHON -c "
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry, EVENT_TYPE_MAPPING
from claude_code_hooks_daemon.core.handler import Handler
import importlib, json
from pathlib import Path

registry = HandlerRegistry()
handlers_dir = Path('src/claude_code_hooks_daemon/handlers')
result = {}

for dir_name, event_type in EVENT_TYPE_MAPPING.items():
    event_dir = handlers_dir / dir_name
    if not event_dir.is_dir():
        continue
    handlers = []
    for py_file in event_dir.glob('*.py'):
        if py_file.name.startswith('_'):
            continue
        mod = f'claude_code_hooks_daemon.handlers.{dir_name}.{py_file.stem}'
        try:
            module = importlib.import_module(mod)
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, Handler) and attr is not Handler:
                    instance = attr()
                    handlers.append({
                        'class': attr.__name__,
                        'handler_id': instance.handler_id,
                        'name': instance.name,
                        'priority': instance.priority,
                        'terminal': instance.terminal,
                        'tags': list(instance.tags) if hasattr(instance, 'tags') else [],
                        'doc': (attr.__doc__ or '').strip().split('\n')[0] if attr.__doc__ else '',
                    })
        except Exception as e:
            handlers.append({'module': mod, 'error': str(e)})
    if handlers:
        result[dir_name] = sorted(handlers, key=lambda h: h.get('priority', 99))

print(json.dumps(result, indent=2))
"
```

This outputs JSON with all handlers organized by event type, showing:
- `handler_id` - Unique identifier
- `name` - Handler name (used in config)
- `priority` - Execution order
- `terminal` - Whether it stops dispatch chain
- `tags` - Handler tags (language, function, etc.)
- `doc` - First line of docstring

### Method 2: Get Full Default Config Template

This generates the recommended default config with inline comments:

```bash
cd .claude/hooks-daemon
VENV_PYTHON=untracked/venv/bin/python

$VENV_PYTHON -c "
from claude_code_hooks_daemon.daemon.init_config import generate_config
print(generate_config(mode='full'))
"
```

This outputs a complete YAML config with:
- All available handlers
- Default settings for each
- Inline comments explaining each handler
- Recommended priority values

### Method 3: Compare with Current Config

To find handlers you're missing:

```bash
cd .claude/hooks-daemon
VENV_PYTHON=untracked/venv/bin/python

# 1. Get list of ALL available handlers
$VENV_PYTHON -c "
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry, EVENT_TYPE_MAPPING
from claude_code_hooks_daemon.core.handler import Handler
import importlib
from pathlib import Path

handlers_dir = Path('src/claude_code_hooks_daemon/handlers')
available = {}

for dir_name in EVENT_TYPE_MAPPING.keys():
    event_dir = handlers_dir / dir_name
    if not event_dir.is_dir():
        continue
    handlers = []
    for py_file in event_dir.glob('*.py'):
        if py_file.name.startswith('_'):
            continue
        mod = f'claude_code_hooks_daemon.handlers.{dir_name}.{py_file.stem}'
        try:
            module = importlib.import_module(mod)
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, Handler) and attr is not Handler:
                    instance = attr()
                    handlers.append(instance.name)
        except:
            pass
    if handlers:
        available[dir_name] = sorted(handlers)

# 2. Read current config
import yaml
from pathlib import Path
current_config = yaml.safe_load(Path('../hooks-daemon.yaml').read_text())
current = current_config.get('handlers', {})

# 3. Find missing handlers
print('Available handlers NOT in your config:\n')
for event_type, handler_names in available.items():
    event_config = current.get(event_type, {})
    missing = [h for h in handler_names if h not in event_config]
    if missing:
        print(f'{event_type}:')
        for h in missing:
            print(f'  - {h}')
"
```

### What to Do with New Handlers

1. **Read the handler documentation**:
   ```bash
   cd .claude/hooks-daemon
   # Example: read destructive_git handler docs
   cat src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py
   ```

2. **Check release notes** for handler descriptions:
   ```bash
   cat RELEASES/v2.3.0.md | grep -A 5 "New Handlers"
   ```

3. **Add handlers to your config** if desired:
   ```yaml
   # .claude/hooks-daemon.yaml
   handlers:
     pre_tool_use:
       new_handler_name:
         enabled: true
         priority: 50
         # handler-specific options...
   ```

4. **Restart daemon** to load new config:
   ```bash
   cd .claude/hooks-daemon
   untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
   ```

### Understanding Handler Tags

Handlers are tagged by language, function, and specificity. Use tags to filter:

**Language Tags**: `python`, `php`, `typescript`, `javascript`, `go`
**Function Tags**: `safety`, `tdd`, `qa-enforcement`, `workflow`, `advisory`, `validation`
**Specificity Tags**: `ec-specific`, `project-specific`

To see handlers by tag in the discovery output above, check the `tags` field.

---

## Post-Update: Handler Status Report

After updating and discovering new handlers, generate a comprehensive status report:

```bash
cd .claude/hooks-daemon
untracked/venv/bin/python scripts/handler_status.py
```

This provides a complete overview of your handler configuration:
- **All available handlers** organized by event type
- **Enabled/Disabled status** for each handler
- **Priority and terminal settings**
- **Handler tags** (for filtering and organization)
- **Handler-specific configuration** (for enabled handlers)
- **Summary statistics**

**Use this report to:**
1. **Verify** your enabled handlers are correct
2. **Identify** new handlers from the update
3. **Review** handler-specific configuration
4. **Compare** with the discovery output to see what's missing
5. **Confirm** tag filtering is working as expected

**Save for documentation:**
```bash
cd .claude/hooks-daemon
untracked/venv/bin/python scripts/handler_status.py > /tmp/handler-status.txt
```

---

## Post-Update: Planning Workflow Check (Optional)

After updating, check if you want to adopt or sync with the daemon's planning workflow system.

### Check Current Planning Setup

```bash
# Check if you already have planning docs
ls -la CLAUDE/PlanWorkflow.md 2>/dev/null
ls -la CLAUDE/Plan/ 2>/dev/null

# Check daemon's latest planning docs
cat .claude/hooks-daemon/CLAUDE/PlanWorkflow.md | head -50
```

### Scenarios

**Scenario 1: No Planning Docs Yet**

See "Post-Installation: Planning Workflow Adoption" in [LLM-INSTALL.md](https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/CLAUDE/LLM-INSTALL.md) for full adoption guide.

Quick adoption:
```bash
# Copy planning workflow docs
cp .claude/hooks-daemon/CLAUDE/PlanWorkflow.md CLAUDE/PlanWorkflow.md
mkdir -p CLAUDE/Plan

# Enable planning handlers in .claude/hooks-daemon.yaml
# (see install docs for handler config)

# Restart daemon
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

**Scenario 2: Already Using Planning System**

Check if daemon's approach has updates:
```bash
# Compare your version with daemon's version
diff CLAUDE/PlanWorkflow.md .claude/hooks-daemon/CLAUDE/PlanWorkflow.md || echo "Docs differ"
```

**If docs differ, ask user:**
```
Your project has planning docs, but the daemon's planning workflow has been updated.

Would you like to:
1. Update your planning docs to match daemon's latest version?
2. Keep your current planning docs unchanged?
3. Review differences and selectively adopt changes?
```

**If user chooses to update:**
```bash
# Backup current docs
cp CLAUDE/PlanWorkflow.md CLAUDE/PlanWorkflow.md.backup

# Update to latest
cp .claude/hooks-daemon/CLAUDE/PlanWorkflow.md CLAUDE/PlanWorkflow.md

# Review changes
diff CLAUDE/PlanWorkflow.md.backup CLAUDE/PlanWorkflow.md

# Commit if satisfied
git add CLAUDE/PlanWorkflow.md
git commit -m "Update planning workflow docs to match daemon v2.3.0"
```

**Scenario 3: Different Planning Approach**

If you have a different planning system (Jira, Linear, custom docs), you can:
- Keep planning handlers disabled
- Use daemon for code quality/safety only
- No action needed

### Planning Handlers Reference

Available planning enforcement handlers:
- `plan-workflow-guidance` (priority 45) - Guides through planning steps
- `validate-plan-number` (priority 30) - Validates plan numbering
- `block-plan-time-estimates` (priority 40) - Prevents time estimates
- `enforce-markdown-organization` (priority 35) - Enforces markdown rules (EC-specific)

**Check status:**
```bash
cd .claude/hooks-daemon
untracked/venv/bin/python scripts/handler_status.py | grep -A 1 "plan-\|markdown"
```

---

## Version-Specific Documentation

### RELEASES Directory

**Location**: `RELEASES/` (in daemon repository)

**Purpose**: Contains detailed release notes for each version.

**Files**:
- `RELEASES/README.md` - Overview of release documentation
- `RELEASES/v2.2.0.md` - v2.2.0 release notes
- `RELEASES/v2.2.1.md` - v2.2.1 release notes
- (Additional versions as released)

**Use for**:
- Understanding what changed between versions
- Reading highlights and new features
- Checking upgrade instructions per release
- Viewing test/coverage stats

**To check release notes for a specific version:**
```bash
cd .claude/hooks-daemon
cat RELEASES/v2.2.0.md
```

### UPGRADES Directory

**Location**: `CLAUDE/UPGRADES/` (in daemon repository)

**Purpose**: Contains LLM-optimized migration guides with step-by-step instructions.

**Structure**:
```
CLAUDE/UPGRADES/
├── README.md                     # Upgrade system documentation
├── upgrade-template/             # Template for new upgrade guides
├── v1/                           # Upgrades FROM v1.x versions
│   └── v1.10-to-v2.0/
└── v2/                           # Upgrades FROM v2.x versions
    └── v2.0-to-v2.1/
        ├── v2.0-to-v2.1.md       # Main upgrade guide
        ├── config-before.yaml    # Config before upgrade
        ├── config-after.yaml     # Config after upgrade
        ├── config-additions.yaml # New config to add
        ├── verification.sh       # Verification script
        └── examples/             # Expected outputs
```

**Use for**:
- Detailed step-by-step migration instructions
- Understanding breaking changes
- Config migration examples
- Verification and rollback procedures

---

## Upgrade Path Determination

When upgrading across multiple versions, follow sequential upgrade path:

### 1. Determine Current and Target Versions

```bash
cd .claude/hooks-daemon

# Current version
CURRENT=$(cat src/claude_code_hooks_daemon/version.py | grep "__version__" | cut -d'"' -f2)
echo "Current: $CURRENT"

# Available versions
git fetch --tags
LATEST=$(git describe --tags $(git rev-list --tags --max-count=1))
echo "Latest: $LATEST"
```

### 2. Find Available Upgrade Guides

```bash
cd .claude/hooks-daemon
ls -la CLAUDE/UPGRADES/v*/
```

### 3. Follow Sequential Upgrades

**Example**: Upgrading from v2.0 to v2.2

1. Read `CLAUDE/UPGRADES/v2/v2.0-to-v2.1/v2.0-to-v2.1.md`
2. Apply v2.0 to v2.1 upgrade steps
3. Read `CLAUDE/UPGRADES/v2/v2.1-to-v2.2/v2.1-to-v2.2.md` (if exists)
4. Apply v2.1 to v2.2 upgrade steps
5. Verify with `verification.sh` at each step

**If no upgrade guide exists**: Check `RELEASES/vX.Y.Z.md` for that version's upgrade instructions section.

---

## Upgrade Types

### Patch Upgrades (v2.2.0 -> v2.2.1)

- Bug fixes only
- No config changes required
- No breaking changes
- Just update code and restart daemon

```bash
cd .claude/hooks-daemon
git fetch --tags && git checkout v2.2.1
untracked/venv/bin/pip install -e .
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

### Minor Upgrades (v2.1.0 -> v2.2.0)

- New features/handlers
- May have config additions (backward compatible)
- No breaking changes
- Check UPGRADES guide for new config options

```bash
# After code update, check for new config options
cat CLAUDE/UPGRADES/v2/v2.1-to-v2.2/config-additions.yaml
# Add relevant new options to .claude/hooks-daemon.yaml
```

### Major Upgrades (v2.x -> v3.0)

- Breaking changes likely
- Config structure may change
- Handler API may change
- MUST follow UPGRADES guide step-by-step
- Backup everything before proceeding

```bash
# Always read the full upgrade guide first
cat CLAUDE/UPGRADES/v2/v2.x-to-v3.0/v2.x-to-v3.0.md

# Follow migration steps exactly
```

---

## Config Migration

### Check for Config Changes

After updating code, compare your config with the new template:

```bash
cd .claude/hooks-daemon

# View default config template
cat install.py | grep -A 100 "DEFAULT_CONFIG"

# Or regenerate fresh template (doesn't overwrite existing)
untracked/venv/bin/python -c "
from install import generate_hooks_daemon_config
print(generate_hooks_daemon_config())
"
```

### Apply Config Additions

If upgrade guide includes `config-additions.yaml`:

```bash
# Read the additions
cat CLAUDE/UPGRADES/v2/v2.0-to-v2.1/config-additions.yaml

# Manually merge into your config
# (DO NOT blindly replace - merge new sections only)
```

### Validate Config

```bash
cd .claude/hooks-daemon
untracked/venv/bin/python -c "
import yaml
from pathlib import Path
config = yaml.safe_load(Path('../hooks-daemon.yaml').read_text())
print('Config valid:', 'handlers' in config and 'daemon' in config)
"
```

---

## Verification Steps

### Quick Verification

```bash
cd .claude/hooks-daemon
VENV_PYTHON=untracked/venv/bin/python

# 1. Version check
$VENV_PYTHON -c "from claude_code_hooks_daemon.version import __version__; print(f'Version: {__version__}')"

# 2. Daemon status
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status

# 3. Hook test
echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | ../../.claude/hooks/pre-tool-use
```

### Full Verification (for major upgrades)

```bash
cd .claude/hooks-daemon

# Run tests (optional - for thorough verification)
./scripts/qa/run_tests.sh

# Check all QA passes
./scripts/qa/run_all.sh
```

### Run Version-Specific Verification

If upgrade guide includes verification script:

```bash
cd .claude/hooks-daemon
bash CLAUDE/UPGRADES/v2/v2.0-to-v2.1/verification.sh
```

---

## Rollback Instructions

### Quick Rollback

```bash
cd .claude/hooks-daemon

# Stop daemon
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true

# Restore config backup
cp ../hooks-daemon.yaml.backup ../hooks-daemon.yaml

# Find previous version tag
git tag -l | sort -V

# Checkout previous version
git checkout vX.Y.Z  # Replace with your previous version

# Reinstall
untracked/venv/bin/pip install -e .

# Verify rollback
cat src/claude_code_hooks_daemon/version.py
```

### If Rollback Fails

```bash
# Nuclear option - reinstall from scratch
cd .claude
rm -rf hooks-daemon

# Follow fresh install instructions
# See: LLM-INSTALL.md
```

---

## Troubleshooting

### Update Fails to Pull

```bash
cd .claude/hooks-daemon

# Check for local modifications
git status

# If dirty, stash changes
git stash

# Try update again
git fetch --tags
git checkout "$LATEST_TAG"

# Restore stashed changes (if any)
git stash pop
```

### Daemon Won't Start After Update

```bash
cd .claude/hooks-daemon

# Check for import errors
untracked/venv/bin/python -c "import claude_code_hooks_daemon; print('OK')"

# If error, reinstall dependencies
untracked/venv/bin/pip install -e . --force-reinstall

# Check logs
cat untracked/daemon.log 2>/dev/null || echo "No logs"
```

### Hooks Don't Work After Update

1. **Restart daemon** (daemon restart is sufficient for most updates):
   ```bash
   cd .claude/hooks-daemon
   untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
   ```
2. Check hook forwarders exist:
   ```bash
   ls -la ../.claude/hooks/
   ```
3. Test hook directly:
   ```bash
   echo '{"tool_name":"Bash","tool_input":{"command":"test"}}' | ../.claude/hooks/pre-tool-use
   ```
4. **Restart Claude Code session** (ONLY needed if new event types were added - rare):
   - Check if `.claude/hooks/` has new files compared to before update
   - If yes, restart Claude Code to reload settings.json
   - If no new hook files, daemon restart is sufficient

### Config Validation Errors

```bash
cd .claude/hooks-daemon

# Validate YAML syntax
untracked/venv/bin/python -c "
import yaml
try:
    yaml.safe_load(open('../hooks-daemon.yaml'))
    print('YAML syntax OK')
except Exception as e:
    print(f'YAML error: {e}')
"
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

## Checking for Updates

### From User's Project

Ask your LLM to run:

```bash
cd .claude/hooks-daemon
git fetch --tags
CURRENT=$(cat src/claude_code_hooks_daemon/version.py | grep "__version__" | cut -d'"' -f2)
LATEST=$(git describe --tags $(git rev-list --tags --max-count=1) 2>/dev/null)
echo "Current: $CURRENT"
echo "Latest: $LATEST"
if [ "$CURRENT" != "${LATEST#v}" ]; then
  echo "Update available!"
else
  echo "Already at latest version"
fi
```

### Reading Release Notes Before Update

```bash
cd .claude/hooks-daemon
git fetch --tags
LATEST=$(git describe --tags $(git rev-list --tags --max-count=1))

# Preview release notes (without checking out)
git show "$LATEST:RELEASES/${LATEST}.md" 2>/dev/null || \
  echo "Release notes will be available after checkout"
```

---

## Support

If you encounter update issues:

1. **Check daemon logs**:
   ```bash
   cat .claude/hooks-daemon/untracked/daemon.log
   ```

2. **Run debug script**:
   ```bash
   .claude/hooks-daemon/scripts/debug_info.py /tmp/debug_report.md
   cat /tmp/debug_report.md
   ```

3. **Report issue**:
   - GitHub: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues
   - Include: current version, target version, error output, daemon logs

---

**Update Date:** `date +%Y-%m-%d`
