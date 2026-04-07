# Upgrade Guide: v2.32 → v3.0

## What Changed

v3.0.0 removes the `command_redirection` feature entirely. This was an internal mechanism on the `pipe_blocker`, `npm_command`, and `gh_issue_comments` handlers that, when enabled, stripped the blocked portion of a command, executed the remainder, and saved the output to a file. The feature caused unpredictable behaviour, could not handle output redirection, and added significant complexity for marginal benefit. It has been disabled by default since v2.31.0 and is now removed entirely.

**Three things were removed:**

1. The `command_redirection` config option on `pipe_blocker`, `npm_command`, and `gh_issue_comments`
2. The shared `core/command_redirection.py` Python module (and its public API: `execute_and_save`, `launch_and_save`, `format_redirection_context`)
3. The `cleanup_stale_command_redirection_files()` function in `daemon/paths.py`

## Version Compatibility

- **Source Version**: v2.32.x (minimum version you can upgrade from)
- **Target Version**: v3.0.0 (version after upgrade)
- **Supports Rollback**: Yes
- **Breaking Changes**: Yes
- **Config Migration Required**: Yes (only if you have `command_redirection` set in your config)

## Pre-Upgrade Checklist

Before starting the upgrade:

- [ ] Backup `.claude/hooks-daemon.yaml`
  ```bash
  cp .claude/hooks-daemon.yaml .claude/hooks-daemon.yaml.backup
  ```
- [ ] Check whether your config uses `command_redirection`
  ```bash
  grep -n "command_redirection" .claude/hooks-daemon.yaml || echo "Not used - clean upgrade"
  ```
- [ ] Check whether any project-level handlers import the deleted module
  ```bash
  grep -rn "command_redirection" .claude/project-handlers/ 2>/dev/null || echo "No project handler usage"
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

## Changes in This Release

### Removed Features

- **`command_redirection` option**: Removed from all three handlers (`pipe_blocker`, `npm_command`, `gh_issue_comments`).
- **`core/command_redirection.py` module**: Deleted entirely. `execute_and_save`, `launch_and_save`, and `format_redirection_context` are no longer importable.
- **`cleanup_stale_command_redirection_files()`**: Removed from `daemon/paths.py`.

### Modified Handlers

- **`pipe_blocker`**: Now simply denies blocked piped commands with an educational message. No execution.
- **`npm_command`**: Now simply denies non-`llm:` npm commands with an educational message. No execution.
- **`gh_issue_comments`**: Now simply denies `gh issue view` without `--comments` with an educational message. No execution.

### Hook Script Changes

- None. Hook forwarder scripts are unchanged.

### Configuration Changes

- The `command_redirection` config key is no longer recognised. Schema validation will reject any config that uses it. **You must remove any `command_redirection:` lines from `.claude/hooks-daemon.yaml` before upgrading.**

### Dependency Changes

- None.

## Breaking Changes

### 1. `command_redirection` config option removed

**What broke**: Any project that has `options: command_redirection: true` (or `false`) under `pipe_blocker`, `npm_command`, or `gh_issue_comments` in `.claude/hooks-daemon.yaml` will fail config schema validation on daemon startup.

**Who is affected**: Projects that explicitly set `command_redirection` in their config. Since v2.31.0 the default has been `false`, so projects using defaults are not affected at the config level — but the option key itself is still rejected by schema validation if present.

**Why**: The feature was unreliable. Stripping a "bad part" out of a Bash command and executing the remainder is fundamentally fragile because Bash commands are not trivially decomposable. Output redirection (`>`, `2>&1`, `tee`), shell built-ins, and command substitution all caused incorrect behaviour. Removing the option entirely is cleaner than carrying a documented-broken setting forward.

**Migration Steps**:

1. **Detect affected config**:
   ```bash
   grep -n "command_redirection" .claude/hooks-daemon.yaml
   ```
   If this returns no output, you have nothing to migrate.

2. **Remove the lines from your config**. Open `.claude/hooks-daemon.yaml` and remove any block matching:
   ```yaml
       pipe_blocker:
         enabled: true
         priority: 17
         options:
           command_redirection: true   # <- remove this line
   ```
   If `options:` is now empty, remove the empty `options:` line as well:
   ```yaml
       pipe_blocker:
         enabled: true
         priority: 17
   ```
   Repeat for `npm_command` and `gh_issue_comments`.

3. **Verify the fix**:
   ```bash
   grep -n "command_redirection" .claude/hooks-daemon.yaml || echo "Clean"
   ```
   Should print `Clean`.

### 2. `core/command_redirection.py` module deleted

**What broke**: Any Python code that imports from `claude_code_hooks_daemon.core.command_redirection` will raise `ImportError` on daemon startup.

**Who is affected**: Project-level handlers (in `.claude/project-handlers/`) and any third-party tooling that depended on `execute_and_save`, `launch_and_save`, or `format_redirection_context`.

**Why**: The module existed solely to support the `command_redirection` feature on the three built-in handlers. With that feature removed, the module has no remaining callers in the daemon. Keeping it as a public API would commit us to supporting an interface we have judged to be fundamentally unreliable.

**Migration Steps**:

1. **Detect affected project handlers**:
   ```bash
   grep -rn "command_redirection" .claude/project-handlers/ 2>/dev/null
   ```

2. **There is no drop-in replacement.** If your project handler depended on `execute_and_save` or `launch_and_save`, you have two options:
   - **Drop the execution behaviour** and just deny with an educational message (recommended — this is what the built-in handlers now do).
   - **Inline the subprocess logic** in your handler if you genuinely need it. The original implementation was a thin wrapper around `subprocess.run` / `subprocess.Popen` writing output to a file under `/tmp/hooks-daemon-cmd/`.

3. **Verify the fix**:
   ```bash
   cd .claude/hooks-daemon
   untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli validate-project-handlers
   echo $?
   ```
   Expected: exit code 0.

### 3. `cleanup_stale_command_redirection_files()` removed

**What broke**: Any code that imports `cleanup_stale_command_redirection_files` from `claude_code_hooks_daemon.daemon.paths` will raise `ImportError`.

**Who is affected**: Custom tooling or scripts that explicitly called this cleanup function. The daemon's own startup code has already been updated.

**Why**: With the `command_redirection` feature gone, there are no command redirection files left to clean up.

**Migration Steps**: Remove the import. There is no replacement — `cleanup_stale_daemon_files()` continues to handle cleanup of daemon runtime files (sockets, PID files, logs) and is unchanged.

**Rollback**: If you cannot complete migration immediately, downgrade to v2.32.0:
```bash
cd .claude/hooks-daemon
git checkout v2.32.0
untracked/venv/bin/pip install -e .
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

## Step-by-Step Upgrade Instructions

### 1. Migrate your config (if needed)

```bash
grep -n "command_redirection" .claude/hooks-daemon.yaml
```

If this prints anything, edit `.claude/hooks-daemon.yaml` and remove the matching lines as described in "Breaking Changes" Section 1 above.

### 2. Migrate project handlers (if needed)

```bash
grep -rn "command_redirection" .claude/project-handlers/ 2>/dev/null
```

If this prints anything, update those handlers as described in "Breaking Changes" Section 2 above.

### 3. Update Daemon Code

```bash
cd .claude/hooks-daemon
git fetch --tags
git checkout v3.0.0
```

### 4. Update Dependencies

```bash
cd .claude/hooks-daemon
untracked/venv/bin/pip install -e .
```

### 5. Restart Daemon

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
__version__ = "3.0.0"
```

### 2. Verify Config is Clean

```bash
grep -n "command_redirection" .claude/hooks-daemon.yaml || echo "Clean"
```

**Expected**: `Clean`

### 3. Verify Daemon Starts

```bash
cd .claude/hooks-daemon
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli status
```

**Expected**: `Daemon: RUNNING`

### 4. Verify Project Handlers Load

```bash
cd .claude/hooks-daemon
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli validate-project-handlers
echo $?
```

**Expected**: exit code 0, all handlers load.

### 5. Run Automated Verification

```bash
bash CLAUDE/UPGRADES/v3/v2.32-to-v3.0/verification.sh
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
git checkout v2.32.0
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

None.

## Support

If you encounter issues during upgrade:

1. **Check daemon logs**:
   ```bash
   cd .claude/hooks-daemon
   untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli logs
   ```

2. **Validate project handlers**:
   ```bash
   untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli validate-project-handlers --verbose
   ```

3. **Try rollback** (see "Rollback Instructions" above)

4. **Report issue**:
   - GitHub: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues
   - Include: version info, error output, daemon logs, the offending config snippet

## References

- [Upgrade system documentation](../../README.md)
- [Handler development guide](../../../HANDLER_DEVELOPMENT.md)
- [Release notes v3.0.0](../../../../RELEASES/v3.0.0.md)
- [Full changelog](../../../../CHANGELOG.md)
