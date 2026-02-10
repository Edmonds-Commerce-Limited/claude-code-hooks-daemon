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

## Architecture Overview

The upgrade system uses a **two-layer architecture**:

- **Layer 1** (`scripts/upgrade.sh`): Minimal curl-fetched script (~130 lines). Detects project root, fetches tags, determines target version, then delegates to Layer 2 via `exec`.
- **Layer 2** (`scripts/upgrade_version.sh`): Version-specific orchestrator implementing **"Upgrade = Clean Reinstall + Config Preservation"**. Sources a shared modular library (`scripts/install/*.sh`) for all operations.

**Key principle**: Upgrade produces the same clean state as a fresh install, while preserving only user config customizations via a diff/merge/validate pipeline.

### Config Preservation Pipeline

During upgrade, user customizations are preserved automatically:

1. **Backup**: Current config saved to timestamped backup file
2. **Snapshot**: Full state snapshot saved (hooks, config, settings.json) for rollback
3. **Extract**: Diff between old default config and user config identifies customizations
4. **Checkout**: New version code checked out (clean reinstall of code)
5. **Merge**: User customizations merged into new default config
6. **Validate**: Merged config validated for structural correctness
7. **Report**: Any incompatibilities reported to the user

If any step fails, the upgrade rolls back to the snapshot automatically.

---

## RECOMMENDED: Fetch, Review, and Run (Safest Method)

**CRITICAL: Fetch the upgrade script, review it, then run it** - This avoids curl pipe shell patterns that our own security handlers block.

The upgrade script itself handles all git operations (fetch, checkout, pull, etc.). You just need to download it, make sure you're comfortable with what it does, then run it.

### Standard Upgrade Process

```bash
# Download the latest upgrade script
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/scripts/upgrade.sh -o /tmp/upgrade.sh

# Review the script to ensure you're comfortable with it
less /tmp/upgrade.sh

# Run it (it handles all the git operations)
bash /tmp/upgrade.sh

# Clean up
rm /tmp/upgrade.sh
```

This works for **any version** (including pre-v2.5.0 installations) and is the safest method since you can inspect what the script will do before running it. The script handles all the git fetch/checkout/pull operations.

### Upgrade to Specific Version

```bash
# Fetch and run with version argument
curl -fsSL https://raw.githubusercontent.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/main/scripts/upgrade.sh -o /tmp/upgrade.sh
bash /tmp/upgrade.sh v2.5.0
rm /tmp/upgrade.sh
```

### What the Script Does (Two-Layer Flow)

**Layer 1** (the curl-fetched script):
- Auto-detects your project root (works from any subdirectory)
- Fetches latest tags from remote
- Determines target version (latest tag or specified argument)
- Delegates to Layer 2 via `exec`

**Layer 2** (version-specific orchestrator):
- Creates state snapshot for rollback (hooks, config, settings.json)
- Backs up user config
- Extracts user customizations (diff against old defaults)
- Stops the daemon safely
- Checks out target version code
- Recreates virtual environment (clean venv)
- Deploys hook scripts and slash commands
- Merges user customizations into new default config
- Validates merged config
- Reports any incompatibilities
- Starts daemon and verifies running
- Cleans up old snapshots (keeps 5 most recent)
- Rolls back automatically on any failure

**Legacy fallback**: If upgrading to a version that predates the two-layer architecture, Layer 1 falls back to a legacy inline upgrade (stop, checkout, pip install, restart). This is expected for older tags.

### Why Fetch from GitHub?

**Never use the local upgrade script** (`.claude/hooks-daemon/scripts/upgrade.sh`) because:

1. **Bug fixes** - Your local script might have bugs fixed in newer versions
2. **New features** - Latest script may handle new migration scenarios
3. **Better safety** - Improved rollback and error handling
4. **Bootstrap solution** - Works for all versions, even pre-v2.5.0
5. **Consistency** - Everyone uses the same upgrade logic

This is the same pattern used by `rustup`, `nvm`, `homebrew`, and other modern tooling.

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

### Method 2: Get Full Default Config Template

```bash
cd .claude/hooks-daemon
VENV_PYTHON=untracked/venv/bin/python

$VENV_PYTHON -c "
from claude_code_hooks_daemon.daemon.init_config import generate_config
print(generate_config(mode='full'))
"
```

### Method 3: Compare with Current Config

To find handlers you're missing:

```bash
cd .claude/hooks-daemon
VENV_PYTHON=untracked/venv/bin/python

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

import yaml
from pathlib import Path
current_config = yaml.safe_load(Path('../hooks-daemon.yaml').read_text())
current = current_config.get('handlers', {})

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
   cat src/claude_code_hooks_daemon/handlers/pre_tool_use/destructive_git.py
   ```

2. **Check release notes** for handler descriptions:
   ```bash
   cat RELEASES/v2.3.0.md | grep -A 5 "New Handlers"
   ```

3. **Add handlers to your config** if desired:
   ```yaml
   handlers:
     pre_tool_use:
       new_handler_name:
         enabled: true
         priority: 50
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

---

## Post-Update: Handler Status Report

After updating and discovering new handlers, generate a comprehensive status report:

```bash
cd .claude/hooks-daemon
untracked/venv/bin/python scripts/handler_status.py
```

---

## Post-Update: Planning Workflow Check (Optional)

After updating, check if you want to adopt or sync with the daemon's planning workflow system.

### Check Current Planning Setup

```bash
ls -la CLAUDE/PlanWorkflow.md 2>/dev/null
ls -la CLAUDE/Plan/ 2>/dev/null
```

### Scenarios

**Scenario 1: No Planning Docs Yet** - See "Post-Installation: Planning Workflow Adoption" in LLM-INSTALL.md.

**Scenario 2: Already Using Planning System** - Check for updates:
```bash
diff CLAUDE/PlanWorkflow.md .claude/hooks-daemon/CLAUDE/PlanWorkflow.md || echo "Docs differ"
```

**Scenario 3: Different Planning Approach** - Keep planning handlers disabled.

---

## Version-Specific Documentation

### RELEASES Directory

**Location**: `RELEASES/` (in daemon repository)

Contains detailed release notes for each version. Use for understanding what changed between versions.

```bash
cd .claude/hooks-daemon
cat RELEASES/v2.2.0.md
```

### UPGRADES Directory

**Location**: `CLAUDE/UPGRADES/` (in daemon repository)

Contains LLM-optimized migration guides with step-by-step instructions, config examples, and verification scripts.

```
CLAUDE/UPGRADES/
├── README.md                     # Upgrade system documentation
├── upgrade-template/             # Template for new upgrade guides
├── v1/                           # Upgrades FROM v1.x versions
└── v2/                           # Upgrades FROM v2.x versions
    └── v2.0-to-v2.1/
        ├── v2.0-to-v2.1.md       # Main upgrade guide
        ├── config-before.yaml    # Config before upgrade
        ├── config-after.yaml     # Config after upgrade
        ├── config-additions.yaml # New config to add
        ├── verification.sh       # Verification script
        └── examples/             # Expected outputs
```

---

## Upgrade Path Determination

When upgrading across multiple versions, follow sequential upgrade path:

### 1. Determine Current and Target Versions

```bash
cd .claude/hooks-daemon

CURRENT=$(cat src/claude_code_hooks_daemon/version.py | grep "__version__" | cut -d'"' -f2)
echo "Current: $CURRENT"

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

- Bug fixes only, no config changes, no breaking changes
- Just update code and restart daemon

```bash
cd .claude/hooks-daemon
git fetch --tags && git checkout v2.2.1
untracked/venv/bin/pip install -e .
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

### Minor Upgrades (v2.1.0 -> v2.2.0)

- New features/handlers, may have config additions (backward compatible)
- Check UPGRADES guide for new config options

### Major Upgrades (v2.x -> v3.0)

- Breaking changes likely, config structure may change
- MUST follow UPGRADES guide step-by-step

---

## Rollback Instructions

### Automatic Rollback (via Layer 2 Upgrade Script)

The Layer 2 upgrade orchestrator (`scripts/upgrade_version.sh`) creates state snapshots before any changes. If the upgrade fails at any step, it automatically restores the snapshot.

Snapshots are stored at:
```
.claude/hooks-daemon/untracked/upgrade-snapshots/{timestamp}/
├── manifest.json       # Metadata: version, timestamp, files list
└── files/
    ├── hooks/          # All hook forwarder scripts
    ├── hooks-daemon.yaml
    ├── settings.json
    └── init.sh
```

The 5 most recent snapshots are retained; older ones are automatically cleaned up.

### Manual Rollback (from Snapshot)

If you need to manually restore from a snapshot:

```bash
DAEMON_DIR=.claude/hooks-daemon

# List available snapshots
ls -la "$DAEMON_DIR/untracked/upgrade-snapshots/"

# Pick the most recent
SNAPSHOT=$(ls -d "$DAEMON_DIR/untracked/upgrade-snapshots/"* | sort -r | head -1)
echo "Restoring from: $SNAPSHOT"

# Stop daemon
"$DAEMON_DIR/untracked/venv/bin/python" -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true

# Restore config
cp "$SNAPSHOT/files/hooks-daemon.yaml" .claude/hooks-daemon.yaml

# Restore settings
cp "$SNAPSHOT/files/settings.json" .claude/settings.json 2>/dev/null || true

# Restore hooks
cp "$SNAPSHOT/files/hooks/"* .claude/hooks/ 2>/dev/null || true

# Check manifest for original version
cat "$SNAPSHOT/manifest.json"

# Checkout original version (from manifest)
cd "$DAEMON_DIR"
git checkout <version-from-manifest>
untracked/venv/bin/pip install -e .

# Restart
cd ../..
"$DAEMON_DIR/untracked/venv/bin/python" -m claude_code_hooks_daemon.daemon.cli restart
```

### Quick Rollback (Config Only)

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

## Config Migration

### Automatic (via Layer 2 Upgrade)

The Layer 2 upgrade script handles config migration automatically using the config preservation pipeline:

1. Backs up current config
2. Extracts your customizations (diff against old defaults)
3. Merges customizations into new version's defaults
4. Validates the merged result
5. Reports any incompatibilities

You only need to act if incompatibilities are reported.

### Manual Config Migration

After updating code, compare your config with the new template:

```bash
cd .claude/hooks-daemon
VENV_PYTHON=untracked/venv/bin/python

# Generate new default config
$VENV_PYTHON -c "
from claude_code_hooks_daemon.daemon.init_config import generate_config
print(generate_config(mode='full'))
" > /tmp/new_default_config.yaml

# Diff against your config
diff ../hooks-daemon.yaml /tmp/new_default_config.yaml
```

### Config Preservation CLI

The daemon includes CLI commands for config operations:

```bash
VENV_PYTHON=.claude/hooks-daemon/untracked/venv/bin/python

# Diff: find customizations between old default and user config
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli config-diff \
  --old-default /tmp/old_default.yaml \
  --user-config .claude/hooks-daemon.yaml

# Merge: apply customizations to new default
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli config-merge \
  --new-default /tmp/new_default.yaml \
  --custom-diff /tmp/custom_diff.yaml

# Validate: check config structure
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli config-validate \
  --config .claude/hooks-daemon.yaml
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

---

## Troubleshooting

**All commands below are run from the PROJECT ROOT** (not from inside `.claude/hooks-daemon/`).

### "PROTECTION NOT ACTIVE" Error During Upgrade

**This is expected during upgrade.** When the daemon is stopped for code checkout, hook forwarders will report this error. It does NOT mean your system is broken. Continue with the upgrade steps. The daemon will be restarted as part of the upgrade process.

### Update Fails to Pull

```bash
git -C .claude/hooks-daemon status
git -C .claude/hooks-daemon stash
git -C .claude/hooks-daemon fetch --tags
git -C .claude/hooks-daemon checkout "$LATEST_TAG"
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
python3 -c "
import yaml
try:
    yaml.safe_load(open('.claude/hooks-daemon.yaml'))
    print('YAML syntax OK')
except Exception as e:
    print(f'YAML error: {e}')
"
```

### Layer 2 Upgrader Not Found (Legacy Fallback)

If you see "Layer 2 upgrader not found" during upgrade, the currently installed version predates the two-layer architecture. The legacy fallback (stop, checkout, pip install, restart) will handle the upgrade. After upgrading, future upgrades will use the full Layer 2 flow.

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
