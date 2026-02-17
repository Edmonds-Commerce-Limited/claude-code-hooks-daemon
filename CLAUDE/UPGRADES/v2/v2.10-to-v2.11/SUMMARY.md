# v2.10 → v2.11 Upgrade Summary

## What Changed

**Removed Handlers**:
1. `validate_sitemap` (PostToolUse) - Project-specific sitemap validation reminder
2. `remind_validator` (SubagentStop) - Project-specific validator agent reminder

**Why Removed**: These were "hangover code" from early development. They implemented workflow patterns specific to one project and don't belong in the core daemon. Project-specific handlers should live in `.claude/project-handlers/`.

## Impact

**Low** - These handlers were project-specific and unlikely to be used by other projects.

**Affected Users**: Only projects that explicitly configured these handlers in `.claude/hooks-daemon.yaml`.

**Daemon Behaviour**: Continues to work normally. Obsolete handler references are silently ignored (no errors).

## Files Created

```
CLAUDE/UPGRADES/v2/v2.10-to-v2.11/
├── README.md                  # Overview and quick start
├── v2.10-to-v2.11.md         # Complete upgrade guide (595 lines)
├── config-before.yaml         # Example config before upgrade
├── config-after.yaml          # Example config after upgrade
├── migration-script.sh        # Automated config migration (executable)
├── verification.sh            # Upgrade verification (executable)
└── SUMMARY.md                 # This file
```

## Quick Migration

### For Users Who Don't Use These Handlers

**No action required** - Your config is already compatible.

### For Users Who Use These Handlers

**Option 1 - Automated** (recommended):
```bash
cd /path/to/your/project
bash .claude/hooks-daemon/CLAUDE/UPGRADES/v2/v2.10-to-v2.11/migration-script.sh
```

**Option 2 - Manual**:
1. Open `.claude/hooks-daemon.yaml`
2. Remove or comment out `validate_sitemap` and `remind_validator` entries
3. If you need the functionality, recreate as project handlers (see guide)

## Migration to Project Handlers

If you relied on these handlers, the upgrade guide includes:
- Complete Python code examples for recreating both handlers
- Step-by-step setup instructions
- Testing procedures
- Documentation references

**Key Files to Read**:
- Migration guide: `v2.10-to-v2.11.md` (section "Migration to Project Handlers")
- Project handlers docs: `.claude/hooks-daemon/CLAUDE/PROJECT_HANDLERS.md`

## Verification

After upgrading to v2.11.0:

```bash
cd /path/to/your/project
bash .claude/hooks-daemon/CLAUDE/UPGRADES/v2/v2.10-to-v2.11/verification.sh
```

Expected output:
- ✅ Version: v2.11.0
- ✅ Config: No obsolete handlers
- ✅ Daemon: Restarts successfully
- ✅ Handlers: Load without errors

## Documentation Quality

### Main Upgrade Guide (v2.10-to-v2.11.md)

**Structure** (follows v2.0-to-v2.1 template):
- Summary of changes
- Version compatibility matrix
- Pre-upgrade checklist
- Changes overview (what was removed and why)
- Step-by-step upgrade instructions
- Breaking changes explanation
- Migration to project handlers (complete code examples)
- Verification steps
- Rollback instructions
- Known issues
- Configuration examples
- Support information

**Length**: 595 lines

**Completeness**:
- ✅ Clear explanation of why handlers were removed
- ✅ Migration path for both removed handlers
- ✅ Complete Python code examples for recreation
- ✅ Automated migration script
- ✅ Verification procedures
- ✅ Rollback instructions

### Supporting Files

**config-before.yaml** (67 lines):
- Shows typical v2.10 config with removed handlers
- Annotated to identify what gets removed

**config-after.yaml** (64 lines):
- Shows clean v2.11 config
- Includes comments showing where handlers were removed
- References project handlers documentation

**migration-script.sh** (257 lines):
- Detects if obsolete handlers are in config
- Creates backup automatically
- Two migration modes: comment out or delete
- Uses Python (not sed) to avoid blocker
- Clear colored output
- Provides next steps

**verification.sh** (113 lines):
- 5 verification checks
- Clear pass/fail indicators
- Helpful error messages
- Exit codes for automation

**README.md** (151 lines):
- Quick start guide
- File descriptions
- Impact assessment
- Support information

## Commit Message

```
Add v2.10 → v2.11 upgrade guide for handler removal

Breaking changes in v2.11.0:
- Removed validate_sitemap handler (PostToolUse)
- Removed remind_validator handler (SubagentStop)

These were project-specific "hangover code" and don't belong in core daemon.

Created complete upgrade package:
- Main guide with migration paths (595 lines)
- Config examples (before/after)
- Automated migration script
- Verification script
- README and summary

Users who relied on these handlers can recreate them as project-level
handlers using the provided code examples and documentation.

Low impact - handlers were project-specific and unlikely to be used elsewhere.
```

## Next Steps

1. Review all files for accuracy
2. Test migration script with real configs (if available)
3. Commit upgrade guide
4. Reference in CHANGELOG.md (already exists for v2.11.0)
5. Reference in v2.11.0 release notes

## Related Documentation

- Breaking changes: `/workspace/CHANGELOG.md` (lines 200-204)
- Removal commit: 990bb1f
- Project handlers: `/workspace/CLAUDE/PROJECT_HANDLERS.md`
- Handler development: `/workspace/CLAUDE/HANDLER_DEVELOPMENT.md`
