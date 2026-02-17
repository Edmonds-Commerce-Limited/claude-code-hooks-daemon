# Upgrade Hooks Daemon

Upgrade your Claude Code Hooks Daemon to a new version with automatic safety checks and rollback.

## Quick Upgrade

```bash
/hooks-daemon upgrade
```

This auto-detects the latest version and upgrades safely.

## Upgrade to Specific Version

```bash
/hooks-daemon upgrade 2.14.0
```

Specify an exact version number to upgrade to.

## Force Reinstall Current Version

```bash
/hooks-daemon upgrade --force
```

Reinstall the current version (useful for repairing broken installations).

## What Happens During Upgrade

The upgrade process includes multiple safety checks:

1. **Validates current daemon** - Ensures daemon can restart before upgrading
2. **Backs up configuration** - Saves current config to `.backup` file
3. **Downloads new version** - Fetches the specified or latest version
4. **Verifies installation** - Ensures new daemon starts successfully
5. **Tests functionality** - Runs basic smoke tests
6. **Rolls back on failure** - Automatically reverts if any step fails

## Upgrade Safety Features

- **Automatic backup** - Config files backed up before changes
- **Rollback protection** - Failed upgrades automatically revert
- **Version validation** - Checks version exists before downloading
- **Daemon verification** - New version must start successfully
- **Skill refresh** - Updates skill files to match daemon version

## After Upgrade

The upgrade process will:
- Restart the daemon with the new version
- Refresh skill files in `.claude/skills/hooks-daemon/`
- Display changelog highlights for the new version

## If Upgrade Fails

If the upgrade fails, the system automatically:
1. Stops the new daemon
2. Restores backed-up configuration
3. Restarts the previous daemon version
4. Reports the failure reason

See [references/troubleshooting.md](references/troubleshooting.md#upgrade-failures) for common upgrade issues.

## Manual Upgrade

If you need to upgrade manually:

```bash
# 1. Stop daemon
$PYTHON -m claude_code_hooks_daemon.daemon.cli stop

# 2. Download upgrade script
curl -fsSL https://raw.githubusercontent.com/your-org/hooks-daemon/main/scripts/upgrade.sh | bash

# 3. Verify new version
$PYTHON -m claude_code_hooks_daemon.daemon.cli status
```

## Version History

To see what's new in each version, check:
- `CHANGELOG.md` in the daemon repository
- `RELEASES/` directory for detailed release notes
- GitHub releases page
