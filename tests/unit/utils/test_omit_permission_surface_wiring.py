"""Every reader of ``daemon.omit_permission_surface`` honours the switch (Plan 00618 N-19).

The switch removes the PermissionRequest forwarder, so each place that audits or
repairs hook registrations must stop requiring it when the project config says
``omit_permission_surface: true``, and must still require it when the key is
absent or false. One settings file without the forwarder is judged by each
consumer, with and without the switch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.handlers.registry import apply_handler_options
from claude_code_hooks_daemon.handlers.session_start.hook_registration_checker import (
    HookRegistrationCheckerHandler,
)
from claude_code_hooks_daemon.install.client_validator import ClientInstallValidator
from claude_code_hooks_daemon.utils.hook_registration import (
    HOOK_EVENTS_IN_SETTINGS,
    build_hook_registration,
    expected_hook_events,
    reconcile_settings_hooks,
    validate_settings_hooks,
)
from claude_code_hooks_daemon.utils.permission_surface import PERMISSION_REQUEST_EVENT
from claude_code_hooks_daemon.utils.settings_repair import repair_settings_registrations

_OMIT_ON = "daemon:\n  omit_permission_surface: true\n"
_OMIT_OFF = "daemon:\n  omit_permission_surface: false\n"


def _settings_without_forwarder() -> dict[str, Any]:
    hooks = {
        key: build_hook_registration(bash)
        for key, bash in HOOK_EVENTS_IN_SETTINGS.items()
        if key != PERMISSION_REQUEST_EVENT
    }
    return {"hooks": hooks}


def _project(root: Path, config: str | None) -> Path:
    claude = root / ".claude"
    claude.mkdir(parents=True)
    (claude / "settings.json").write_text(
        json.dumps(_settings_without_forwarder(), indent=2) + "\n", encoding="utf-8"
    )
    if config is not None:
        (claude / "hooks-daemon.yaml").write_text(config, encoding="utf-8")
    return root


def _mentions_forwarder(lines: list[str]) -> bool:
    return any(PERMISSION_REQUEST_EVENT in line for line in lines)


class TestHookRegistrationHelpers:
    def test_the_switch_drops_only_the_permission_request_event(self) -> None:
        kept = expected_hook_events(omit_permission_surface=True)
        everything = expected_hook_events()
        assert PERMISSION_REQUEST_EVENT in everything
        assert PERMISSION_REQUEST_EVENT not in kept
        assert set(everything) - set(kept) == {PERMISSION_REQUEST_EVENT}

    def test_validation_requires_the_forwarder_unless_the_switch_is_on(self) -> None:
        settings = _settings_without_forwarder()
        assert _mentions_forwarder(validate_settings_hooks(settings))
        assert not validate_settings_hooks(settings, omit_permission_surface=True)

    def test_reconcile_adds_the_forwarder_unless_the_switch_is_on(self) -> None:
        settings = _settings_without_forwarder()
        added, result = reconcile_settings_hooks(settings)
        assert PERMISSION_REQUEST_EVENT in result.events_added
        assert PERMISSION_REQUEST_EVENT in added["hooks"]
        kept, kept_result = reconcile_settings_hooks(settings, omit_permission_surface=True)
        assert not kept_result.changed
        assert PERMISSION_REQUEST_EVENT not in kept["hooks"]


class TestSettingsRepair:
    def test_the_switch_on_leaves_the_file_alone(self, tmp_path: Path) -> None:
        root = _project(tmp_path, _OMIT_ON)
        path = root / ".claude" / "settings.json"
        before = path.read_text(encoding="utf-8")
        assert repair_settings_registrations(path).repaired is False
        assert path.read_text(encoding="utf-8") == before

    @pytest.mark.parametrize("config", [None, _OMIT_OFF])
    def test_without_the_switch_the_forwarder_is_added(
        self, tmp_path: Path, config: str | None
    ) -> None:
        root = _project(tmp_path, config)
        path = root / ".claude" / "settings.json"
        result = repair_settings_registrations(path)
        assert result.repaired is True
        assert PERMISSION_REQUEST_EVENT in result.events_added
        assert PERMISSION_REQUEST_EVENT in json.loads(path.read_text(encoding="utf-8"))["hooks"]


class TestClientValidator:
    def test_the_switch_on_raises_no_missing_forwarder_warning(self, tmp_path: Path) -> None:
        root = _project(tmp_path, _OMIT_ON)
        result = ClientInstallValidator._verify_hook_registrations(root)
        assert not _mentions_forwarder(result.warnings)

    def test_without_the_switch_the_missing_forwarder_is_warned(self, tmp_path: Path) -> None:
        root = _project(tmp_path, None)
        result = ClientInstallValidator._verify_hook_registrations(root)
        assert _mentions_forwarder(result.warnings)


class TestHookRegistrationChecker:
    @staticmethod
    def _handler(root: Path) -> HookRegistrationCheckerHandler:
        handler = HookRegistrationCheckerHandler()
        apply_handler_options(
            handler, {"auto_migrate_settings": False, "auto_repair_registrations": False}
        )
        patcher = patch.object(handler, "_get_project_root", return_value=root)
        patcher.start()
        return handler

    def test_the_switch_on_reports_no_missing_forwarder(self, tmp_path: Path) -> None:
        handler = self._handler(_project(tmp_path, _OMIT_ON))
        try:
            result = handler.handle({"hook_event_name": "SessionStart"})
            assert not _mentions_forwarder(result.context)
            assert handler.verify_still_needed() is False
        finally:
            patch.stopall()

    def test_without_the_switch_the_missing_forwarder_is_reported(self, tmp_path: Path) -> None:
        handler = self._handler(_project(tmp_path, None))
        try:
            result = handler.handle({"hook_event_name": "SessionStart"})
            assert _mentions_forwarder(result.context)
            assert handler.verify_still_needed() is True
        finally:
            patch.stopall()
