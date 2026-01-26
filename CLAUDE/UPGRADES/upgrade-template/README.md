# Upgrade Guide: vX.Y → vX.Z

## Summary

[One-paragraph description of what changed and why users should upgrade]

Example:
"This upgrade adds the YOLO Container Detection handler for SessionStart events, providing automatic detection of YOLO container environments with contextual information to Claude. No breaking changes. Recommended for all users running Claude Code in container environments."

## Version Compatibility

- **Source Version**: vX.Y (minimum version you can upgrade from)
- **Target Version**: vX.Z (version after upgrade)
- **Minimum Claude Code Version**: X.Y.Z (if applicable)
- **Supports Rollback**: Yes/No
- **Breaking Changes**: Yes/No
- **Config Migration Required**: Yes/No

## Pre-Upgrade Checklist

Before starting the upgrade:

- [ ] Backup `.claude/hooks-daemon.yaml`
  ```bash
  cp .claude/hooks-daemon.yaml .claude/hooks-daemon.yaml.backup
  ```
- [ ] Verify daemon is stopped
  ```bash
  cd .claude/hooks-daemon
  untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop
  ```
- [ ] Check for uncommitted changes
  ```bash
  cd .claude/hooks-daemon
  git status
  ```
- [ ] Read "Breaking Changes" section below (if any)

## Changes Overview

### New Features

- Feature 1: Description
- Feature 2: Description

### New Handlers

- **`handler_name`** (event: EventType, priority: XX, terminal: Yes/No)
  - Description: What it does
  - Config: Configuration options
  - Use case: When/why to use it

### Modified Handlers

- **`handler_name`**
  - What changed: Description
  - Why: Rationale
  - Migration: What users need to do

### Removed Handlers

- **`handler_name`**
  - Deprecation reason: Why it was removed
  - Alternatives: What to use instead
  - Migration: Steps to migrate

### Configuration Changes

#### New Config Fields

```yaml
handlers:
  event_type:
    new_handler:
      enabled: true
      new_field: value
```

#### Renamed/Removed Fields

- `old_field` → `new_field` (renamed)
- `deprecated_field` → removed (no replacement)

#### Default Value Changes

- `field_name`: `old_default` → `new_default` (why changed)

### Hook Script Changes

- Updated forwarder scripts (if applicable)
- init.sh modifications (if applicable)
- New hook events registered (if applicable)

### Dependency Changes

- New dependencies: `package>=version`
- Updated dependencies: `package>=new_version`
- Removed dependencies: `deprecated_package`

## Step-by-Step Upgrade Instructions

### 1. Update Daemon Code

**Option A - Using Git** (recommended if you cloned the repo):

```bash
cd .claude/hooks-daemon
git fetch origin
git checkout vX.Z  # Specific tag
# Or: git pull origin main  # Latest main branch
```

**Option B - Manual Download** (if not using git):

```bash
cd .claude
mv hooks-daemon hooks-daemon.backup
wget https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/archive/vX.Z.tar.gz
tar -xzf vX.Z.tar.gz
mv claude-code-hooks-daemon-X.Z hooks-daemon
cd hooks-daemon
```

### 2. Update Dependencies

```bash
cd .claude/hooks-daemon
untracked/venv/bin/pip install -e .
```

**Expected output**:
```
Successfully installed claude-code-hooks-daemon-X.Z.0
```

### 3. Update Configuration File

**File**: `.claude/hooks-daemon.yaml`

**Action**: [Add/Modify/Remove] the following sections.

**Important**: See supporting files in this directory:
- `config-before.yaml` - Shows config before upgrade
- `config-after.yaml` - Shows complete config after upgrade
- `config-additions.yaml` - Shows **only what to add** (merge this in)

**Option 1 - Manual Edit** (recommended):

Add/modify the following in your `.claude/hooks-daemon.yaml`:

```yaml
# [Show exact YAML changes with comments explaining each field]
handlers:
  event_type:
    new_handler:
      enabled: true
      option1: value1  # Comment explaining option1
      option2: value2  # Comment explaining option2
```

**Option 2 - Copy Example** (for fresh installs):

If starting fresh, you can copy the complete example:

```bash
cp .claude/hooks-daemon/CLAUDE/UPGRADES/vX/vX.Y-to-vX.Z/config-after.yaml .claude/hooks-daemon.yaml
```

**Why These Changes**:
[Explain the rationale for configuration changes]

### 4. Update Hook Scripts (if needed)

**Files**: `.claude/hooks/*`

**Action**: Run installer to update scripts:

```bash
cd .claude/hooks-daemon
untracked/venv/bin/python install.py --project-root ../..
```

**Prompts**:
- "Overwrite existing hooks?" → **Yes** (update forwarder scripts)
- "Overwrite existing config?" → **No** (keep your modified config)

**Note**: Only needed if hook scripts changed in this version.

### 5. Register New Handlers (if needed)

**File**: `src/claude_code_hooks_daemon/hooks/{event_type}.py`

Check if new handlers require manual registration. Most handlers auto-register via config.

[Include specific registration code if needed]

### 6. Clean Up Deprecated Handlers (if any)

If handlers were removed, delete their entries from `.claude/hooks-daemon.yaml`:

```yaml
# Remove these lines:
handlers:
  event_type:
    old_handler:  # <-- Delete this entire section
      enabled: true
```

### 7. Restart Daemon

```bash
cd .claude/hooks-daemon
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

**Expected output**:
```
Daemon stopped successfully
Daemon started with PID: XXXXX
```

## Breaking Changes

[If no breaking changes, write: "No breaking changes in this release."]

### Breaking Change 1: [Title]

**What broke**:
[Describe exactly what no longer works]

**Why**:
[Explain rationale for the breaking change]

**Who is affected**:
[Describe which users/use cases are impacted]

**Migration Steps**:

1. Step 1
2. Step 2
3. Step 3

**Example**:

Before (vX.Y):
```yaml
old_config:
  field: value
```

After (vX.Z):
```yaml
new_config:
  renamed_field: value
```

**Rollback** (if migration doesn't work):
[Steps to undo this specific change]

## Verification Steps

### 1. Verify Version Updated

```bash
cd .claude/hooks-daemon
cat src/claude_code_hooks_daemon/version.py
```

**Expected output**:
```python
__version__ = "X.Z.0"
```

### 2. Verify Daemon Starts

```bash
cd .claude/hooks-daemon
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli status
```

**Expected output** (daemon running):
```
Daemon is running (PID: XXXXX)
Socket: .claude/hooks-daemon/untracked/venv/socket
```

**Expected output** (daemon not running - normal for lazy startup):
```
Daemon is not running
```

### 3. Test Hook Execution

```bash
echo '{"hook_event_name":"EventType","tool_name":"Bash","tool_input":{"command":"echo test"}}' | \
  .claude/hooks/event-type
```

**Expected output**:
```json
{
  "decision": "allow",
  "reason": null,
  "context": []
}
```

### 4. Test New Handlers

[Specific tests for new handlers added in this version]

Example:
```bash
# Test SessionStart hook with new handler
echo '{"hook_event_name":"SessionStart","source":"new"}' | \
  .claude/hooks/session-start
```

**Expected context** (if new handler is advisory):
```json
{
  "decision": "allow",
  "reason": null,
  "context": ["New handler message here"]
}
```

### 5. Run QA Suite (for development)

If you're developing handlers:

```bash
cd .claude/hooks-daemon
./scripts/qa/run_all.sh
```

**Expected output**:
```
✅ All QA checks passed
Coverage: 95%+
```

### 6. Run Automated Verification Script

This directory includes an automated verification script:

```bash
cd .claude/hooks-daemon
bash CLAUDE/UPGRADES/vX/vX.Y-to-vX.Z/verification.sh
```

**Expected output**:
```
✅ Version check: PASS
✅ Config validation: PASS
✅ Daemon startup: PASS
✅ Hook execution: PASS
✅ New handlers: PASS
```

## Rollback Instructions

If upgrade fails or causes issues:

### 1. Stop Daemon

```bash
cd .claude/hooks-daemon
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli stop
```

### 2. Restore Configuration Backup

```bash
cp .claude/hooks-daemon.yaml.backup .claude/hooks-daemon.yaml
```

### 3. Revert Daemon Code

**Option A - Git** (if you used git for upgrade):

```bash
cd .claude/hooks-daemon
git checkout vX.Y  # Previous working version
git checkout main  # If using main branch, revert commit
```

**Option B - Manual** (if you backed up directory):

```bash
cd .claude
rm -rf hooks-daemon
mv hooks-daemon.backup hooks-daemon
```

### 4. Reinstall Previous Dependencies

```bash
cd .claude/hooks-daemon
untracked/venv/bin/pip install -e .
```

### 5. Restart Daemon

```bash
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

### 6. Verify Rollback

```bash
cat src/claude_code_hooks_daemon/version.py
# Should show: __version__ = "X.Y.0"
```

## Known Issues

[List known problems with this version and their workarounds]

### Issue 1: [Title]

**Description**: [What doesn't work or behaves unexpectedly]

**Affected Versions**: vX.Z.0 (fixed in vX.Z.1)

**Workaround**:
```bash
[Steps to work around the issue]
```

**Status**: Fixed in vX.Z.1 / Open issue #123 / Will be fixed in next release

---

[If no known issues: "No known issues at this time."]

## Additional Notes

[Any other information users should know]

Examples:
- Performance improvements
- Deprecation warnings
- Future breaking changes planned
- Recommended config changes (optional but beneficial)

## Support

If you encounter issues during upgrade:

1. **Check daemon logs**:
   ```bash
   cat .claude/hooks-daemon/untracked/venv/daemon.log
   ```

2. **Try rollback** (see "Rollback Instructions" above)

3. **Check verification steps** (see "Verification Steps" above)

4. **Report issue**:
   - GitHub: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues
   - Include: version info, error output, daemon logs, steps you followed

5. **Emergency fix**:
   ```bash
   # If daemon won't stop
   pkill -f claude_code_hooks_daemon

   # If socket stuck
   rm .claude/hooks-daemon/untracked/venv/socket
   ```

## References

- [Upgrade system documentation](../README.md)
- [Handler development guide](../../HANDLER_DEVELOPMENT.md)
- [Release notes](https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/releases/tag/vX.Z.0)
- [Full changelog](../../CHANGELOG.md)
