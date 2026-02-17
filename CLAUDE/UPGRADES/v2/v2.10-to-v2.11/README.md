# v2.10 → v2.11 Upgrade Package

This directory contains all materials needed to upgrade from v2.10.x to v2.11.0.

## Breaking Changes

v2.11.0 removes two project-specific handlers:
- `validate_sitemap` (PostToolUse)
- `remind_validator` (SubagentStop)

These were "hangover code" from early development and should not have been in the core daemon.

## Files in This Directory

### Main Documentation
- **v2.10-to-v2.11.md** - Complete upgrade guide with step-by-step instructions

### Configuration Examples
- **config-before.yaml** - Example v2.10 config with removed handlers
- **config-after.yaml** - Example v2.11 config without removed handlers

### Automation Scripts
- **migration-script.sh** - Automated config migration (comments out or removes obsolete handlers)
- **verification.sh** - Verifies upgrade was successful

### This File
- **README.md** - This overview

## Quick Start

### 1. Read the Upgrade Guide

```bash
cat CLAUDE/UPGRADES/v2/v2.10-to-v2.11/v2.10-to-v2.11.md
```

### 2. Run Migration Script (if needed)

```bash
cd /path/to/your/project
bash .claude/hooks-daemon/CLAUDE/UPGRADES/v2/v2.10-to-v2.11/migration-script.sh
```

This will:
- Check if your config references removed handlers
- Create backup of current config
- Comment out or remove obsolete handlers
- Provide next steps

### 3. Verify Upgrade

```bash
cd /path/to/your/project
bash .claude/hooks-daemon/CLAUDE/UPGRADES/v2/v2.10-to-v2.11/verification.sh
```

This will:
- Check version is v2.11.0
- Validate config has no active obsolete handlers
- Test daemon restart
- Check for handler errors in logs
- Confirm daemon status

## Who Should Use This?

### You NEED to migrate if:
- Your `.claude/hooks-daemon.yaml` references `validate_sitemap`
- Your `.claude/hooks-daemon.yaml` references `remind_validator`
- You explicitly enabled these handlers

### You DON'T need to migrate if:
- You never configured these handlers
- You use only default handler configuration
- You're upgrading from a clean v2.10 install

## Impact Assessment

**Low Impact** - These handlers were project-specific and unlikely to be used by other projects.

**What happens if you don't migrate?**
- Daemon continues to work normally
- Obsolete handler references are silently ignored
- No errors or warnings
- Clean config is just better housekeeping

## Migration Path for Removed Functionality

If you relied on these handlers, you can recreate them as project-level handlers.

See the upgrade guide for:
- Complete code examples for recreating handlers
- Instructions on project handler setup
- Testing procedures

**Key benefit**: Project handlers are version-controlled with your project, not the daemon.

## Support

If you encounter issues:

1. **Check verification script output** - Run `verification.sh` for diagnostics
2. **Review daemon logs** - Check `.claude/hooks-daemon/untracked/daemon.log`
3. **Consult upgrade guide** - See `v2.10-to-v2.11.md` for detailed instructions
4. **Report issues** - GitHub: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues

## Quick Reference

### Manual Config Changes

**Remove these entries** (if present):

```yaml
handlers:
  post_tool_use:
    validate_sitemap:     # Remove this entire section
      enabled: true
      priority: 50

  subagent_stop:
    remind_validator:     # Remove this entire section
      enabled: true
      priority: 50
```

### Rollback

If you need to revert to v2.10.1:

```bash
cd .claude/hooks-daemon
git checkout v2.10.1
untracked/venv/bin/pip install -e .
cp .claude/hooks-daemon.yaml.backup .claude/hooks-daemon.yaml  # if backup exists
```

See full rollback instructions in the upgrade guide.

## Version Compatibility

- **Source**: v2.10.0, v2.10.1
- **Target**: v2.11.0
- **Supports Rollback**: Yes
- **Breaking Changes**: Yes (handler removal)
- **Config Migration**: Recommended but optional

## Related Documentation

- [Main upgrade guide](v2.10-to-v2.11.md)
- [Project handlers documentation](../../../PROJECT_HANDLERS.md)
- [Handler development guide](../../../HANDLER_DEVELOPMENT.md)
- [Upgrade system overview](../../README.md)
