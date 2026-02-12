# Plan 00056: Fix DaemonLocationGuardHandler Whitelisting

## Context

**Problem**: The DaemonLocationGuardHandler was implemented with a completely made-up "official upgrade command" pattern that doesn't exist:
```python
OFFICIAL_UPGRADE_PATTERN = re.compile(
    r"cd\s+\.claude/hooks-daemon\s+&&\s+git\s+pull\s+&&\s+cd\s+\.\./\.\.\s+&&.*upgrade"
)
```

This is wrong because:
1. The `.claude/hooks-daemon` directory is NOT upgraded by `cd`-ing into it and running `git pull`
2. The **actual recommended upgrade method** (from LLM-UPDATE.md) is:
   ```bash
   curl -fsSL https://raw.githubusercontent.com/.../upgrade.sh -o /tmp/upgrade.sh
   bash /tmp/upgrade.sh --project-root /path/to/project
   rm /tmp/upgrade.sh
   ```
3. The upgrade script handles ALL git operations internally - users never `cd` into hooks-daemon for upgrades

**Manual upgrade exists** (LLM-UPDATE.md Step 2), which involves:
```bash
cd .claude/hooks-daemon
git fetch --tags
git checkout "$LATEST_TAG"
cd ../..
```

But this is:
- A multi-step manual process, not a single command to whitelist
- Not recommended (script method is preferred)
- Used only when the script method fails

## Solution

**Remove the whitelisting pattern entirely** and just block ALL `cd .claude/hooks-daemon` attempts.

**Rationale**:
1. **Recommended upgrade method** uses `/tmp/upgrade.sh` - never touches hooks-daemon directly
2. **Manual upgrade** is a last-resort fallback for when the script fails
3. If agents need manual upgrade access, they can:
   - Temporarily disable the handler in config
   - Ask the user for permission to proceed
4. **Safety over convenience** - blocking prevents confusion, which is the whole point

## Changes Required

### File: `src/claude_code_hooks_daemon/handlers/pre_tool_use/daemon_location_guard.py`

**Remove**:
- `OFFICIAL_UPGRADE_PATTERN` class attribute (lines 18-20)
- Whitelisting logic in `matches()` (lines 51-53)

**Update**:
- Handler docstring to remove mention of whitelisting
- `handle()` guidance to explain upgrade process correctly

### File: `tests/unit/handlers/pre_tool_use/test_daemon_location_guard.py`

**Remove**:
- `test_not_matches_official_upgrade_command` test (lines 81-88)

**Update test count**: 15 tests → 14 tests

### File: `src/claude_code_hooks_daemon/handlers/pre_tool_use/daemon_location_guard.py` (acceptance tests)

**Update**:
- Remove second AcceptanceTest that tested whitelisting

## Implementation Steps

1. **Read current handler** to confirm exact line numbers
2. **Remove OFFICIAL_UPGRADE_PATTERN** constant
3. **Remove whitelisting check** from `matches()`
4. **Update docstrings** to reflect no whitelisting
5. **Update guidance** with correct upgrade instructions
6. **Update acceptance tests** (remove whitelist test)
7. **Remove unit test** for whitelisting
8. **Run full QA** to verify all tests pass
9. **Restart daemon** to verify it loads

## Correct Upgrade Guidance (for handler)

The `handle()` method should provide this guidance:

```
📦 CORRECT UPGRADE PROCESS:

  # Download latest upgrade script
  curl -fsSL https://raw.githubusercontent.com/.../upgrade.sh -o /tmp/upgrade.sh

  # Review it
  less /tmp/upgrade.sh

  # Run it (script handles all git operations)
  bash /tmp/upgrade.sh --project-root /path/to/your/project

  # Clean up
  rm /tmp/upgrade.sh

💡 The upgrade script handles all git operations internally.
   You never need to cd into .claude/hooks-daemon for upgrades.

⚠️  Manual upgrade (last resort only):
    If the script fails, you can temporarily disable this handler:
    .claude/hooks-daemon.yaml → daemon_location_guard.enabled: false
```

## Verification

After changes:
1. ✅ All unit tests pass (14 tests, down from 15)
2. ✅ Full QA suite passes
3. ✅ Daemon restarts successfully
4. ✅ Handler blocks `cd .claude/hooks-daemon` (no exceptions)
5. ✅ Guidance provides correct upgrade instructions

## Success Criteria

- [x] OFFICIAL_UPGRADE_PATTERN removed
- [x] Whitelisting logic removed from matches()
- [x] Docstrings updated (no mention of whitelisting)
- [x] Guidance updated with correct upgrade instructions
- [x] Unit test removed (test_not_matches_official_upgrade_command)
- [x] Acceptance test updated (remove whitelist test)
- [x] All QA checks pass
- [x] Daemon loads successfully

## Completion Summary

**Status**: Complete (2026-02-12)

All success criteria met:
- Removed fake OFFICIAL_UPGRADE_PATTERN constant
- Removed whitelisting logic from matches() method
- Updated docstrings and guidance with correct upgrade process
- Test count: 14 tests (down from 15)
- Acceptance tests: 1 test (down from 2)
- All QA checks pass (7/7)
- Daemon restarts and loads successfully

## Files to Modify

1. `src/claude_code_hooks_daemon/handlers/pre_tool_use/daemon_location_guard.py`
2. `tests/unit/handlers/pre_tool_use/test_daemon_location_guard.py`
