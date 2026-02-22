"""Unit tests for config migration manifest loading and advisory generation.

TDD: These tests were written BEFORE the implementation in config_migrations.py.
"""

from pathlib import Path

import pytest
import yaml

from claude_code_hooks_daemon.install.config_migrations import (
    AdvisorySuggestion,
    AdvisoryWarning,
    ConfigChangeEntry,
    ConfigChanges,
    ConfigMigrationManifest,
    MigrationAdvisory,
    RenamedEntry,
    _default_manifests_dir,
    format_advisory_for_llm,
    generate_migration_advisory,
    list_known_versions,
    load_manifest,
    load_manifests_between,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MINIMAL_MANIFEST_YAML = """\
version: "2.2.0"
date: "2026-01-27"
breaking: false
config_changes:
  added: []
  renamed: []
  removed: []
  changed: []
"""

FULL_MANIFEST_YAML = """\
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
      description: "Replaced by lint_on_edit"
      migration_note: "Use lint_on_edit instead"
  changed: []
"""

USER_CONFIG_WITH_OLD_KEY = {
    "handlers": {
        "post_tool_use": {
            "validate_eslint_on_write": {"enabled": True},
        }
    },
    "daemon": {},
}

USER_CONFIG_WITH_NEW_KEY = {
    "handlers": {
        "post_tool_use": {
            "lint_on_edit": {"enabled": True},
        }
    },
    "daemon": {},
}

USER_CONFIG_EMPTY = {
    "handlers": {},
    "daemon": {},
}


# ---------------------------------------------------------------------------
# ConfigChangeEntry
# ---------------------------------------------------------------------------


class TestConfigChangeEntry:
    def test_required_fields(self) -> None:
        entry = ConfigChangeEntry(
            key="handlers.pre_tool_use.destructive_git",
            description="Blocks dangerous git commands",
        )
        assert entry.key == "handlers.pre_tool_use.destructive_git"
        assert entry.description == "Blocks dangerous git commands"
        assert entry.example_yaml is None
        assert entry.migration_note is None

    def test_optional_fields(self) -> None:
        entry = ConfigChangeEntry(
            key="handlers.post_tool_use.lint_on_edit",
            description="New linter",
            example_yaml="lint_on_edit:\n  enabled: true\n",
            migration_note="Use this instead of validate_eslint",
        )
        assert entry.example_yaml == "lint_on_edit:\n  enabled: true\n"
        assert entry.migration_note == "Use this instead of validate_eslint"


# ---------------------------------------------------------------------------
# RenamedEntry
# ---------------------------------------------------------------------------


class TestRenamedEntry:
    def test_required_fields(self) -> None:
        entry = RenamedEntry(
            old_key="handlers.post_tool_use.validate_eslint_on_write",
            new_key="handlers.post_tool_use.lint_on_edit",
        )
        assert entry.old_key == "handlers.post_tool_use.validate_eslint_on_write"
        assert entry.new_key == "handlers.post_tool_use.lint_on_edit"
        assert entry.migration_note is None

    def test_optional_migration_note(self) -> None:
        entry = RenamedEntry(
            old_key="old",
            new_key="new",
            migration_note="Update your config",
        )
        assert entry.migration_note == "Update your config"


# ---------------------------------------------------------------------------
# ConfigChanges
# ---------------------------------------------------------------------------


class TestConfigChanges:
    def test_defaults_are_empty_lists(self) -> None:
        changes = ConfigChanges()
        assert changes.added == []
        assert changes.renamed == []
        assert changes.removed == []
        assert changes.changed == []

    def test_has_changes_false_when_empty(self) -> None:
        changes = ConfigChanges()
        assert changes.has_changes is False

    def test_has_changes_true_when_added(self) -> None:
        changes = ConfigChanges(added=[ConfigChangeEntry(key="x", description="y")])
        assert changes.has_changes is True

    def test_has_changes_true_when_renamed(self) -> None:
        changes = ConfigChanges(renamed=[RenamedEntry(old_key="a", new_key="b")])
        assert changes.has_changes is True

    def test_has_changes_true_when_removed(self) -> None:
        changes = ConfigChanges(removed=[ConfigChangeEntry(key="x", description="removed")])
        assert changes.has_changes is True


# ---------------------------------------------------------------------------
# ConfigMigrationManifest
# ---------------------------------------------------------------------------


class TestConfigMigrationManifest:
    def test_parse_minimal_manifest(self) -> None:
        data = yaml.safe_load(MINIMAL_MANIFEST_YAML)
        manifest = ConfigMigrationManifest.from_dict(data)
        assert manifest.version == "2.2.0"
        assert manifest.date == "2026-01-27"
        assert manifest.breaking is False
        assert manifest.upgrade_guide is None
        assert manifest.config_changes.has_changes is False

    def test_parse_full_manifest(self) -> None:
        data = yaml.safe_load(FULL_MANIFEST_YAML)
        manifest = ConfigMigrationManifest.from_dict(data)
        assert manifest.version == "2.12.0"
        assert manifest.breaking is True
        assert manifest.upgrade_guide == "CLAUDE/UPGRADES/v2/v2.11-to-v2.12/"
        assert len(manifest.config_changes.added) == 1
        assert len(manifest.config_changes.renamed) == 1
        assert len(manifest.config_changes.removed) == 1
        assert len(manifest.config_changes.changed) == 0

    def test_parse_added_entry(self) -> None:
        data = yaml.safe_load(FULL_MANIFEST_YAML)
        manifest = ConfigMigrationManifest.from_dict(data)
        added = manifest.config_changes.added[0]
        assert added.key == "handlers.post_tool_use.lint_on_edit"
        assert "LintOnEditHandler" in added.description
        assert added.example_yaml is not None
        assert "enabled: true" in added.example_yaml
        assert added.migration_note == "Supports 9 languages via Strategy Pattern"

    def test_parse_renamed_entry(self) -> None:
        data = yaml.safe_load(FULL_MANIFEST_YAML)
        manifest = ConfigMigrationManifest.from_dict(data)
        renamed = manifest.config_changes.renamed[0]
        assert renamed.old_key == "handlers.post_tool_use.validate_eslint_on_write"
        assert renamed.new_key == "handlers.post_tool_use.lint_on_edit"
        assert renamed.migration_note == "Update your config key"

    def test_parse_removed_entry(self) -> None:
        data = yaml.safe_load(FULL_MANIFEST_YAML)
        manifest = ConfigMigrationManifest.from_dict(data)
        removed = manifest.config_changes.removed[0]
        assert removed.key == "handlers.post_tool_use.validate_eslint_on_write"
        assert removed.migration_note == "Use lint_on_edit instead"

    def test_missing_version_raises_value_error(self) -> None:
        data: dict = {"date": "2026-01-01", "breaking": False, "config_changes": {}}
        with pytest.raises((ValueError, KeyError)):
            ConfigMigrationManifest.from_dict(data)


# ---------------------------------------------------------------------------
# load_manifest
# ---------------------------------------------------------------------------


class TestLoadManifest:
    def test_returns_none_for_unknown_version(self, tmp_path: Path) -> None:
        result = load_manifest("9.9.9", manifests_dir=tmp_path)
        assert result is None

    def test_loads_existing_manifest(self, tmp_path: Path) -> None:
        manifest_file = tmp_path / "v2.2.0.yaml"
        manifest_file.write_text(MINIMAL_MANIFEST_YAML)
        result = load_manifest("2.2.0", manifests_dir=tmp_path)
        assert result is not None
        assert result.version == "2.2.0"

    def test_loads_full_manifest(self, tmp_path: Path) -> None:
        manifest_file = tmp_path / "v2.12.0.yaml"
        manifest_file.write_text(FULL_MANIFEST_YAML)
        result = load_manifest("2.12.0", manifests_dir=tmp_path)
        assert result is not None
        assert result.breaking is True


# ---------------------------------------------------------------------------
# load_manifests_between
# ---------------------------------------------------------------------------


class TestLoadManifestsBetween:
    def _write_manifest(self, tmp_path: Path, version: str, breaking: bool = False) -> None:
        content = f"""\
version: "{version}"
date: "2026-01-01"
breaking: {"true" if breaking else "false"}
config_changes:
  added: []
  renamed: []
  removed: []
  changed: []
"""
        (tmp_path / f"v{version}.yaml").write_text(content)

    def test_returns_empty_list_when_no_manifests(self, tmp_path: Path) -> None:
        result = load_manifests_between("2.2.0", "2.5.0", manifests_dir=tmp_path)
        assert result == []

    def test_excludes_from_version_includes_to_version(self, tmp_path: Path) -> None:
        for v in ["2.2.0", "2.3.0", "2.4.0", "2.5.0"]:
            self._write_manifest(tmp_path, v)
        result = load_manifests_between("2.2.0", "2.5.0", manifests_dir=tmp_path)
        versions = [m.version for m in result]
        assert "2.2.0" not in versions  # from_version excluded
        assert "2.5.0" in versions  # to_version included
        assert "2.3.0" in versions
        assert "2.4.0" in versions

    def test_returns_manifests_in_version_order(self, tmp_path: Path) -> None:
        # Write in reverse order to test sorting
        for v in ["2.5.0", "2.3.0", "2.4.0"]:
            self._write_manifest(tmp_path, v)
        result = load_manifests_between("2.2.0", "2.5.0", manifests_dir=tmp_path)
        versions = [m.version for m in result]
        assert versions == sorted(versions, key=lambda v: tuple(int(x) for x in v.split(".")))

    def test_handles_patch_versions_correctly(self, tmp_path: Path) -> None:
        # v2.10.0 should come after v2.9.0 (not before v2.2.0)
        for v in ["2.9.0", "2.10.0", "2.10.1"]:
            self._write_manifest(tmp_path, v)
        result = load_manifests_between("2.9.0", "2.10.1", manifests_dir=tmp_path)
        versions = [m.version for m in result]
        assert "2.9.0" not in versions
        assert "2.10.0" in versions
        assert "2.10.1" in versions

    def test_from_version_greater_than_to_version_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="from_version.*to_version"):
            load_manifests_between("2.5.0", "2.2.0", manifests_dir=tmp_path)

    def test_same_from_and_to_version_returns_empty(self, tmp_path: Path) -> None:
        self._write_manifest(tmp_path, "2.5.0")
        result = load_manifests_between("2.5.0", "2.5.0", manifests_dir=tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# _default_manifests_dir
# ---------------------------------------------------------------------------


class TestDefaultManifestsDir:
    def test_returns_path_ending_in_config_changes(self) -> None:
        result = _default_manifests_dir()
        assert result.name == "config-changes"
        assert "UPGRADES" in str(result)


# ---------------------------------------------------------------------------
# list_known_versions
# ---------------------------------------------------------------------------


class TestListKnownVersions:
    def test_returns_empty_when_dir_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent"
        result = list_known_versions(manifests_dir=missing)
        assert result == []

    def test_returns_sorted_versions(self, tmp_path: Path) -> None:
        for v in ["2.5.0", "2.3.0", "2.10.0", "2.2.0"]:
            (tmp_path / f"v{v}.yaml").write_text(f'version: "{v}"\n')
        result = list_known_versions(manifests_dir=tmp_path)
        assert result == ["2.2.0", "2.3.0", "2.5.0", "2.10.0"]

    def test_skips_non_version_files(self, tmp_path: Path) -> None:
        (tmp_path / "v2.2.0.yaml").write_text('version: "2.2.0"\n')
        (tmp_path / "SCHEMA.md").write_text("# Schema\n")
        (tmp_path / "vnot-a-version.yaml").write_text("# not a version\n")
        result = list_known_versions(manifests_dir=tmp_path)
        assert result == ["2.2.0"]

    def test_returns_empty_when_no_valid_versions(self, tmp_path: Path) -> None:
        (tmp_path / "SCHEMA.md").write_text("# Schema\n")
        result = list_known_versions(manifests_dir=tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# load_manifests_between — edge cases for coverage
# ---------------------------------------------------------------------------


class TestLoadManifestsBetweenEdgeCases:
    def test_returns_empty_when_base_dir_missing(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent"
        result = load_manifests_between("2.2.0", "2.5.0", manifests_dir=missing)
        assert result == []

    def test_skips_files_with_invalid_version_pattern(self, tmp_path: Path) -> None:
        # A file starting with 'v' but non-numeric version — should be skipped
        (tmp_path / "vnot-a-version.yaml").write_text("# not valid\n")
        (tmp_path / "v2.3.0.yaml").write_text(
            'version: "2.3.0"\ndate: "2026-01-01"\nbreaking: false\n'
            "config_changes:\n  added: []\n  renamed: []\n  removed: []\n  changed: []\n"
        )
        result = load_manifests_between("2.2.0", "2.5.0", manifests_dir=tmp_path)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# generate_migration_advisory
# ---------------------------------------------------------------------------


class TestGenerateMigrationAdvisory:
    def _make_manifests_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "config-changes"
        d.mkdir()
        return d

    def _write_manifest(self, manifests_dir: Path, version: str, content: str) -> None:
        (manifests_dir / f"v{version}.yaml").write_text(content)

    def _write_user_config(self, tmp_path: Path, config: dict) -> Path:
        import yaml

        p = tmp_path / "hooks-daemon.yaml"
        p.write_text(yaml.dump(config))
        return p

    def test_empty_advisory_when_no_manifests(self, tmp_path: Path) -> None:
        md = self._make_manifests_dir(tmp_path)
        cfg = self._write_user_config(tmp_path, USER_CONFIG_EMPTY)
        advisory = generate_migration_advisory(
            from_version="2.2.0",
            to_version="2.5.0",
            user_config_path=cfg,
            manifests_dir=md,
        )
        assert advisory.warnings == []
        assert advisory.suggestions == []

    def test_warns_when_user_has_renamed_old_key(self, tmp_path: Path) -> None:
        md = self._make_manifests_dir(tmp_path)
        self._write_manifest(md, "2.12.0", FULL_MANIFEST_YAML)
        cfg = self._write_user_config(tmp_path, USER_CONFIG_WITH_OLD_KEY)
        advisory = generate_migration_advisory(
            from_version="2.11.0",
            to_version="2.12.0",
            user_config_path=cfg,
            manifests_dir=md,
        )
        assert len(advisory.warnings) == 1
        assert "validate_eslint_on_write" in advisory.warnings[0].key
        assert advisory.warnings[0].version == "2.12.0"

    def test_suggests_new_option_when_user_missing_it(self, tmp_path: Path) -> None:
        md = self._make_manifests_dir(tmp_path)
        self._write_manifest(md, "2.12.0", FULL_MANIFEST_YAML)
        cfg = self._write_user_config(tmp_path, USER_CONFIG_EMPTY)
        advisory = generate_migration_advisory(
            from_version="2.11.0",
            to_version="2.12.0",
            user_config_path=cfg,
            manifests_dir=md,
        )
        assert len(advisory.suggestions) == 1
        assert advisory.suggestions[0].key == "handlers.post_tool_use.lint_on_edit"
        assert advisory.suggestions[0].version == "2.12.0"

    def test_no_suggestion_when_user_already_has_new_key(self, tmp_path: Path) -> None:
        md = self._make_manifests_dir(tmp_path)
        self._write_manifest(md, "2.12.0", FULL_MANIFEST_YAML)
        cfg = self._write_user_config(tmp_path, USER_CONFIG_WITH_NEW_KEY)
        advisory = generate_migration_advisory(
            from_version="2.11.0",
            to_version="2.12.0",
            user_config_path=cfg,
            manifests_dir=md,
        )
        assert advisory.suggestions == []

    def test_no_warning_when_user_already_using_new_key(self, tmp_path: Path) -> None:
        md = self._make_manifests_dir(tmp_path)
        self._write_manifest(md, "2.12.0", FULL_MANIFEST_YAML)
        cfg = self._write_user_config(tmp_path, USER_CONFIG_WITH_NEW_KEY)
        advisory = generate_migration_advisory(
            from_version="2.11.0",
            to_version="2.12.0",
            user_config_path=cfg,
            manifests_dir=md,
        )
        # User has new key (lint_on_edit), not old (validate_eslint_on_write) → no warning
        assert advisory.warnings == []

    def test_aggregates_changes_across_multiple_versions(self, tmp_path: Path) -> None:
        md = self._make_manifests_dir(tmp_path)
        v1 = """\
version: "2.10.0"
date: "2026-02-11"
breaking: false
config_changes:
  added:
    - key: daemon.enforce_single_daemon_process
      description: "Prevents multiple daemon instances"
  renamed: []
  removed: []
  changed: []
"""
        v2 = """\
version: "2.11.0"
date: "2026-02-12"
breaking: false
config_changes:
  added:
    - key: handlers.pre_tool_use.release_blocker
      description: "Blocks stop during release"
  renamed: []
  removed: []
  changed: []
"""
        self._write_manifest(md, "2.10.0", v1)
        self._write_manifest(md, "2.11.0", v2)
        cfg = self._write_user_config(tmp_path, USER_CONFIG_EMPTY)
        advisory = generate_migration_advisory(
            from_version="2.9.0",
            to_version="2.11.0",
            user_config_path=cfg,
            manifests_dir=md,
        )
        assert len(advisory.suggestions) == 2

    def test_advisory_stores_from_and_to_versions(self, tmp_path: Path) -> None:
        md = self._make_manifests_dir(tmp_path)
        cfg = self._write_user_config(tmp_path, USER_CONFIG_EMPTY)
        advisory = generate_migration_advisory(
            from_version="2.10.0",
            to_version="2.15.2",
            user_config_path=cfg,
            manifests_dir=md,
        )
        assert advisory.from_version == "2.10.0"
        assert advisory.to_version == "2.15.2"


# ---------------------------------------------------------------------------
# format_advisory_for_llm
# ---------------------------------------------------------------------------


class TestFormatAdvisoryForLlm:
    def test_returns_no_changes_message_when_empty(self) -> None:
        advisory = MigrationAdvisory(
            warnings=[], suggestions=[], from_version="2.10.0", to_version="2.15.2"
        )
        output = format_advisory_for_llm(advisory)
        assert "No Changes Needed" in output or "no changes" in output.lower()

    def test_includes_warning_section_when_warnings_present(self) -> None:
        advisory = MigrationAdvisory(
            warnings=[
                AdvisoryWarning(
                    key="handlers.post_tool_use.validate_eslint_on_write",
                    message="Renamed to lint_on_edit",
                    version="2.12.0",
                )
            ],
            suggestions=[],
            from_version="2.11.0",
            to_version="2.12.0",
        )
        output = format_advisory_for_llm(advisory)
        assert "Action Required" in output or "⚠️" in output
        assert "validate_eslint_on_write" in output

    def test_includes_suggestions_section_when_suggestions_present(self) -> None:
        advisory = MigrationAdvisory(
            warnings=[],
            suggestions=[
                AdvisorySuggestion(
                    key="handlers.post_tool_use.lint_on_edit",
                    description="New LintOnEditHandler",
                    version="2.12.0",
                    example_yaml="lint_on_edit:\n  enabled: true\n",
                )
            ],
            from_version="2.11.0",
            to_version="2.12.0",
        )
        output = format_advisory_for_llm(advisory)
        assert "New Options" in output or "💡" in output
        assert "lint_on_edit" in output

    def test_output_references_handler_reference_doc(self) -> None:
        advisory = MigrationAdvisory(
            warnings=[],
            suggestions=[
                AdvisorySuggestion(
                    key="handlers.pre_tool_use.error_hiding_blocker",
                    description="Blocks error hiding",
                    version="2.15.0",
                )
            ],
            from_version="2.14.0",
            to_version="2.15.0",
        )
        output = format_advisory_for_llm(advisory)
        assert "HANDLER_REFERENCE" in output or "docs/guides" in output

    def test_includes_version_range_header(self) -> None:
        advisory = MigrationAdvisory(
            warnings=[], suggestions=[], from_version="2.10.0", to_version="2.15.2"
        )
        output = format_advisory_for_llm(advisory)
        assert "2.10.0" in output
        assert "2.15.2" in output

    def test_warning_with_migration_note_includes_update_line(self) -> None:
        advisory = MigrationAdvisory(
            warnings=[
                AdvisoryWarning(
                    key="handlers.post_tool_use.validate_eslint_on_write",
                    message="Renamed to lint_on_edit",
                    version="2.12.0",
                    migration_note="Update your config key to lint_on_edit",
                )
            ],
            suggestions=[],
            from_version="2.11.0",
            to_version="2.12.0",
        )
        output = format_advisory_for_llm(advisory)
        assert "Update: Update your config key to lint_on_edit" in output
