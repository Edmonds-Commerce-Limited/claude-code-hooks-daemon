# Plan 00065: Version-Aware Config Migration Advisory System

**Status**: Complete (2026-02-22)

## Context

When users upgrade from version X to version Y of claude-code-hooks-daemon, they receive a new default config but have no guidance on what new handler options, renamed keys, or removed features appeared between those versions. This means new capabilities (e.g., `blocking_mode` on `sed_blocker`, new handlers like `error_hiding_blocker`) go unconfigured even after upgrading.

The user specifically raised this when asking why grep was still being blocked after upgrading — the `extra_whitelist` option existed but no upgrade flow told them about it. The fix: a machine-readable manifest of config changes per version, plus a CLI advisory command that reads those manifests and reports what's new/changed relative to the user's current config.

## Recommended Approach

### Design Summary

1. **Config-change manifests** — YAML files at `CLAUDE/UPGRADES/config-changes/v{X.Y.Z}.yaml` documenting what changed in each version (added options, renamed keys, removed handlers, changed defaults). One file per version.

2. **CLI command `check-config-migrations`** — New daemon CLI command that reads all manifests between two versions and produces an actionable advisory report. Compares manifests against the user's actual config to flag options they haven't yet configured.

3. **LLM-UPDATE.md integration** — After each upgrade, the config advisory runs automatically and its output is included in the upgrade summary. Users see "3 new options available since your previous version" with example YAML.

4. **Backfill** — Create manifests for all 19 versions from v2.2.0 to v2.15.2 by reading CHANGELOG.md (the single source of truth for what changed). Versions with no config changes get empty/minimal manifests (explicit `config_changes: []` is still useful as documentation that nothing changed).

### Critical Files

| File | Role |
|------|------|
| `CLAUDE/UPGRADES/config-changes/v{X.Y.Z}.yaml` | Per-version change manifests (new) |
| `src/claude_code_hooks_daemon/install/config_migrations.py` | Manifest loader + advisory generator (new) |
| `src/claude_code_hooks_daemon/daemon/cli.py` | Register new `check-config-migrations` command |
| `CLAUDE/LLM-UPDATE.md` | Add advisory step to upgrade workflow |
| `tests/unit/install/test_config_migrations.py` | Unit tests (TDD) |
| `tests/integration/test_config_migrations_integration.py` | Integration tests |

---

## Implementation Plan

### Phase 1: Manifest Format & Structure (TDD)

**Goal**: Define and validate the YAML schema for config-change manifests.

- [x] Write failing tests for `ConfigMigrationManifest` dataclass parsing:
  - Valid manifest with all field types (added, renamed, removed, changed)
  - Minimal manifest (no changes)
  - Invalid manifest (missing required fields)
- [x] Implement `src/claude_code_hooks_daemon/install/config_migrations.py`:
  - `ConfigChangeEntry` dataclass (key, description, example_yaml, migration_note)
  - `ConfigMigrationManifest` dataclass (version, date, breaking, added, renamed, removed, changed, upgrade_guide)
  - `load_manifest(version: str) -> ConfigMigrationManifest | None` — loads from `CLAUDE/UPGRADES/config-changes/`
  - `load_manifests_between(from_version: str, to_version: str) -> list[ConfigMigrationManifest]` — returns all manifests in version order
- [x] Create manifest schema file `CLAUDE/UPGRADES/config-changes/SCHEMA.md` documenting the format
- [x] Create first manifest `CLAUDE/UPGRADES/config-changes/v2.2.0.yaml` (base version, empty changes)
- [x] Run QA: `./scripts/qa/run_all.sh`

**Manifest format**:
```yaml
version: "2.12.0"
date: "2026-02-12"
breaking: true
upgrade_guide: "CLAUDE/UPGRADES/v2/v2.11-to-v2.12/"
config_changes:
  added:
    - key: handlers.post_tool_use.lint_on_edit
      description: "New LintOnEditHandler replaces validate_eslint_on_write"
      example_yaml: |
        lint_on_edit:
          enabled: true
      migration_note: "Supports 9 languages via Strategy Pattern"
  renamed:
    - old_key: handlers.post_tool_use.validate_eslint_on_write
      new_key: handlers.post_tool_use.lint_on_edit
      migration_note: "Update your config key"
  removed:
    - key: handlers.post_tool_use.validate_eslint_on_write
      migration_note: "Use lint_on_edit instead"
  changed: []
```

---

### Phase 2: Advisory Generator (TDD)

**Goal**: Implement the advisory logic that compares manifests against a user's config.

- [x] Write failing tests for `generate_migration_advisory()`:
  - User has old key that was renamed → warns "rename X → Y"
  - User has removed handler still in config → warns "X was removed"
  - User missing a new option → advises "new option Y available"
  - User already has new option → silently skips
  - No changes between versions → returns empty advisory
  - Multiple versions span → aggregates all changes
- [x] Implement `generate_migration_advisory(from_version, to_version, user_config_path) -> MigrationAdvisory`:
  - `MigrationAdvisory` dataclass with lists: `warnings` (breaking), `suggestions` (new options), `summary`
  - Reads user's `hooks-daemon.yaml` to check which keys are present
  - Cross-references manifests: for each renamed/removed key, check if user still has old key
  - For each added key, check if user already has it (if not, include in suggestions)
- [x] Implement `format_advisory_for_llm(advisory: MigrationAdvisory) -> str`:
  - Structured text output for LLM-UPDATE.md integration
  - Clear sections: `⚠️ Action Required` (breaking), `💡 New Options Available`, `✅ No Changes Needed`
- [x] Run QA

---

### Phase 3: CLI Command (TDD)

**Goal**: Register `check-config-migrations` in daemon CLI.

- [x] Write failing tests for CLI command:
  - `check-config-migrations --from 2.10.0 --to 2.12.0` produces advisory output
  - `--from` version greater than `--to` → error
  - Unknown version → error with list of known versions
  - `--format json` flag for machine-readable output
- [x] Add `cmd_check_config_migrations()` to `src/claude_code_hooks_daemon/daemon/cli.py`:
  - Arguments: `--from VERSION`, `--to VERSION`, `--config PATH`, `--format [text|json]`
  - Default config path: auto-detect from project root (same as other config commands)
  - Calls `generate_migration_advisory()` then `format_advisory_for_llm()`
  - Exit code 0 = no warnings, 1 = warnings/suggestions present
- [x] Register in CLI argument parser alongside existing `config-diff`, `config-merge`, `config-validate`
- [x] Run daemon restart verification: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
- [x] Run QA

---

### Phase 4: Backfill All 19 Versions

**Goal**: Create manifests for every version from v2.2.0 to v2.15.2 based on CHANGELOG.md.

Using CHANGELOG.md as the source of truth, create one manifest per version. Versions with no config changes get `config_changes: {added: [], renamed: [], removed: [], changed: []}` (explicit empty = documented decision).

Versions to backfill (from CHANGELOG analysis):

| Version | Breaking | Config Changes |
|---------|----------|----------------|
| v2.2.0  | No | Base version — empty |
| v2.3.0  | No | TBD from CHANGELOG |
| v2.4.0  | No | TBD from CHANGELOG |
| v2.5.0  | No | New handlers (check CHANGELOG) |
| v2.6.0  | No | TBD from CHANGELOG |
| v2.7.0  | No | Config preservation engine |
| v2.8.0  | No | Project-level handlers (`project_handlers:` section) |
| v2.9.0  | No | Strategy Pattern (no config changes) |
| v2.10.0 | No | Python version check |
| v2.11.0 | Yes | Removed `validate_sitemap`, `remind_validator` |
| v2.12.0 | Yes | Renamed `validate_eslint_on_write` → `lint_on_edit`, new handlers |
| v2.13.0 | No | New `release_blocker` handler, `enforce_single_daemon_process` |
| v2.14.0 | No | New handlers (check CHANGELOG) |
| v2.15.0 | No | `error_hiding_blocker`, pipe_blocker options |
| v2.15.1 | No | Minor changes |
| v2.15.2 | No | Config header change |

- [x] Read CHANGELOG.md in detail and create manifest for each version
- [x] Validate all manifests parse correctly via unit test: `test_all_manifests_parse_correctly()`
- [x] Cross-reference with existing upgrade guides (v2.10→11, v2.11→12, v2.12→13) to ensure consistency

---

### Phase 5: LLM-UPDATE.md Integration

**Goal**: Add advisory step to the upgrade workflow so users automatically see what's new.

- [x] Add new step to LLM-UPDATE.md after upgrade completes:
  ```
  ## Step N: Check Config Migration Advisory

  After upgrading, check for new configuration options:

  ```bash
  $PYTHON -m claude_code_hooks_daemon.daemon.cli check-config-migrations \
    --from {PREVIOUS_VERSION} --to {NEW_VERSION}
  ```

  If any suggestions appear, review the new options and decide whether to enable them.
  ```
- [x] Add advisory output example (what the LLM will see)
- [x] Add note that advisory is informational — new options are opt-in

---

### Phase 6: Integration Tests & QA

- [x] Integration test: full advisory from v2.10.0 to v2.15.2 produces expected suggestions
- [x] Integration test: user config with renamed key gets correct warning
- [x] Integration test: user config with all new options already set → empty advisory
- [x] Run full QA: `./scripts/qa/run_all.sh`
- [x] Run daemon restart: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`

---

## Key Design Decisions

### Decision 1: Per-version manifest files (not a single aggregated file)
**Chosen**: `CLAUDE/UPGRADES/config-changes/v{X.Y.Z}.yaml` (one file per version)
**Rationale**: Aligns with upgrade guide convention (one directory per version transition). Easy to add new manifests at release time without editing a central file. Git diff shows exactly what changed per release.

### Decision 2: Manifests stored in CLAUDE/UPGRADES/ (not in src/)
**Chosen**: `CLAUDE/UPGRADES/config-changes/`
**Rationale**: These are LLM-facing documentation artifacts, not runtime code. Follows the pattern of upgrade guides. The CLI command reads them as data files, not as importable Python.

### Decision 3: Advisory is informational, not blocking
**Chosen**: Exit code 0 for suggestions, 1 for warnings (breaking changes). Not integrated as a blocking gate.
**Rationale**: New options are opt-in by design. Advisory should inform, not block upgrading. Warnings (you have a removed config key) are more urgent but still not blocking.

### Decision 4: Backfill ALL versions from v2.2.0
**Chosen**: Backfill all 19 versions.
**Rationale**: Project is young (< 1 year), CHANGELOG.md is complete and accurate, and having explicit "no changes" manifests is valuable documentation. Future tooling can rely on complete coverage.

---

## Verification

```bash
# 1. Run all tests
pytest tests/unit/install/test_config_migrations.py -v
pytest tests/integration/test_config_migrations_integration.py -v

# 2. Run CLI command
$PYTHON -m claude_code_hooks_daemon.daemon.cli check-config-migrations \
  --from 2.10.0 --to 2.15.2

# 3. Verify daemon loads
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
$PYTHON -m claude_code_hooks_daemon.daemon.cli status

# 4. Full QA suite
./scripts/qa/run_all.sh
```

Expected output of check-config-migrations (v2.10→v2.15.2) for a user on v2.10 config:
```
💡 New Options Available (since v2.10.0 → v2.15.2)

  v2.12.0: handlers.post_tool_use.lint_on_edit
    New LintOnEditHandler (replaces validate_eslint_on_write)
    Example: lint_on_edit: {enabled: true}

  v2.13.0: daemon.enforce_single_daemon_process
    Prevents multiple daemon instances. Auto-enabled in containers.

  v2.15.0: handlers.pre_tool_use.error_hiding_blocker
    Blocks commands that suppress error output (2>/dev/null pipes).

⚠️  Action Required (1 issue)

  Your config references a renamed key:
    validate_eslint_on_write → lint_on_edit (since v2.12.0)
    Update: handlers.post_tool_use in your hooks-daemon.yaml

See docs/guides/HANDLER_REFERENCE.md for full option details.
```
