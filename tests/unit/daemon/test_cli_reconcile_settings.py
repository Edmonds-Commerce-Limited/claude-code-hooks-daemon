"""Tests for the ``reconcile-settings`` CLI subcommand (Plan 00185)."""

import argparse
import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_reconcile_settings
from claude_code_hooks_daemon.utils.hook_registration import HOOK_EVENTS_IN_SETTINGS


def _ns(path: Path, check: bool = False) -> argparse.Namespace:
    return argparse.Namespace(path=path, check=check)


class TestCmdReconcileSettings:
    def test_creates_full_set_when_file_missing(self, tmp_path: Path) -> None:
        settings_path = tmp_path / ".claude" / "settings.json"
        result = cmd_reconcile_settings(_ns(settings_path))
        assert result == 0
        assert settings_path.exists()
        on_disk = json.loads(settings_path.read_text())
        assert set(on_disk["hooks"].keys()) == set(HOOK_EVENTS_IN_SETTINGS.keys())

    def test_adds_missing_events_to_partial_file(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(
            json.dumps({"hooks": {}, "permissions": {"allow": ["Bash(ls:*)"]}})
        )
        result = cmd_reconcile_settings(_ns(settings_path))
        assert result == 0
        on_disk = json.loads(settings_path.read_text())
        assert set(on_disk["hooks"].keys()) == set(HOOK_EVENTS_IN_SETTINGS.keys())
        assert on_disk["permissions"] == {"allow": ["Bash(ls:*)"]}

    def test_complete_file_is_noop_exit_zero(self, tmp_path: Path) -> None:
        hooks = {
            json_key: [{"hooks": [{"type": "command", "command": f".claude/hooks/{bash_key}"}]}]
            for json_key, bash_key in HOOK_EVENTS_IN_SETTINGS.items()
        }
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"hooks": hooks}))
        before = settings_path.read_text()
        result = cmd_reconcile_settings(_ns(settings_path))
        assert result == 0
        assert settings_path.read_text() == before

    def test_check_mode_reports_and_exits_one_when_incomplete(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"hooks": {}}))
        result = cmd_reconcile_settings(_ns(settings_path, check=True))
        assert result == 1
        # File must NOT be modified in check mode.
        assert json.loads(settings_path.read_text())["hooks"] == {}

    def test_check_mode_exits_zero_when_complete(self, tmp_path: Path) -> None:
        hooks = {
            json_key: [{"hooks": [{"type": "command", "command": f".claude/hooks/{bash_key}"}]}]
            for json_key, bash_key in HOOK_EVENTS_IN_SETTINGS.items()
        }
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"hooks": hooks}))
        result = cmd_reconcile_settings(_ns(settings_path, check=True))
        assert result == 0

    def test_malformed_json_returns_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("{ not json")
        result = cmd_reconcile_settings(_ns(settings_path))
        assert result == 1
        assert "settings.json" in capsys.readouterr().err.lower()
