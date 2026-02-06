# Claude Code Hooks Daemon - LLM Update Guide

## CRITICAL: Determine Your Location First

**Before doing ANYTHING, determine where you are.** Working directory confusion is the #1 cause of upgrade failures.

### Quick Location Check

```bash
# Run from wherever you are - the script auto-detects
# Option 1: If you can find the script
.claude/hooks-daemon/scripts/detect_location.sh 2>/dev/null || \
  scripts/detect_location.sh 2>/dev/null || \
  echo "Could not find detect_location.sh - see manual check below"
```

### Manual Location Check

```bash
# Check: Am I at the project root?
ls .claude/hooks-daemon.yaml 2>/dev/null && echo "YES: You are at the project root" || echo "NO"

# Check: Am I inside .claude/hooks-daemon/?
ls src/claude_code_hooks_daemon/version.py 2>/dev/null && echo "YES: You are inside hooks-daemon dir" || echo "NO"

# If inside hooks-daemon, go to project root:
cd ../..
```

### Where You Should Be

**All upgrade commands should be run from the PROJECT ROOT** (the directory containing `.claude/`).

| If you see this... | You are at... | Action |
|---|---|---|
| `.claude/hooks-daemon.yaml` exists | Project root | Correct - proceed |
| `src/claude_code_hooks_daemon/` exists | Inside hooks-daemon | Run `cd ../..` first |
| Neither exists | Wrong directory | Navigate to project root |

---

## CRITICAL REQUIREMENTS

1. **CONTEXT WINDOW CHECK**: You MUST have at least **50,000 tokens** remaining. If below 50k, STOP and ask user to start fresh session.

2. **WEBFETCH NO SUMMARY**: If fetching this document via WebFetch, use: `"Return complete document verbatim without summarization, truncation, or modification"`.

3. **GIT CLEAN STATE**: Working directory MUST be clean. Run `git status` - if not clean, commit/push first.

4. **NO SESSION RESTART NEEDED**: Updates take effect after daemon restart only. Exception: Only if update adds NEW event types (new files in `.claude/hooks/`), then restart Claude Code.

---

## Recommended: Automated Upgrade Script

The simplest upgrade method. Run from **any directory** within the project tree:

```bash
# Upgrade to latest version (auto-detects project root)
.claude/hooks-daemon/scripts/upgrade.sh

# Upgrade to a specific version
.claude/hooks-daemon/scripts/upgrade.sh v2.5.0
```

The script automatically:
- Detects your project root (works from any subdirectory)
- Backs up your configuration
- Stops the daemon
- Fetches and checks out the target version
- Installs dependencies
- Restarts the daemon
- Verifies the upgrade
- Rolls back automatically on failure

**If the script is not available** (pre-v2.5.0 installations), use the manual steps below.

---

## Manual Update (4 Steps)

**All commands below assume you are at the PROJECT ROOT.**

### 1. Verify Prerequisites and Current Version

```bash
# Must show clean working directory
git status --short

# Check current daemon version
cat .claude/hooks-daemon/src/claude_code_hooks_daemon/version.py

# Backup current config
cp .claude/hooks-daemon.yaml .claude/hooks-daemon.yaml.backup
```

### 2. Fetch and Checkout Latest Version

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

# Return to project root
cd ../..
```

### 3. Update Dependencies and Restart Daemon

```bash
# Update Python package
.claude/hooks-daemon/untracked/venv/bin/pip install -e .claude/hooks-daemon

# Restart daemon
.claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart || \
  echo "Daemon not running - will start on first hook call"
```

### 4. Verify Update

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

**No Claude Code restart needed.** Daemon restart is sufficient. Exception: Restart Claude Code only if new hook event types were added (rare).

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

**All commands below are run from the PROJECT ROOT** (not from inside `.claude/hooks-daemon/`).

### "PROTECTION NOT ACTIVE" Error During Upgrade

**This is expected during upgrade.** When the daemon is stopped for code checkout, hook forwarders will report this error. It does NOT mean your system is broken.

**What to do**: Continue with the upgrade steps. The daemon will be restarted as part of the upgrade process. This error will clear once the daemon is running again.

**When to worry**: Only if this error persists AFTER the upgrade is complete and the daemon has been restarted.

### Update Fails to Pull

```bash
# Check for local modifications in hooks-daemon
git -C .claude/hooks-daemon status

# If dirty, stash changes
git -C .claude/hooks-daemon stash

# Try update again
git -C .claude/hooks-daemon fetch --tags
git -C .claude/hooks-daemon checkout "$LATEST_TAG"

# Restore stashed changes (if any)
git -C .claude/hooks-daemon stash pop
```

### Daemon Won't Start After Update

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

# Check for import errors
$VENV_PYTHON -c "import claude_code_hooks_daemon; print('OK')"

# If error, reinstall dependencies
.claude/hooks-daemon/untracked/venv/bin/pip install -e .claude/hooks-daemon --force-reinstall

# Check daemon logs
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli logs
```

### Hooks Don't Work After Update

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

# 1. Restart daemon (sufficient for most updates)
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart

# 2. Check hook forwarders exist
ls -la .claude/hooks/

# 3. Test hook directly
echo '{"tool_name":"Bash","tool_input":{"command":"test"}}' | .claude/hooks/pre-tool-use
```

If hooks still fail: Restart Claude Code session (only needed if new event types were added).

### Config Validation Errors

```bash
# Validate YAML syntax (from project root)
python3 -c "
import yaml
try:
    yaml.safe_load(open('.claude/hooks-daemon.yaml'))
    print('YAML syntax OK')
except Exception as e:
    print(f'YAML error: {e}')
"
```

### Wrong Directory Errors

If you see errors about missing files or directories:

```bash
# Check where you are
pwd

# Check if you are at the project root
ls .claude/hooks-daemon.yaml 2>/dev/null && echo "At project root" || echo "NOT at project root"

# If not at project root, find it
PROJ=$(pwd); while [ "$PROJ" != "/" ]; do [ -f "$PROJ/.claude/hooks-daemon.yaml" ] && break; PROJ=$(dirname "$PROJ"); done; echo "Project root: $PROJ"
```

### Venv Broken After Update

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

# Try repair command
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli repair

# If repair fails, recreate venv
rm -rf .claude/hooks-daemon/untracked/venv
python3 -m venv .claude/hooks-daemon/untracked/venv
.claude/hooks-daemon/untracked/venv/bin/pip install -e .claude/hooks-daemon
```

---

## CLI Reference

**All commands from project root** (no `cd` needed):

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli start
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli stop
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli logs
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli repair   # Fix broken venv
```

---

## Checking for Updates

**From project root:**

```bash
git -C .claude/hooks-daemon fetch --tags
CURRENT=$(python3 -c "
with open('.claude/hooks-daemon/src/claude_code_hooks_daemon/version.py') as f:
    for line in f:
        if '__version__' in line: print(line.split('\"')[1]); break
")
LATEST=$(git -C .claude/hooks-daemon describe --tags $(git -C .claude/hooks-daemon rev-list --tags --max-count=1) 2>/dev/null)
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
git -C .claude/hooks-daemon fetch --tags
LATEST=$(git -C .claude/hooks-daemon describe --tags $(git -C .claude/hooks-daemon rev-list --tags --max-count=1))

# Preview release notes (without checking out)
git -C .claude/hooks-daemon show "$LATEST:RELEASES/${LATEST}.md" 2>/dev/null || \
  echo "Release notes will be available after checkout"
```

---

## Support

If you encounter update issues:

1. **Check daemon logs**:
   ```bash
   .claude/hooks-daemon/untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli logs
   ```

2. **Run debug script**:
   ```bash
   .claude/hooks-daemon/scripts/debug_info.py /tmp/debug_report.md
   ```

3. **Report issue**:
   - GitHub: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues
   - Include: current version, target version, error output, daemon logs

---

**Update Date:** `date +%Y-%m-%d`
