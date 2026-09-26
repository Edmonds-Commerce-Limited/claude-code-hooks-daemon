"""Tests for the file-level settings.json registration self-heal util."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.utils.hook_registration import HOOK_EVENTS_IN_SETTINGS
from claude_code_hooks_daemon.utils.settings_repair import (
    _TMP_SUFFIX,
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

    def test_repair_preserves_the_file_mode(self, tmp_path: Path) -> None:
        """Repairing must not rewrite the file's permissions (Plan 00239).

        The repair stages a temp file and ``replace()``s it over settings.json, so
        the file inherits the TEMP file's mode rather than keeping its own. The
        real target is git-TRACKED (``.claude/settings.json``), so a mode rewrite
        here changes a file the user has committed — under the daemon's umask-0
        that meant handing it 0666.

        The permissive umask is deliberate: under a restrictive one the temp file
        would come out tight anyway and this would pass without testing anything.
        """
        settings_path = tmp_path / "settings.json"
        _write(settings_path, {"hooks": {}})
        settings_path.chmod(0o644)

        previous_umask = os.umask(0)
        try:
            result = repair_settings_registrations(settings_path)
        finally:
            os.umask(previous_umask)

        assert result.repaired is True, "test needs a repair to actually happen"
        assert stat.S_IMODE(settings_path.stat().st_mode) == 0o644

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

    def test_successful_write_leaves_no_temp_residue(self, tmp_path: Path) -> None:
        # An atomic write goes via a sibling temp file that must be gone (renamed
        # into place) after a successful repair — only settings.json + backup remain.
        settings_path = tmp_path / "settings.json"
        _write(settings_path, {"hooks": {}})

        repair_settings_registrations(settings_path)

        names = sorted(p.name for p in tmp_path.iterdir())
        assert names == sorted(["settings.json", "settings.json" + BACKUP_SUFFIX])

    def test_atomic_write_leaves_original_intact_if_replace_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # If the atomic rename fails mid-repair, the live settings.json must be
        # byte-for-byte intact (never truncated) — the merged content only ever
        # lands via Path.replace(), never a partial write to the live file.
        settings_path = tmp_path / "settings.json"
        _write(settings_path, {"hooks": {}})
        original_bytes = settings_path.read_text()

        def _boom(self: Path, target: object) -> None:
            raise OSError("simulated rename failure")

        monkeypatch.setattr(Path, "replace", _boom)

        result = repair_settings_registrations(settings_path)

        assert result.repaired is False
        # The critical guarantee: the live file is byte-for-byte the original,
        # never a truncated partial — the merged content only lands via replace.
        assert settings_path.read_text() == original_bytes
        # A failed replace may leave the staging temp behind (harmless — the next
        # repair overwrites it); the live settings.json is never among the debris.
        residue = {p.name for p in tmp_path.iterdir()} - {
            "settings.json",
            "settings.json" + BACKUP_SUFFIX,
        }
        assert residue <= {"settings.json" + _TMP_SUFFIX}

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

    def test_concurrent_write_survives_the_repair(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A writer that lands between our read and our replace must not be lost.

        Plan 00468 G7: Claude Code's own plugin CLI (``/plugin``,
        ``claude plugin install/enable/disable``) is an uncounted, unlocked
        writer of ``settings.json``. This simulates it landing an
        ``enabledPlugins`` change right after the repair's first read; the
        repair must re-read immediately before replacing and fold its own
        addition onto the concurrent writer's content, never overwrite it.
        """
        settings_path = tmp_path / "settings.json"
        _write(settings_path, {"hooks": {}})
        original_read_text = Path.read_text
        read_count = {"n": 0}
        concurrent_settings = {
            "hooks": {},
            "enabledPlugins": {"some-plugin@some-marketplace": True},
        }

        def _read_text_with_concurrent_write(self: Path, *args: Any, **kwargs: Any) -> str:
            text: str = original_read_text(self, *args, **kwargs)
            if self == settings_path:
                read_count["n"] += 1
                if read_count["n"] == 1:
                    # Simulate the plugin CLI writing between our first read
                    # and the re-read this fix adds right before the replace.
                    settings_path.write_text(json.dumps(concurrent_settings), encoding="utf-8")
            return text

        monkeypatch.setattr(Path, "read_text", _read_text_with_concurrent_write)

        result = repair_settings_registrations(settings_path)

        assert result.repaired is True
        assert read_count["n"] >= 2, "repair must re-read before replacing"
        on_disk = json.loads(settings_path.read_text())
        assert on_disk["enabledPlugins"] == {"some-plugin@some-marketplace": True}
        assert set(on_disk["hooks"].keys()) == set(HOOK_EVENTS_IN_SETTINGS.keys())

    def test_concurrent_corruption_aborts_loudly_without_clobbering(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A concurrent writer that leaves invalid JSON must never be overwritten.

        The repair cannot merge onto content it cannot parse, and clobbering a
        writer that ran after us would silently discard its change. The only
        safe response is to abort without writing.
        """
        settings_path = tmp_path / "settings.json"
        _write(settings_path, {"hooks": {}})
        original_read_text = Path.read_text
        read_count = {"n": 0}

        def _read_text_with_concurrent_corruption(self: Path, *args: Any, **kwargs: Any) -> str:
            text: str = original_read_text(self, *args, **kwargs)
            if self == settings_path:
                read_count["n"] += 1
                if read_count["n"] == 1:
                    settings_path.write_text("{ not json", encoding="utf-8")
            return text

        monkeypatch.setattr(Path, "read_text", _read_text_with_concurrent_corruption)

        result = repair_settings_registrations(settings_path)

        assert result.repaired is False
        assert settings_path.read_text() == "{ not json"
