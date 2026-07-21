"""Tests for the file-level settings.json registration self-heal util."""

from __future__ import annotations

import json
from pathlib import Path

from claude_code_hooks_daemon.utils.hook_registration import HOOK_EVENTS_IN_SETTINGS
from claude_code_hooks_daemon.utils.settings_repair import (
    BACKUP_SUFFIX,
    RepairResult,
    repair_settings_registrations,
)


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class TestRepairSettingsRegistrations:
    def test_nonexistent_file_is_noop(self, tmp_path: Path) -> None:
        result = repair_settings_registrations(tmp_path / "settings.json")
        assert isinstance(result, RepairResult)
        assert result.repaired is False
        assert result.events_added == []

    def test_adds_missing_events_and_reports_them(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        _write(settings_path, {"hooks": {}})

        result = repair_settings_registrations(settings_path)

        assert result.repaired is True
        assert set(result.events_added) == set(HOOK_EVENTS_IN_SETTINGS.keys())
        on_disk = json.loads(settings_path.read_text())
        assert set(on_disk["hooks"].keys()) == set(HOOK_EVENTS_IN_SETTINGS.keys())

    def test_idempotent_second_run_is_noop(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        _write(settings_path, {"hooks": {}})
        repair_settings_registrations(settings_path)
        result2 = repair_settings_registrations(settings_path)
        assert result2.repaired is False
        assert result2.events_added == []

    def test_preserves_permissions_and_unknown_keys(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        _write(
            settings_path,
            {"hooks": {}, "permissions": {"allow": ["Bash(ls:*)"]}, "customKey": 1},
        )
        repair_settings_registrations(settings_path)
        on_disk = json.loads(settings_path.read_text())
        assert on_disk["permissions"] == {"allow": ["Bash(ls:*)"]}
        assert on_disk["customKey"] == 1

    def test_writes_one_shot_backup(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        _write(settings_path, {"hooks": {}})
        original_bytes = settings_path.read_text()

        result = repair_settings_registrations(settings_path)

        backup = settings_path.with_name(settings_path.name + BACKUP_SUFFIX)
        assert result.backup_path == backup
        assert backup.exists()
        assert backup.read_text() == original_bytes

    def test_no_change_writes_no_backup(self, tmp_path: Path) -> None:
        # Already-complete settings must not be rewritten or backed up.
        hooks = {
            json_key: [{"hooks": [{"type": "command", "command": f".claude/hooks/{bash_key}"}]}]
            for json_key, bash_key in HOOK_EVENTS_IN_SETTINGS.items()
        }
        settings_path = tmp_path / "settings.json"
        _write(settings_path, {"hooks": hooks})
        result = repair_settings_registrations(settings_path)
        assert result.repaired is False
        backup = settings_path.with_name(settings_path.name + BACKUP_SUFFIX)
        assert not backup.exists()

    def test_malformed_json_is_failsafe_noop(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("{ not json", encoding="utf-8")
        result = repair_settings_registrations(settings_path)
        assert result.repaired is False

    def test_non_dict_json_is_failsafe_noop(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("[1, 2, 3]", encoding="utf-8")
        result = repair_settings_registrations(settings_path)
        assert result.repaired is False
