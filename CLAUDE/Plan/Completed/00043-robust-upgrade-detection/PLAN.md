# Plan 00043: Robust Upgrade Detection & Repair for Broken Installations

**Status**: Complete (2026-02-10)

## Context

Users who installed from older versions (pre-v2.7.0) may not have `.claude/hooks-daemon.yaml` at their project root. The upgrade script (`upgrade.sh`) and `detect_project_root()` use that file as the **sole signal** for finding the project root. This means upgrades fail immediately for these users with:

```
ERR Could not find project root (no .claude/hooks-daemon.yaml in any parent directory)
```

The daemon repo (`.claude/hooks-daemon/.git`) IS present -- the installation is just missing the config file.

## Approach

Add fallback detection signals and auto-repair of missing config during upgrade.

## Changes

### 1. `scripts/install/project_detection.sh` - Multi-signal detection

Update `detect_project_root()` to check multiple signals in priority order:
1. `.claude/hooks-daemon.yaml` (current - ideal state)
2. `.claude/hooks-daemon/.git` (daemon repo exists but config missing)

This is the shared library function used by both Layer 1 and Layer 2.

Also update `detect_and_validate_project()` to set a new `NEEDS_CONFIG_REPAIR` flag when detection succeeded via fallback signal (no config file).

### 2. `scripts/upgrade.sh` (Layer 1) - Use multi-signal detection

Replace the inline detection loop (lines 47-55) with the same multi-signal logic:
1. First check for `.claude/hooks-daemon.yaml` (fast path)
2. Fallback: check for `.claude/hooks-daemon/.git` (broken install)

When detected via fallback, log a warning: `"Config file missing - will be repaired during upgrade"`

### 3. `scripts/upgrade_version.sh` (Layer 2) - Auto-repair missing config

After Step 6 (checkout target version), the example config at `$DAEMON_DIR/.claude/hooks-daemon.yaml.example` is available. Step 10 already handles this case:

```bash
elif [ ! -f "$TARGET_CONFIG" ] && [ -f "$NEW_DEFAULT_CONFIG" ]; then
    cp "$NEW_DEFAULT_CONFIG" "$TARGET_CONFIG"
    print_success "Installed new default config"
```

So Layer 2 already repairs missing config during the merge step. No change needed here -- the fix is entirely in detection (getting past the Layer 1 gate).

### 4. Tests

Add unit tests for the enhanced `detect_project_root()` to verify both detection paths.

## Files to Modify

1. **`scripts/install/project_detection.sh`** - `detect_project_root()` (lines 31-44)
2. **`scripts/upgrade.sh`** - Project root detection block (lines 45-57)
3. **`tests/`** - New/updated tests for detection logic

## Verification

1. Simulate broken install: create a temp dir with `.claude/hooks-daemon/.git` but NO `.claude/hooks-daemon.yaml`
2. Run `detect_project_root()` from that dir -- should succeed
3. Run `upgrade.sh` logic -- should detect project root and warn about missing config
4. Full QA: `./scripts/qa/run_all.sh`
5. Daemon restart: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
