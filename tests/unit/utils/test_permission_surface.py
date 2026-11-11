"""The opt-in switch that omits the daemon's permission-prompt surface (Plan 00474)."""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.paths import ProjectPath
from claude_code_hooks_daemon.utils.hook_registration import (
    HOOK_EVENTS_IN_SETTINGS,
    build_hook_registration,
    reconcile_settings_hooks,
    validate_settings_hooks,
)
from claude_code_hooks_daemon.utils.permission_surface import (
    OMIT_KEY,
    PERMISSION_REQUEST_EVENT,
    SwitchSetting,
    daemon_deny_rules,
    read_omit_permission_surface,
    read_permission_surface_setting,
    strip_permission_surface,
)

DAEMON_RULES = [ProjectPath.claude_code_deny_rule(r) for r in ProjectPath.EPHEMERAL_ROOTS]


def _full_settings(extra_deny: list[str] | None = None) -> dict[str, Any]:
    return {
        "permissions": {"deny": [*DAEMON_RULES, *(extra_deny or [])]},
        "hooks": {k: build_hook_registration(v) for k, v in HOOK_EVENTS_IN_SETTINGS.items()},
    }


def _write_config(project: Path, body: str) -> Path:
    claude = project / ".claude"
    claude.mkdir()
    (claude / "hooks-daemon.yaml").write_text(body, encoding="utf-8")
    return claude / "settings.json"


class TestDaemonDenyRules:
    def test_derived_from_ephemeral_roots(self) -> None:
        assert daemon_deny_rules() == tuple(DAEMON_RULES)


class TestReadSwitch:
    def test_absent_config_is_off(self, tmp_path: Path) -> None:
        assert read_omit_permission_surface(tmp_path / ".claude" / "settings.json") is False

    def test_key_absent_is_off(self, tmp_path: Path) -> None:
        path = _write_config(tmp_path, "daemon:\n  log_level: INFO\n")
        assert read_omit_permission_surface(path) is False

    def test_true_is_on(self, tmp_path: Path) -> None:
        path = _write_config(tmp_path, f"daemon:\n  {OMIT_KEY}: true\n")
        assert read_omit_permission_surface(path) is True

    def test_false_is_off(self, tmp_path: Path) -> None:
        path = _write_config(tmp_path, f"daemon:\n  {OMIT_KEY}: false\n")
        assert read_omit_permission_surface(path) is False

    def test_non_boolean_is_off_and_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = _write_config(tmp_path, f"daemon:\n  {OMIT_KEY}: 'yes please'\n")
        with caplog.at_level(logging.WARNING):
            assert read_omit_permission_surface(path) is False
        assert OMIT_KEY in caplog.text

    def test_unparseable_config_is_off_and_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = _write_config(tmp_path, "daemon: [unclosed\n")
        with caplog.at_level(logging.WARNING):
            assert read_omit_permission_surface(path) is False
        assert "hooks-daemon.yaml" in caplog.text

    def test_non_mapping_config_is_off_and_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = _write_config(tmp_path, "- a\n- b\n")
        with caplog.at_level(logging.WARNING):
            assert read_omit_permission_surface(path) is False
        assert caplog.text


class TestReadSettingAsWritten:
    def test_absent_config_is_absent(self, tmp_path: Path) -> None:
        setting = read_permission_surface_setting(tmp_path / ".claude" / "settings.json")
        assert setting is SwitchSetting.ABSENT

    def test_key_absent_is_absent(self, tmp_path: Path) -> None:
        path = _write_config(tmp_path, "daemon:\n  log_level: INFO\n")
        assert read_permission_surface_setting(path) is SwitchSetting.ABSENT

    def test_explicit_false_is_off(self, tmp_path: Path) -> None:
        path = _write_config(tmp_path, f"daemon:\n  {OMIT_KEY}: false\n")
        assert read_permission_surface_setting(path) is SwitchSetting.OFF

    def test_true_is_on(self, tmp_path: Path) -> None:
        path = _write_config(tmp_path, f"daemon:\n  {OMIT_KEY}: true\n")
        assert read_permission_surface_setting(path) is SwitchSetting.ON

    def test_malformed_is_unreadable_and_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = _write_config(tmp_path, f"daemon:\n  {OMIT_KEY}: 'maybe'\n")
        with caplog.at_level(logging.WARNING):
            assert read_permission_surface_setting(path) is SwitchSetting.UNREADABLE
        assert OMIT_KEY in caplog.text

    def test_unparseable_is_unreadable_and_logged_once(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = _write_config(tmp_path, "daemon: [unclosed\n")
        with caplog.at_level(logging.WARNING):
            assert read_permission_surface_setting(path) is SwitchSetting.UNREADABLE
        assert caplog.text.count("hooks-daemon.yaml") == 1


class TestStrip:
    def test_removes_hook_and_daemon_rules(self) -> None:
        stripped, removed = strip_permission_surface(_full_settings())
        assert PERMISSION_REQUEST_EVENT not in stripped["hooks"]
        assert "permissions" not in stripped
        assert removed
        assert "hooks.PermissionRequest" in removed

    def test_input_not_mutated(self) -> None:
        original = _full_settings()
        snapshot = copy.deepcopy(original)
        strip_permission_surface(original)
        assert original == snapshot

    def test_user_deny_rules_survive(self) -> None:
        stripped, _ = strip_permission_surface(_full_settings(["Bash(rm -rf /)"]))
        assert stripped["permissions"] == {"deny": ["Bash(rm -rf /)"]}

    def test_other_permission_keys_survive(self) -> None:
        settings = _full_settings()
        settings["permissions"]["allow"] = ["Read(*)"]
        stripped, _ = strip_permission_surface(settings)
        assert stripped["permissions"] == {"allow": ["Read(*)"]}

    def test_user_hook_in_same_event_survives(self) -> None:
        settings = _full_settings()
        user_group = {"hooks": [{"type": "command", "command": "bash my-own-script.sh"}]}
        settings["hooks"][PERMISSION_REQUEST_EVENT].append(user_group)
        stripped, _ = strip_permission_surface(settings)
        assert stripped["hooks"][PERMISSION_REQUEST_EVENT] == [user_group]

    def test_user_hook_sharing_group_with_forwarder_survives(self) -> None:
        settings = _full_settings()
        mine = {"type": "command", "command": "bash my-own-script.sh"}
        settings["hooks"][PERMISSION_REQUEST_EVENT][0]["hooks"].append(mine)
        stripped, _ = strip_permission_surface(settings)
        assert stripped["hooks"][PERMISSION_REQUEST_EVENT] == [{"hooks": [mine]}]

    def test_other_events_untouched(self) -> None:
        settings = _full_settings()
        stripped, _ = strip_permission_surface(settings)
        for key in HOOK_EVENTS_IN_SETTINGS:
            if key != PERMISSION_REQUEST_EVENT:
                assert stripped["hooks"][key] == settings["hooks"][key]

    def test_idempotent(self) -> None:
        once, _ = strip_permission_surface(_full_settings())
        twice, removed = strip_permission_surface(once)
        assert twice == once
        assert removed == ()

    def test_nothing_to_strip_reports_nothing(self) -> None:
        settings: dict[str, Any] = {"model": "x", "permissions": {"deny": ["Bash(x)"]}}
        stripped, removed = strip_permission_surface(settings)
        assert stripped == settings
        assert removed == ()

    def test_malformed_shapes_are_left_alone(self) -> None:
        settings: dict[str, Any] = {"permissions": "nope", "hooks": {"PermissionRequest": "nope"}}
        stripped, removed = strip_permission_surface(settings)
        assert stripped == settings
        assert removed == ()

    def test_user_empty_permissions_block_untouched_when_nothing_removed(self) -> None:
        settings: dict[str, Any] = {"permissions": {}, "hooks": {}}
        stripped, removed = strip_permission_surface(settings)
        assert stripped == settings
        assert removed == ()


class TestHookRegistrationAwareness:
    def test_validate_flags_missing_by_default(self) -> None:
        stripped, _ = strip_permission_surface(_full_settings())
        assert validate_settings_hooks(stripped)

    def test_validate_accepts_omission_when_switch_on(self) -> None:
        stripped, _ = strip_permission_surface(_full_settings())
        assert validate_settings_hooks(stripped, omit_permission_surface=True) == []

    def test_reconcile_default_re_adds_the_hook(self) -> None:
        stripped, _ = strip_permission_surface(_full_settings())
        restored, result = reconcile_settings_hooks(stripped)
        assert result.events_added == [PERMISSION_REQUEST_EVENT]
        assert PERMISSION_REQUEST_EVENT in restored["hooks"]

    def test_reconcile_with_switch_does_not_re_add_it(self) -> None:
        stripped, _ = strip_permission_surface(_full_settings())
        _, result = reconcile_settings_hooks(stripped, omit_permission_surface=True)
        assert result.changed is False
