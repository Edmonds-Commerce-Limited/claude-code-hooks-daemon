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
      recommended: false                           # Optional — promote into the
                                                   #   "Recommended — enable these" section
      dormant: false                               # Optional — true = off until opted in
      recommended_value: true                      # Optional — value the client should set

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
    - key: handlers.pre_tool_use.markdown_organization.options.allow_untracked_claude_memory
      description: "Now blocks untracked Claude memory writes by default"
      recommended: true                            # Promote into "Recommended"
      recommended_value: false                     # Advisory fires when client's value differs
      migration_note: "Migrate existing memory into tracked docs first"
```

## Promotion Fields (Plan 00133)

`added` and `changed` entries support three optional promotion fields so the
advisory can *recommend enabling* a dormant feature, not just list it:

| Field               | Applies to        | Effect                                                                                                                                                                                                                                                                                                            |
| ------------------- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `recommended`       | `added`/`changed` | When `true`, the entry renders in the **🆕 Recommended — enable these** section instead of the quiet **💡 New Options Available**.                                                                                                                                                                                |
| `dormant`           | `added`/`changed` | Marks an off-by-default feature that is inert until opted in (distinguishes a dormant opt-in from a default-safe FYI addition).                                                                                                                                                                                   |
| `recommended_value` | `added`/`changed` | The value the client should set. For a **`changed`** entry (a default flip) the advisory compares the client's current value against this and promotes the change when they differ — covering both a client who never set the key (silently inherits the new default) and one who explicitly holds the old value. |

A `changed` entry **without** `recommended_value` remains documentation-only
(no suggestion is generated).

## Key Format

Config paths use dot notation mirroring the YAML structure:

| Config location                         | Key format                              |
| --------------------------------------- | --------------------------------------- |
| `handlers.pre_tool_use.destructive_git` | `handlers.pre_tool_use.destructive_git` |
| `handlers.post_tool_use.lint_on_edit`   | `handlers.post_tool_use.lint_on_edit`   |
| `daemon.enforce_single_daemon_process`  | `daemon.enforce_single_daemon_process`  |
| `daemon.project_languages`              | `daemon.project_languages`              |

## Advisory Logic

The `check-config-migrations` CLI command:

1. Loads all manifests between `--from` and `--to` versions (range is exclusive/inclusive)
2. Checks user config at the specified path
3. For **renamed** keys: warns if user still has the old key
4. For **added** keys: suggests if user doesn't have the new key yet (promoted
   into the Recommended section when `recommended: true`)
5. For **changed** keys with a `recommended_value`: promotes the change when the
   client's current value differs from `recommended_value` (default-flip path)
6. For **removed** keys: warns if user still has the removed key (see note below)

Note: Removed keys generate warnings only if they appear in the `renamed` section.
A `changed` entry without `recommended_value` is documentation-only; the advisory
focuses on actionable changes.

## Maintenance

Add a new manifest file at release time. The release agent handles this automatically
when using the `/release` skill.

For backfilled versions (historical), use CHANGELOG.md as the source of truth.
