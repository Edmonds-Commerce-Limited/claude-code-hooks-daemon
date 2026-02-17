# v2.11 → v2.12 Upgrade Documentation

This directory contains complete upgrade documentation for migrating from v2.11.0 to v2.12.0.

## Breaking Change Summary

**Handler Rename**: `validate_eslint_on_write` → `lint_on_edit`

**Enhancement**: Extended from ESLint-only to 9 languages with Strategy Pattern architecture.

## Files in This Directory

### Documentation

- **v2.11-to-v2.12.md** - Complete upgrade guide
  - Overview of breaking changes
  - Step-by-step migration instructions
  - Configuration examples
  - New features and capabilities
  - Rollback instructions
  - Troubleshooting

### Configuration Examples

- **config-before.yaml** - Example v2.11 config with old handler name
- **config-after.yaml** - Example v2.12 config with new handler name

### Migration Tools

- **migration-script.sh** - Automated migration script
  - Detects old handler name in config
  - Creates timestamped backup
  - Performs safe string replacement using Python
  - Validates YAML syntax after change
  - Shows before/after diff

- **verification.sh** - Post-upgrade verification script
  - Checks daemon version (2.12.0)
  - Validates config file syntax
  - Confirms old handler name removed
  - Verifies new handler name present
  - Tests handler import

## Quick Start

### 1. Read the Guide

```bash
cat CLAUDE/UPGRADES/v2/v2.11-to-v2.12/v2.11-to-v2.12.md
```

### 2. Run Migration Script

```bash
bash CLAUDE/UPGRADES/v2/v2.11-to-v2.12/migration-script.sh
```

### 3. Verify Migration

```bash
bash CLAUDE/UPGRADES/v2/v2.11-to-v2.12/verification.sh
```

### 4. Restart Daemon

```bash
cd .claude/hooks-daemon
untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart
```

## What Changed

### Handler Rename

- **Old**: `validate_eslint_on_write`
- **New**: `lint_on_edit`

### New Capabilities

The renamed handler now supports **9 programming languages**:

1. **Python** - `py_compile` + `ruff`
2. **JavaScript/TypeScript** - `eslint` (preserved from v2.11)
3. **Ruby** - `ruby -c` + `rubocop`
4. **PHP** - `php -l` + `phpcs`
5. **Go** - `go vet` + `golangci-lint`
6. **Rust** - `rustc` + `clippy`
7. **Java** - `checkstyle`
8. **C/C++** - `clang-tidy`
9. **Shell** - `bash -n` + `shellcheck`

### Architecture

- **Strategy Pattern** - Clean, extensible design
- **Protocol interface** - Language-specific strategies
- **Registry pattern** - Config-filtered loading
- **Independent testing** - Each strategy TDD-able
- **Command overrides** - Customize per language
- **Graceful degradation** - Continues if linter not installed

## Migration Impact

- **Risk**: Low (simple rename, functionality preserved)
- **Downtime**: None (restart daemon after config change)
- **Rollback**: Supported (restore backup config + git checkout v2.11.0)
- **Time**: 5-10 minutes

## Support

If you encounter issues:

1. Check the full guide: `v2.11-to-v2.12.md`
2. Run verification: `bash verification.sh`
3. Check daemon logs: `cat .claude/hooks-daemon/untracked/daemon.log`
4. Report issues: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues

## References

- [Main upgrade guide](v2.11-to-v2.12.md)
- [Plan 00054 - Lint-on-Edit Strategy Pattern](../../../Plan/Completed/00054-lint-on-edit-strategy-pattern/PLAN.md)
- [CHANGELOG.md](../../../../CHANGELOG.md) - v2.12.0 entry
- [Upgrade system overview](../../README.md)
