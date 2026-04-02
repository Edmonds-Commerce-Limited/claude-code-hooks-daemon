# Upgrade Guide: v2.29 → v2.30

## What Changed

v2.30.0 adds `get_claude_md()` as an abstract method on the `Handler` base class. **This is a breaking change for project-level handlers.** Any custom handler written before v2.30.0 that does not implement `get_claude_md()` will fail to load. The fix is a one-line addition to each affected handler. Built-in handlers are not affected (already updated).

## Version Compatibility

- **Source Version**: v2.29.x (minimum version you can upgrade from)
- **Target Version**: v2.30.0 (version after upgrade)
- **Supports Rollback**: Yes
- **Breaking Changes**: Yes
- **Config Migration Required**: No

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
- [ ] **Read "Breaking Changes" section below** — you will need to update project handlers

## Changes in This Release

### New Features

- **Handler Self-Documentation (`get_claude_md()`)**: Every handler now explicitly declares what guidance it publishes into the project `CLAUDE.md`. This makes handler documentation mandatory and opt-out (`return None`) rather than opt-in.

- **`ClaudeMdInjector`**: New core component that collects `get_claude_md()` output from all active handlers on daemon restart and writes a `<hooksdaemon>` section into the project `CLAUDE.md`. The section is auto-replaced on each restart.

- **Step 7.6 CLAUDE.md Guidance Audit**: Release process now includes a mandatory sub-agent analysis step verifying all impactful handlers have accurate `get_claude_md()` content.

### Modified Handlers

- **All 77+ built-in handlers**: Updated with explicit `get_claude_md()` implementations (either `return None` or real guidance strings). No user action needed for built-in handlers.

### Hook Script Changes

- None. Hook forwarder scripts are unchanged.

### Configuration Changes

- None. No config file changes required.

### Dependency Changes

- None.

## Breaking Changes

### `get_claude_md()` is now an abstract method on `Handler`

**What broke**: Any project-level handler (in `.claude/project-handlers/`) that was written before v2.30.0 will fail to load because it does not implement the new `get_claude_md()` abstract method. Python treats the class as abstract, and the daemon's loader reports "No Handler subclass found in project handler file".

**Who is affected**: Users with custom project-level handlers in `.claude/project-handlers/`. Users with no project handlers are not affected.

**Why**: Making `get_claude_md()` abstract ensures every handler explicitly declares whether it has guidance to publish. This prevents silent omissions where a handler blocks commands but agents have no way to know what is blocked or why.

**Migration Steps**:

1. **Detect affected handlers**:
   ```bash
   cd .claude/hooks-daemon
   untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli validate-project-handlers
   ```
   Any handler that fails with a message mentioning `get_claude_md` needs updating.

2. **Add the method to each affected handler**:
   ```python
   class MyHandler(Handler):
       # ... existing code ...

       def get_claude_md(self) -> str | None:
           return None
   ```

   If your handler blocks or advises on specific patterns, consider returning a guidance string instead of `None`:
   ```python
   def get_claude_md(self) -> str | None:
       return (
           "## my_handler — description of what it does\n\n"
           "**Blocked**: patterns that are blocked\n\n"
           "**Allowed**: patterns that are allowed\n"
       )
   ```

3. **Verify the fix**:
   ```bash
   cd .claude/hooks-daemon
   untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli validate-project-handlers
   # Expected: all handlers load successfully, exit code 0

   untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
   # Expected: daemon starts without errors
   ```

**Rollback**: If you cannot update handlers immediately, downgrade to v2.29.x:
```bash
cd .claude/hooks-daemon
git checkout v2.29.2
untracked/venv/bin/pip install -e .
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

## Step-by-Step Upgrade Instructions

### 1. Update Daemon Code

```bash
cd .claude/hooks-daemon
git fetch origin
git checkout v2.30.0
```

### 2. Update Dependencies

```bash
cd .claude/hooks-daemon
untracked/venv/bin/pip install -e .
```

### 3. Update Project Handlers (REQUIRED if you have any)

For each handler file in `.claude/project-handlers/`:

Add the `get_claude_md()` method:

```python
def get_claude_md(self) -> str | None:
    return None
```

### 4. Restart Daemon

```bash
cd .claude/hooks-daemon
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

## Verification Steps

### 1. Verify Version Updated

```bash
cd .claude/hooks-daemon
cat src/claude_code_hooks_daemon/version.py
```

**Expected**:
```python
__version__ = "2.30.0"
```

### 2. Validate Project Handlers

```bash
cd .claude/hooks-daemon
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli validate-project-handlers
echo $?
```

**Expected**: exit code 0, all handlers load successfully.

### 3. Verify Daemon Starts

```bash
cd .claude/hooks-daemon
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli status
```

**Expected**: `Daemon: RUNNING`

### 4. Run Automated Verification

```bash
bash CLAUDE/UPGRADES/v2/v2.29-to-v2.30/verification.sh
```

## Rollback Instructions

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

```bash
cd .claude/hooks-daemon
git checkout v2.29.2
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

## Known Issues

- **v2.30.0 shipped without this upgrade guide**: The breaking change was released without migration documentation. This guide was added retroactively in the v2.30.1 hotfix.
- **Error message before hotfix**: Without the v2.30.1 hotfix, the error message is the unhelpful "No Handler subclass found" instead of naming the missing `get_claude_md()` method. Apply the hotfix for better diagnostics.

## Support

If you encounter issues during upgrade:

1. **Validate handlers**:
   ```bash
   untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli validate-project-handlers --verbose
   ```

2. **Check daemon logs**:
   ```bash
   untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli logs
   ```

3. **Try rollback** (see "Rollback Instructions" above)

4. **Report issue**:
   - GitHub: https://github.com/anthropics/claude-code-hooks-daemon/issues
   - Include: version info, error output, daemon logs

## References

- [Upgrade system documentation](../README.md)
- [Handler development guide](../../HANDLER_DEVELOPMENT.md)
- [Release notes v2.30.0](../../../RELEASES/v2.30.0.md)
- [Full changelog](../../../CHANGELOG.md)
