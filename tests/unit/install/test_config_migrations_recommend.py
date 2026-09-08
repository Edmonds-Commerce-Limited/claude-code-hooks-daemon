"""Plan 00133 Phase 2: recommended/dormant promotion + changed-value comparison.

TDD — written BEFORE implementing the schema extension and the value-comparison
advisory path in config_migrations.py.

New capabilities under test:
  - ConfigChangeEntry carries `recommended`, `dormant`, `recommended_value`.
  - from_dict parses those on both `added` and `changed` entries.
  - The advisory PROMOTES a `changed` entry whose `recommended_value` differs
    from the client's current value (covers both "key absent → silently
    inherits new default" and "key explicitly holds the old value").
  - A `changed` entry already at `recommended_value` produces NO suggestion.
  - format_advisory_for_llm renders a dedicated "Recommended" section.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from claude_code_hooks_daemon.install.config_migrations import (
    ConfigChangeEntry,
    ConfigMigrationManifest,
    format_advisory_for_llm,
    generate_migration_advisory,
)

# ---------------------------------------------------------------------------
# Manifest fixtures
# ---------------------------------------------------------------------------

# A default-flip: an existing key whose recommended value changed to `false`.
FLIP_MANIFEST_YAML = """\
version: "3.24.0"
date: "2026-06-22"
breaking: false
config_changes:
  added: []
  renamed: []
  removed: []
  changed:
    - key: handlers.pre_tool_use.markdown_organization.options.allow_untracked_claude_memory
      description: "Now blocks untracked Claude memory by default."
      recommended: true
      recommended_value: false
      migration_note: "Migrate existing memory into tracked docs first."
"""

# A brand-new opt-in option we recommend enabling.
ADDED_RECOMMENDED_YAML = """\
version: "3.24.0"
date: "2026-06-22"
breaking: false
config_changes:
  added:
    - key: handlers.pre_tool_use.some_handler.options.new_protection
      description: "Opt-in protection, recommended."
      recommended: true
      dormant: true
      recommended_value: true
      example_yaml: |
        some_handler:
          options:
            new_protection: true
  renamed: []
  removed: []
  changed: []
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    manifests_dir = tmp_path / "manifests"
    manifests_dir.mkdir(exist_ok=True)
    (manifests_dir / name).write_text(content)
    return manifests_dir


def _write_user_config(tmp_path: Path, config: dict) -> Path:
    cfg = tmp_path / "hooks-daemon.yaml"
    cfg.write_text(yaml.safe_dump(config))
    return cfg


# ---------------------------------------------------------------------------
# Schema: ConfigChangeEntry + from_dict
# ---------------------------------------------------------------------------


class TestSchemaFields:
    def test_entry_accepts_new_fields(self) -> None:
        entry = ConfigChangeEntry(
            key="a.b.c",
            description="desc",
            recommended=True,
            dormant=True,
            recommended_value=False,
        )
        assert entry.recommended is True
        assert entry.dormant is True
        assert entry.recommended_value is False

    def test_entry_defaults_are_unobtrusive(self) -> None:
        entry = ConfigChangeEntry(key="a.b.c", description="desc")
        assert entry.recommended is False
        assert entry.dormant is False
        # recommended_value defaults to the UNSET sentinel, NOT None/False —
        # so a genuine recommended_value of False/None is distinguishable.
        assert entry.recommended_value is not False
        assert entry.recommended_value is not True

    def test_from_dict_parses_changed_recommended_value(self) -> None:
        manifest = ConfigMigrationManifest.from_dict(yaml.safe_load(FLIP_MANIFEST_YAML))
        changed = manifest.config_changes.changed
        assert len(changed) == 1
        assert changed[0].recommended is True
        assert changed[0].recommended_value is False

    def test_from_dict_parses_added_recommended(self) -> None:
        manifest = ConfigMigrationManifest.from_dict(yaml.safe_load(ADDED_RECOMMENDED_YAML))
        added = manifest.config_changes.added
        assert added[0].recommended is True
        assert added[0].dormant is True
        assert added[0].recommended_value is True


# ---------------------------------------------------------------------------
# Advisory: changed-value comparison
# ---------------------------------------------------------------------------


class TestChangedValuePromotion:
    def test_flip_surfaces_when_key_absent(self, tmp_path: Path) -> None:
        """Client without the key inherits the new default silently → must be told."""
        manifests_dir = _write(tmp_path, "v3.24.0.yaml", FLIP_MANIFEST_YAML)
        user_cfg = _write_user_config(tmp_path, {"handlers": {"pre_tool_use": {}}})
        advisory = generate_migration_advisory(
            "3.23.0", "3.24.0", user_cfg, manifests_dir=manifests_dir
        )
        recommended = [s for s in advisory.suggestions if s.recommended]
        assert any("allow_untracked_claude_memory" in s.key for s in recommended)

    def test_flip_surfaces_when_client_holds_old_value(self, tmp_path: Path) -> None:
        manifests_dir = _write(tmp_path, "v3.24.0.yaml", FLIP_MANIFEST_YAML)
        user_cfg = _write_user_config(
            tmp_path,
            {
                "handlers": {
                    "pre_tool_use": {
                        "markdown_organization": {
                            "options": {"allow_untracked_claude_memory": True}
                        }
                    }
                }
            },
        )
        advisory = generate_migration_advisory(
            "3.23.0", "3.24.0", user_cfg, manifests_dir=manifests_dir
        )
        assert any(s.recommended for s in advisory.suggestions)

    def test_no_promotion_when_already_at_recommended_value(self, tmp_path: Path) -> None:
        manifests_dir = _write(tmp_path, "v3.24.0.yaml", FLIP_MANIFEST_YAML)
        user_cfg = _write_user_config(
            tmp_path,
            {
                "handlers": {
                    "pre_tool_use": {
                        "markdown_organization": {
                            "options": {"allow_untracked_claude_memory": False}
                        }
                    }
                }
            },
        )
        advisory = generate_migration_advisory(
            "3.23.0", "3.24.0", user_cfg, manifests_dir=manifests_dir
        )
        assert not any("allow_untracked_claude_memory" in s.key for s in advisory.suggestions)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


class TestFormatting:
    def test_recommended_section_rendered(self, tmp_path: Path) -> None:
        manifests_dir = _write(tmp_path, "v3.24.0.yaml", FLIP_MANIFEST_YAML)
        user_cfg = _write_user_config(tmp_path, {"handlers": {"pre_tool_use": {}}})
        advisory = generate_migration_advisory(
            "3.23.0", "3.24.0", user_cfg, manifests_dir=manifests_dir
        )
        text = format_advisory_for_llm(advisory)
        assert "Recommended" in text
        assert "allow_untracked_claude_memory" in text


# ---------------------------------------------------------------------------
# Advisory: only_if_set (Plan 00362)
# ---------------------------------------------------------------------------

# A nudge aimed only at clients holding an explicit override: the default is
# already the recommended value, so an absent key needs no advice.
ONLY_IF_SET_YAML = """\
version: "3.24.0"
date: "2026-06-22"
breaking: false
config_changes:
  added: []
  renamed: []
  removed: []
  changed:
    - key: handlers.status_line.some_handler.enabled
      description: "The reason you enabled this is gone; turn it back off."
      recommended: true
      recommended_value: false
      only_if_set: true
"""


class TestOnlyIfSet:
    def test_from_dict_parses_only_if_set(self) -> None:
        manifest = ConfigMigrationManifest.from_dict(yaml.safe_load(ONLY_IF_SET_YAML))
        assert manifest.config_changes.changed[0].only_if_set is True

    def test_only_if_set_defaults_false(self) -> None:
        manifest = ConfigMigrationManifest.from_dict(yaml.safe_load(FLIP_MANIFEST_YAML))
        assert manifest.config_changes.changed[0].only_if_set is False
        assert ConfigChangeEntry(key="a.b", description="d").only_if_set is False

    def test_absent_key_produces_no_suggestion(self, tmp_path: Path) -> None:
        manifests_dir = _write(tmp_path, "v3.24.0.yaml", ONLY_IF_SET_YAML)
        user_cfg = _write_user_config(tmp_path, {"handlers": {"status_line": {}}})
        advisory = generate_migration_advisory(
            "3.23.0", "3.24.0", user_cfg, manifests_dir=manifests_dir
        )
        assert advisory.suggestions == []

    def test_explicit_old_value_is_still_promoted(self, tmp_path: Path) -> None:
        manifests_dir = _write(tmp_path, "v3.24.0.yaml", ONLY_IF_SET_YAML)
        user_cfg = _write_user_config(
            tmp_path,
            {"handlers": {"status_line": {"some_handler": {"enabled": True}}}},
        )
        advisory = generate_migration_advisory(
            "3.23.0", "3.24.0", user_cfg, manifests_dir=manifests_dir
        )
        assert [s.key for s in advisory.suggestions] == [
            "handlers.status_line.some_handler.enabled"
        ]
        assert advisory.suggestions[0].current_value is True

    def test_explicit_recommended_value_is_quiet(self, tmp_path: Path) -> None:
        manifests_dir = _write(tmp_path, "v3.24.0.yaml", ONLY_IF_SET_YAML)
        user_cfg = _write_user_config(
            tmp_path,
            {"handlers": {"status_line": {"some_handler": {"enabled": False}}}},
        )
        advisory = generate_migration_advisory(
            "3.23.0", "3.24.0", user_cfg, manifests_dir=manifests_dir
        )
        assert advisory.suggestions == []
