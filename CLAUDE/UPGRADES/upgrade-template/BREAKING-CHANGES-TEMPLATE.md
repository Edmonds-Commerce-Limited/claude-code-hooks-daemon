# Breaking Changes Template for Release Notes

This template defines the format for documenting breaking changes in release notes (`RELEASES/vX.Y.Z.md`).

## Purpose

When a release includes breaking changes (handler removals, renames, API changes, config changes), the release notes MUST include a prominent "⚠️ BREAKING CHANGES" section immediately after the "Highlights" section.

## Format

```markdown
## ⚠️ BREAKING CHANGES

### Handler Removals

- **`handler_id`** - Removed in vX.Y.Z
  - **Why**: [Explanation of why this handler was removed]
  - **Migration**: [How users should migrate - remove from config, move to project handlers, use alternative]
  - **Guide**: [Link to upgrade guide in CLAUDE/UPGRADES/]

### Handler Renames

- **`new_handler_id`** (renamed from `old_handler_id`) - Renamed in vX.Y.Z
  - **Why**: [Explanation of why this handler was renamed - often feature expansion]
  - **Migration**: Update config to use new name `new_handler_id`
  - **Guide**: [Link to upgrade guide in CLAUDE/UPGRADES/]

### Configuration Changes

- **`config_field`** - [Removed/Renamed/Changed] in vX.Y.Z
  - **Why**: [Explanation of change]
  - **Migration**: [How to update configuration]
  - **Guide**: [Link to upgrade guide in CLAUDE/UPGRADES/]

### API Changes

- **`module.function`** - Signature changed in vX.Y.Z
  - **What changed**: [Description of API change]
  - **Why**: [Rationale for change]
  - **Migration**: [Code examples showing old → new usage]
  - **Guide**: [Link to upgrade guide in CLAUDE/UPGRADES/]
```

## Placement

The "⚠️ BREAKING CHANGES" section MUST appear:
1. **After** the "## Summary" and "## Highlights" sections
2. **Before** the "## Changes" section (with full changelog)

This ensures users see breaking changes immediately when reviewing release notes.

## Example 1: Handler Removal (v2.11.0)

```markdown
## ⚠️ BREAKING CHANGES

### Handler Removals

- **`validate_sitemap`** (PostToolUse) - Removed in v2.11.0
  - **Why**: Project-specific validation code that doesn't belong in core daemon
  - **Migration**: Move to project-level handlers if needed (`.claude/project-handlers/`)
  - **Guide**: [v2.10-to-v2.11 Upgrade Guide](../CLAUDE/UPGRADES/v2/v2.10-to-v2.11/v2.10-to-v2.11.md)

- **`remind_validator`** (SubagentStop) - Removed in v2.11.0
  - **Why**: Project-specific reminder that doesn't belong in core daemon
  - **Migration**: Move to project-level handlers if needed
  - **Guide**: [v2.10-to-v2.11 Upgrade Guide](../CLAUDE/UPGRADES/v2/v2.10-to-v2.11/v2.10-to-v2.11.md)
```

## Example 2: Handler Rename (v2.12.0)

```markdown
## ⚠️ BREAKING CHANGES

### Handler Renames

- **`lint_on_edit`** (renamed from `validate_eslint_on_write`) - Renamed in v2.12.0
  - **Why**: Handler extended from ESLint-only to 9 languages (Python, JavaScript, TypeScript, Ruby, PHP, Go, Rust, Java, C/C++, Shell)
  - **Migration**: Update `.claude/hooks-daemon.yaml` config:
    ```yaml
    # Before (v2.11.0)
    handlers:
      post_tool_use:
        validate_eslint_on_write:
          enabled: true
          priority: 30

    # After (v2.12.0)
    handlers:
      post_tool_use:
        lint_on_edit:
          enabled: true
          priority: 30
    ```
  - **Guide**: [v2.11-to-v2.12 Upgrade Guide](../CLAUDE/UPGRADES/v2/v2.11-to-v2.12/v2.11-to-v2.12.md)
```

## Example 3: Multiple Breaking Changes

```markdown
## ⚠️ BREAKING CHANGES

### Handler Removals

- **`old_handler_1`** - Removed in vX.Y.Z
  - **Why**: [Explanation]
  - **Migration**: [Steps]
  - **Guide**: [Link]

- **`old_handler_2`** - Removed in vX.Y.Z
  - **Why**: [Explanation]
  - **Migration**: [Steps]
  - **Guide**: [Link]

### Handler Renames

- **`new_name`** (renamed from `old_name`) - Renamed in vX.Y.Z
  - **Why**: [Explanation]
  - **Migration**: Update config key
  - **Guide**: [Link]

### Configuration Changes

- **`deprecated_field`** - Removed in vX.Y.Z
  - **Why**: [Explanation]
  - **Migration**: Use `new_field` instead
  - **Guide**: [Link]
```

## Release Agent Integration

The Release Agent (`.claude/agents/release-agent.md`) MUST:

1. **Detect breaking changes** by analyzing the generated CHANGELOG.md entry:
   - Scan "### Removed" section for handler removals
   - Scan "### Changed" section for handler renames and items marked `**BREAKING**`
   - Search entire entry for keywords: "BREAKING", "incompatible", "breaking change"

2. **Generate BREAKING CHANGES section** using this template format

3. **Insert section** into `RELEASES/vX.Y.Z.md` immediately after "## Highlights" section

4. **Link to upgrade guides** in CLAUDE/UPGRADES/ directory

5. **Only add section if breaking changes detected** - do not add empty section

## Content Guidelines

**Why**: Be specific and technical
- ✅ "Project-specific validation code that doesn't belong in core daemon"
- ✅ "Handler extended from ESLint-only to 9 languages"
- ❌ "We decided to remove it"
- ❌ "Better approach"

**Migration**: Be actionable and precise
- ✅ "Remove handler from config, or move to `.claude/project-handlers/` if needed"
- ✅ "Update config key from `validate_eslint_on_write` to `lint_on_edit`"
- ❌ "Update your config"
- ❌ "Migrate to new version"

**Guide Links**: Always use relative paths from RELEASES/ directory
- ✅ `../CLAUDE/UPGRADES/v2/v2.11-to-v2.12/v2.11-to-v2.12.md`
- ❌ Absolute paths
- ❌ GitHub URLs

## Testing

When creating breaking changes documentation:

1. Verify upgrade guide exists at linked path
2. Ensure migration instructions are complete
3. Test migration steps manually
4. Validate all config examples are syntactically correct
5. Check that "Why" explanations are clear and justified

## Version History

- **2026-02-17**: Created template for Plan 00060 Phase 6
