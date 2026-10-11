"""N360 (owner ruling C6): an upgrade keeps running the opt-in handlers that ran before it.

The report of Plan 00493 names the handlers a rule change stops. The owner ruled
that the upgrade should also write ``enabled: true`` for each, so the project's
real configuration carries across the upgrade, and then tell the agent what it
did, why, and how to change it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

import claude_code_hooks_daemon.install.effective_handlers as effective_module
from claude_code_hooks_daemon.daemon.init_config import generate_config
from claude_code_hooks_daemon.install.config_cli import run_check_effective_handlers
from claude_code_hooks_daemon.install.effective_handlers import (
    HandlerChange,
    apply_restore,
    effective_handler_changes,
    format_changes,
)

_FROM = "3.67.0"
_TO = "3.69.0"
_STOPPED = HandlerChange(event="post_tool_use", config_key="goal_injection", change="stops")
_STOPPED_PRE = HandlerChange(
    event="pre_tool_use", config_key="flaggable_content_channel_guard", change="stops"
)
_STARTED = HandlerChange(event="stop", config_key="something_new", change="starts")


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "hooks-daemon.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def _loaded(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


class TestApplyRestore:
    def test_adds_the_missing_key_under_an_existing_event_and_keeps_comments(
        self, tmp_path: Path
    ) -> None:
        path = _write(
            tmp_path,
            "# my project\nversion: '2.0'\nhandlers:\n"
            "  post_tool_use:  # events\n    other:\n      enabled: false  # mine\n",
        )
        assert apply_restore(path, [_STOPPED]) is True
        text = path.read_text(encoding="utf-8")
        assert "# my project" in text and "# mine" in text and "# events" in text
        data = _loaded(path)
        assert data["handlers"]["post_tool_use"]["goal_injection"] == {"enabled": True}
        assert data["handlers"]["post_tool_use"]["other"] == {"enabled": False}

    def test_adds_a_missing_event_under_handlers(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "handlers:\n  stop:\n    x:\n      enabled: true\n")
        assert apply_restore(path, [_STOPPED]) is True
        assert _loaded(path)["handlers"]["post_tool_use"]["goal_injection"] == {"enabled": True}

    def test_adds_the_handlers_section_when_absent(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "version: '2.0'\ndaemon:\n  idle_timeout_seconds: 5\n")
        assert apply_restore(path, [_STOPPED, _STOPPED_PRE]) is True
        data = _loaded(path)
        assert data["daemon"] == {"idle_timeout_seconds": 5}
        assert data["handlers"]["post_tool_use"]["goal_injection"] == {"enabled": True}
        key = "flaggable_content_channel_guard"
        assert data["handlers"]["pre_tool_use"][key] == {"enabled": True}

    def test_a_started_handler_is_never_written(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "version: '2.0'\n")
        original = path.read_text(encoding="utf-8")
        assert apply_restore(path, [_STARTED]) is True
        assert path.read_text(encoding="utf-8") == original

    def test_an_empty_inline_event_mapping_is_opened_up(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "handlers:\n  post_tool_use: {}  # none yet\n  stop: {}\n")
        assert apply_restore(path, [_STOPPED]) is True
        text = path.read_text(encoding="utf-8")
        assert "# none yet" in text
        data = _loaded(path)
        assert data["handlers"]["post_tool_use"] == {"goal_injection": {"enabled": True}}
        assert data["handlers"]["stop"] == {}

    def test_an_empty_inline_handlers_mapping_is_opened_up(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "handlers: {}\nplugins: []\n")
        assert apply_restore(path, [_STOPPED]) is True
        data = _loaded(path)
        assert data["handlers"]["post_tool_use"]["goal_injection"] == {"enabled": True}
        assert data["plugins"] == []

    def test_a_non_empty_inline_handlers_mapping_is_left_alone(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "handlers: {stop: {}}\n")
        assert apply_restore(path, [_STOPPED]) is False
        assert path.read_text(encoding="utf-8") == "handlers: {stop: {}}\n"

    def test_a_non_empty_inline_event_mapping_is_left_alone(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "handlers:\n  post_tool_use: {a: {enabled: true}}\n")
        assert apply_restore(path, [_STOPPED]) is False
        assert (
            path.read_text(encoding="utf-8") == "handlers:\n  post_tool_use: {a: {enabled: true}}\n"
        )

    def test_a_second_application_changes_nothing(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "version: '2.0'\n")
        assert apply_restore(path, [_STOPPED]) is True
        first = path.read_text(encoding="utf-8")
        assert apply_restore(path, [_STOPPED]) is True
        assert path.read_text(encoding="utf-8") == first


class TestUpgradeKeepsRunningWhatRan:
    def test_after_apply_no_handler_stops_running(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "version: '2.0'\nhandlers:\n  stop:\n    x:\n      enabled: true\n")
        result = run_check_effective_handlers(_FROM, _TO, path, apply=True)
        assert result["has_changes"] is True
        assert result["applied"] is True
        after = effective_handler_changes(_loaded(path), _FROM, _TO)
        assert [c for c in after if c.change == "stops"] == []

    @pytest.mark.parametrize("profile", ["minimal", "full"])
    def test_a_generated_config_keeps_every_handler_it_ran_before(
        self, tmp_path: Path, profile: str
    ) -> None:
        path = _write(tmp_path, generate_config(profile))
        before = path.read_text(encoding="utf-8")
        result = run_check_effective_handlers(_FROM, _TO, path, apply=True)
        if result["has_changes"]:
            assert result["applied"] is True
            assert path.read_text(encoding="utf-8") != before
        after = effective_handler_changes(_loaded(path), _FROM, _TO)
        assert [c for c in after if c.change == "stops"] == []

    def test_without_apply_the_config_is_untouched(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "version: '2.0'\n")
        result = run_check_effective_handlers(_FROM, _TO, path)
        assert result["applied"] is False
        assert path.read_text(encoding="utf-8") == "version: '2.0'\n"

    def test_the_report_says_what_was_done_why_and_how_to_change_it(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "version: '2.0'\n")
        text = run_check_effective_handlers(_FROM, _TO, path, apply=True)["text"]
        assert "handler(s) RESTORED" in text
        assert "handler(s) STOP" not in text
        assert "wrote `enabled: true`" in text
        assert "carry across" in text
        assert "enabled: false" in text

    def test_an_unwritable_shape_falls_back_to_the_snippet(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "handlers: {stop: {}}\n")
        result = run_check_effective_handlers(_FROM, _TO, path, apply=True)
        assert result["applied"] is False
        assert "could not edit" in result["text"]
        assert "To keep the ones you want" in result["text"]
        assert path.read_text(encoding="utf-8") == "handlers: {stop: {}}\n"


def test_format_changes_without_apply_keeps_the_original_wording() -> None:
    text = format_changes([_STOPPED], _FROM, _TO)
    assert "STOP running" in text
    assert "wrote" not in text


def test_an_applied_report_says_to_restart_the_daemon_and_names_the_handler() -> None:
    text = format_changes([_STOPPED], _FROM, _TO, applied=True)
    assert "handlers.post_tool_use.goal_injection" in text
    assert "Restart the daemon" in text
    assert "hooks-daemon restart" in text
    assert "To keep the ones you want" not in text


def test_a_failed_apply_report_says_so_and_carries_the_snippet() -> None:
    text = format_changes([_STOPPED], _FROM, _TO, applied=False)
    assert "could not edit" in text
    assert "handler(s) STOP running" in text
    assert "To keep the ones you want" in text
    assert "goal_injection:" in text
    assert "Restart the daemon" not in text


class TestWriteSafety:
    def test_an_interrupted_replace_leaves_the_original_and_no_temp_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _write(tmp_path, "version: '2.0'\n")

        def interrupted(self: Path, target: Path) -> Path:
            raise OSError("interrupted")

        monkeypatch.setattr(Path, "replace", interrupted)
        assert apply_restore(path, [_STOPPED]) is False
        assert path.read_text(encoding="utf-8") == "version: '2.0'\n"
        assert [p.name for p in tmp_path.iterdir()] == ["hooks-daemon.yaml"]

    def test_a_permission_error_is_a_fallback_not_a_traceback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _write(tmp_path, "version: '2.0'\n")

        def denied(*_: object, **__: object) -> tuple[int, str]:
            raise PermissionError("read-only directory")

        monkeypatch.setattr(effective_module.tempfile, "mkstemp", denied)
        result = run_check_effective_handlers(_FROM, _TO, path, apply=True)
        assert result["applied"] is False
        assert "could not edit" in result["text"]
        assert "To keep the ones you want" in result["text"]
        assert path.read_text(encoding="utf-8") == "version: '2.0'\n"

    def test_the_file_mode_survives(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "version: '2.0'\n")
        path.chmod(0o640)
        assert apply_restore(path, [_STOPPED]) is True
        assert path.stat().st_mode & 0o777 == 0o640

    def test_a_symlinked_config_keeps_its_link_and_the_target_is_written(
        self, tmp_path: Path
    ) -> None:
        target_dir = tmp_path / "real"
        target_dir.mkdir()
        target = target_dir / "hooks-daemon.yaml"
        target.write_text("version: '2.0'\n", encoding="utf-8")
        link = tmp_path / "hooks-daemon.yaml"
        link.symlink_to(target)
        assert apply_restore(link, [_STOPPED]) is True
        assert link.is_symlink()
        assert _loaded(target)["handlers"]["post_tool_use"]["goal_injection"] == {"enabled": True}

    def test_crlf_line_endings_are_kept_throughout(self, tmp_path: Path) -> None:
        path = tmp_path / "hooks-daemon.yaml"
        path.write_bytes(
            b"version: '2.0'\r\nhandlers:\r\n  post_tool_use:\r\n    x:\r\n      enabled: true\r\n"
        )
        assert apply_restore(path, [_STOPPED]) is True
        raw = path.read_bytes()
        assert raw.count(b"\n") == raw.count(b"\r\n")
        assert b"goal_injection" in raw

    def test_an_explicit_enabled_false_is_never_flipped(self, tmp_path: Path) -> None:
        text = "handlers:\n  post_tool_use:\n    goal_injection:\n      enabled: false\n"
        path = _write(tmp_path, text)
        assert apply_restore(path, [_STOPPED]) is True
        assert path.read_text(encoding="utf-8") == text

    @pytest.mark.parametrize(
        "glob", [".claude/hooks-daemon.yaml", "**/hooks-daemon.yaml", ".claude/*.yaml"]
    )
    def test_a_write_protected_config_is_never_written(self, tmp_path: Path, glob: str) -> None:
        directory = tmp_path / ".claude"
        directory.mkdir()
        path = directory / "hooks-daemon.yaml"
        text = (
            "handlers:\n  pre_tool_use:\n    write_protected_paths:\n      enabled: true\n"
            f"      options:\n        paths: ['{glob}']\n"
        )
        path.write_text(text, encoding="utf-8")
        result = run_check_effective_handlers(_FROM, _TO, path, apply=True)
        assert result["applied"] is False
        assert "could not edit" in result["text"]
        assert path.read_text(encoding="utf-8") == text

    def test_a_config_protecting_other_paths_is_still_written(self, tmp_path: Path) -> None:
        directory = tmp_path / ".claude"
        directory.mkdir()
        path = directory / "hooks-daemon.yaml"
        path.write_text(
            "handlers:\n  pre_tool_use:\n    write_protected_paths:\n      enabled: true\n"
            "      options:\n        paths: ['infra/**']\n",
            encoding="utf-8",
        )
        assert run_check_effective_handlers(_FROM, _TO, path, apply=True)["applied"] is True
