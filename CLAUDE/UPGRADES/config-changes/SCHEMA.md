# Config Migration Manifest Schema

Per-version YAML files documenting configuration changes introduced in each release.
Used by the `check-config-migrations` CLI command to generate advisory reports.

## File Naming

```
CLAUDE/UPGRADES/config-changes/v{X.Y.Z}.yaml
```

One file per released version. Versions with no config changes still get a file with
empty lists — this explicitly documents that no changes occurred, which is more useful
than a missing file (which is ambiguous).

## Schema

```yaml
# Required
version: "2.12.0"          # Exact version string matching pyproject.toml
date: "2026-02-12"         # ISO 8601 release date

# Required
breaking: true             # true if this version has breaking changes

# Optional — path to upgrade guide directory (relative to project root)
upgrade_guide: "CLAUDE/UPGRADES/v2/v2.11-to-v2.12/"

# Required section (lists may be empty)
config_changes:

  # New config keys introduced in this version
  added:
    - key: handlers.post_tool_use.lint_on_edit    # Dotted config path
      description: "What this option does"         # Required
      example_yaml: |                              # Optional YAML snippet
        lint_on_edit:
          enabled: true
      migration_note: "Optional note for users"    # Optional

  # Keys renamed from one path to another
  renamed:
    - old_key: handlers.post_tool_use.validate_eslint_on_write
      new_key: handlers.post_tool_use.lint_on_edit
      migration_note: "Update your config key"     # Optional

  # Keys removed entirely (no longer valid)
  removed:
    - key: handlers.post_tool_use.validate_sitemap
      description: "Project-specific, moved to project-handlers"
      migration_note: "Use project-level handlers instead"

  # Keys with changed semantics or defaults
  changed:
    - key: daemon.enforce_single_daemon_process
      description: "Now auto-enabled in container environments"
      migration_note: "No action needed; behavior improved"
```

## Key Format

Config paths use dot notation mirroring the YAML structure:

| Config location | Key format |
|----------------|------------|
| `handlers.pre_tool_use.destructive_git` | `handlers.pre_tool_use.destructive_git` |
| `handlers.post_tool_use.lint_on_edit` | `handlers.post_tool_use.lint_on_edit` |
| `daemon.enforce_single_daemon_process` | `daemon.enforce_single_daemon_process` |
| `daemon.project_languages` | `daemon.project_languages` |

## Advisory Logic

The `check-config-migrations` CLI command:

1. Loads all manifests between `--from` and `--to` versions (range is exclusive/inclusive)
2. Checks user config at the specified path
3. For **renamed** keys: warns if user still has the old key
4. For **added** keys: suggests if user doesn't have the new key yet
5. For **removed** keys: warns if user still has the removed key (see note below)

Note: Removed keys generate warnings only if they appear in the `renamed` section.
The `removed` section is documentation-only; the advisory focuses on actionable changes.

## Maintenance

Add a new manifest file at release time. The release agent handles this automatically
when using the `/release` skill.

For backfilled versions (historical), use CHANGELOG.md as the source of truth.
