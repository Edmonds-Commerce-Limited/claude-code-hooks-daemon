"""Tests for the bare-path → ``bash <path>`` settings.json migrator.

Plan 00102 Phase 2 (Tier 2): when an existing client repo upgrades to a
daemon version that emits hooks via ``bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/<event>``
the SessionStart handler rewrites legacy bare-path entries one time per repo.

This file pins down the contract:
- legacy bare-path commands are detected and rewritten in-place
- a one-shot ``settings.json.bak.pre-bash-migration`` is created and
  never overwritten on subsequent migrations
- the migration is idempotent — second run is a no-op
- hand-edited non-daemon command paths are left untouched
- a structured summary is returned so the SessionStart handler can fold
  it into ``additionalContext``
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils.hook_command_migration import (
    BACKUP_SUFFIX,
    MigrationResult,
    is_legacy_hook_command,
    migrate_settings_to_bash_invocation,
)

_LEGACY_PRE_TOOL_USE = '"$CLAUDE_PROJECT_DIR"/.claude/hooks/pre-tool-use'
_NEW_PRE_TOOL_USE = 'bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/pre-tool-use'
_LEGACY_POST_TOOL_USE = '"$CLAUDE_PROJECT_DIR"/.claude/hooks/post-tool-use'
_NEW_POST_TOOL_USE = 'bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/post-tool-use'
_CUSTOM_USER_SCRIPT = "/usr/local/bin/my-custom-pre-hook.sh"


def _legacy_settings() -> dict:
    """A settings.json shaped exactly like a pre-Phase-1 install."""
    return {
        "hooks": {
            "PreToolUse": [
                {"hooks": [{"type": "command", "command": _LEGACY_PRE_TOOL_USE, "timeout": 60}]}
            ],
            "PostToolUse": [
                {"hooks": [{"type": "command", "command": _LEGACY_POST_TOOL_USE, "timeout": 60}]}
            ],
        }
    }


def _migrated_settings() -> dict:
    """A settings.json shaped exactly like the Phase-1 emitter output."""
    return {
        "hooks": {
            "PreToolUse": [
                {"hooks": [{"type": "command", "command": _NEW_PRE_TOOL_USE, "timeout": 60}]}
            ],
            "PostToolUse": [
                {"hooks": [{"type": "command", "command": _NEW_POST_TOOL_USE, "timeout": 60}]}
            ],
        }
    }


@pytest.fixture
def settings_path(tmp_path: Path) -> Path:
    """Return a path to a writable settings.json in a fresh tmp dir."""
    return tmp_path / "settings.json"


class TestIsLegacyHookCommand:
    """Pure predicate — no I/O."""

    def test_bare_path_is_legacy(self) -> None:
        assert is_legacy_hook_command(_LEGACY_PRE_TOOL_USE) is True

    def test_bash_prefixed_path_is_not_legacy(self) -> None:
        assert is_legacy_hook_command(_NEW_PRE_TOOL_USE) is False

    def test_custom_non_daemon_path_is_not_legacy(self) -> None:
        # User-written script: not a daemon wrapper, do not touch.
        assert is_legacy_hook_command(_CUSTOM_USER_SCRIPT) is False

    def test_empty_string_is_not_legacy(self) -> None:
        assert is_legacy_hook_command("") is False

    def test_bash_with_extra_args_is_not_legacy(self) -> None:
        # A user might already have wrapped with bash + extra args; do not
        # re-wrap or otherwise meddle with that.
        assert (
            is_legacy_hook_command('bash -x "$CLAUDE_PROJECT_DIR"/.claude/hooks/pre-tool-use')
            is False
        )


class TestMigrationOnLegacyFile:
    """End-to-end on a freshly-written legacy file."""

    def test_legacy_file_is_rewritten(self, settings_path: Path) -> None:
        settings_path.write_text(json.dumps(_legacy_settings(), indent=2))

        result = migrate_settings_to_bash_invocation(settings_path)

        assert isinstance(result, MigrationResult)
        assert result.migrated is True
        assert result.events_migrated == ["PostToolUse", "PreToolUse"]
        # File on disk now matches the bash-prefixed form.
        on_disk = json.loads(settings_path.read_text())
        assert on_disk == _migrated_settings()

    def test_one_shot_backup_is_created(self, settings_path: Path) -> None:
        original_content = json.dumps(_legacy_settings(), indent=2)
        settings_path.write_text(original_content)

        result = migrate_settings_to_bash_invocation(settings_path)

        backup_path = settings_path.with_name(settings_path.name + BACKUP_SUFFIX)
        assert result.backup_path == backup_path
        assert backup_path.exists()
        # Backup must preserve the ORIGINAL legacy content byte-for-byte.
        assert backup_path.read_text() == original_content


class TestIdempotency:
    """Second run is a no-op; pre-existing backup is never overwritten."""

    def test_already_migrated_file_is_no_op(self, settings_path: Path) -> None:
        settings_path.write_text(json.dumps(_migrated_settings(), indent=2))

        result = migrate_settings_to_bash_invocation(settings_path)

        assert result.migrated is False
        assert result.events_migrated == []
        # No backup is created when no migration was needed.
        backup_path = settings_path.with_name(settings_path.name + BACKUP_SUFFIX)
        assert not backup_path.exists()

    def test_existing_backup_is_preserved(self, settings_path: Path) -> None:
        # Simulate a half-migrated repo: legacy file PLUS a pre-existing
        # backup from an earlier abandoned migration. The new migration
        # MUST NOT overwrite that earlier backup.
        backup_path = settings_path.with_name(settings_path.name + BACKUP_SUFFIX)
        settings_path.write_text(json.dumps(_legacy_settings(), indent=2))
        sentinel = '{"sentinel": "earlier-backup-content-must-survive"}\n'
        backup_path.write_text(sentinel)

        result = migrate_settings_to_bash_invocation(settings_path)

        assert result.migrated is True
        assert backup_path.read_text() == sentinel


class TestMixedAndCustomCommands:
    """Hand-edited non-daemon paths must survive untouched."""

    def test_custom_command_left_alone(self, settings_path: Path) -> None:
        mixed = {
            "hooks": {
                "PreToolUse": [
                    {"hooks": [{"type": "command", "command": _LEGACY_PRE_TOOL_USE, "timeout": 60}]}
                ],
                # User-written hook pointing at a personal script.
                "Notification": [
                    {"hooks": [{"type": "command", "command": _CUSTOM_USER_SCRIPT, "timeout": 30}]}
                ],
            }
        }
        settings_path.write_text(json.dumps(mixed, indent=2))

        result = migrate_settings_to_bash_invocation(settings_path)

        assert result.migrated is True
        assert result.events_migrated == ["PreToolUse"]
        on_disk = json.loads(settings_path.read_text())
        # Daemon wrapper migrated.
        assert on_disk["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == _NEW_PRE_TOOL_USE
        # Custom user script unchanged.
        assert on_disk["hooks"]["Notification"][0]["hooks"][0]["command"] == _CUSTOM_USER_SCRIPT


class TestMissingFile:
    """A non-existent settings.json is a no-op, never an error."""

    def test_nonexistent_file_returns_no_migration(self, tmp_path: Path) -> None:
        result = migrate_settings_to_bash_invocation(tmp_path / "does-not-exist.json")

        assert result.migrated is False
        assert result.events_migrated == []
        assert result.backup_path is None


class TestMalformedSettings:
    """Defensive: never crash on hand-edited or partial settings files.

    The session-start handler must never block startup because someone's
    settings.json is the wrong shape. Each malformed shape returns a no-op
    migration result.
    """

    def test_invalid_json_is_no_op(self, settings_path: Path) -> None:
        settings_path.write_text("{not valid json")

        result = migrate_settings_to_bash_invocation(settings_path)

        assert result.migrated is False
        assert result.events_migrated == []

    def test_top_level_non_dict_is_no_op(self, settings_path: Path) -> None:
        settings_path.write_text(json.dumps(["array", "not", "object"]))

        result = migrate_settings_to_bash_invocation(settings_path)

        assert result.migrated is False

    def test_hooks_is_not_a_dict_is_no_op(self, settings_path: Path) -> None:
        settings_path.write_text(json.dumps({"hooks": ["array-not-dict"]}))

        result = migrate_settings_to_bash_invocation(settings_path)

        assert result.migrated is False

    def test_event_value_not_a_list_is_preserved(self, settings_path: Path) -> None:
        # Some user typed PreToolUse as a string by mistake. We do not
        # touch it, but we also do not crash.
        weird = {
            "hooks": {
                "PreToolUse": "not-a-list",
                "PostToolUse": [
                    {
                        "hooks": [
                            {"type": "command", "command": _LEGACY_POST_TOOL_USE, "timeout": 60}
                        ]
                    }
                ],
            }
        }
        settings_path.write_text(json.dumps(weird, indent=2))

        result = migrate_settings_to_bash_invocation(settings_path)

        assert result.migrated is True
        assert result.events_migrated == ["PostToolUse"]
        on_disk = json.loads(settings_path.read_text())
        assert on_disk["hooks"]["PreToolUse"] == "not-a-list"

    def test_hook_entry_not_a_dict_is_preserved(self, settings_path: Path) -> None:
        weird = {
            "hooks": {
                "PreToolUse": [
                    "string-entry-not-dict",
                    {
                        "hooks": [
                            {"type": "command", "command": _LEGACY_PRE_TOOL_USE, "timeout": 60}
                        ]
                    },
                ]
            }
        }
        settings_path.write_text(json.dumps(weird, indent=2))

        result = migrate_settings_to_bash_invocation(settings_path)

        assert result.migrated is True
        on_disk = json.loads(settings_path.read_text())
        assert on_disk["hooks"]["PreToolUse"][0] == "string-entry-not-dict"

    def test_inner_hooks_not_a_list_is_preserved(self, settings_path: Path) -> None:
        weird = {
            "hooks": {
                "PreToolUse": [
                    {"hooks": "not-a-list"},
                    {
                        "hooks": [
                            {"type": "command", "command": _LEGACY_PRE_TOOL_USE, "timeout": 60}
                        ]
                    },
                ]
            }
        }
        settings_path.write_text(json.dumps(weird, indent=2))

        result = migrate_settings_to_bash_invocation(settings_path)

        assert result.migrated is True
        on_disk = json.loads(settings_path.read_text())
        assert on_disk["hooks"]["PreToolUse"][0]["hooks"] == "not-a-list"

    def test_command_entry_not_a_dict_is_preserved(self, settings_path: Path) -> None:
        weird = {
            "hooks": {
                "PreToolUse": [
                    {
                        "hooks": [
                            "string-not-dict",
                            {"type": "command", "command": _LEGACY_PRE_TOOL_USE, "timeout": 60},
                        ]
                    },
                ]
            }
        }
        settings_path.write_text(json.dumps(weird, indent=2))

        result = migrate_settings_to_bash_invocation(settings_path)

        assert result.migrated is True
        on_disk = json.loads(settings_path.read_text())
        assert on_disk["hooks"]["PreToolUse"][0]["hooks"][0] == "string-not-dict"
