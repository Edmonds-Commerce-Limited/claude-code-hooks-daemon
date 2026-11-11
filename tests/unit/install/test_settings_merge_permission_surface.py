"""``daemon.omit_permission_surface`` in the settings merge (Plan 00474)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.install.settings_merge import (
    MergeStatus,
    merge_settings,
    run_settings_merge,
)
from claude_code_hooks_daemon.utils.hook_registration import (
    HOOK_EVENTS_IN_SETTINGS,
    build_hook_registration,
)
from claude_code_hooks_daemon.utils.permission_surface import (
    PERMISSION_REQUEST_EVENT,
    daemon_deny_rules,
    restore_deny_rules,
)

_USER_RULE = "Bash(rm -rf /home/**)"


def _shipped() -> dict[str, Any]:
    return {
        "hooks": {
            key: build_hook_registration(bash) for key, bash in HOOK_EVENTS_IN_SETTINGS.items()
        },
        "permissions": {"deny": list(daemon_deny_rules())},
    }


class TestSwitchOn:
    def test_a_fresh_install_carries_neither_entry(self, tmp_path: Path) -> None:
        new_default = tmp_path / "new.json"
        new_default.write_text(json.dumps(_shipped()), encoding="utf-8")
        client = tmp_path / "settings.json"
        outcome = run_settings_merge(client, new_default, omit_permission_surface=True)
        assert outcome.status is MergeStatus.INSTALLED
        written = json.loads(client.read_text(encoding="utf-8"))
        assert PERMISSION_REQUEST_EVENT not in written["hooks"]
        assert "permissions" not in written

    def test_earlier_daemon_entries_go_and_user_rules_stay(self) -> None:
        client = _shipped()
        client["permissions"]["deny"].append(_USER_RULE)
        client["permissions"]["allow"] = ["Read(x)"]
        merged, report = merge_settings(client, _shipped(), omit_permission_surface=True)
        assert PERMISSION_REQUEST_EVENT not in merged["hooks"]
        assert merged["permissions"] == {"deny": [_USER_RULE], "allow": ["Read(x)"]}
        assert report.changed
        assert f"hooks.{PERMISSION_REQUEST_EVENT}" in report.surface_removed

    def test_a_second_run_is_unchanged(self, tmp_path: Path) -> None:
        new_default = tmp_path / "new.json"
        new_default.write_text(json.dumps(_shipped()), encoding="utf-8")
        client = tmp_path / "settings.json"
        client.write_text(json.dumps(_shipped()), encoding="utf-8")
        first = run_settings_merge(client, new_default, omit_permission_surface=True)
        second = run_settings_merge(client, new_default, omit_permission_surface=True)
        assert first.status is MergeStatus.MERGED
        assert second.status is MergeStatus.UNCHANGED


class TestSwitchOffRestores:
    def test_the_hook_comes_back(self) -> None:
        client = _shipped()
        del client["hooks"][PERMISSION_REQUEST_EVENT]
        merged, _ = merge_settings(client, _shipped())
        assert PERMISSION_REQUEST_EVENT in merged["hooks"]

    def test_the_deny_rules_come_back_beside_the_users_own(self) -> None:
        client = _shipped()
        client["permissions"] = {"deny": [_USER_RULE]}
        merged, report = merge_settings(client, _shipped())
        assert merged["permissions"]["deny"] == [_USER_RULE, *daemon_deny_rules()]
        assert report.changed

    def test_a_full_set_is_left_alone(self) -> None:
        merged, report = merge_settings(_shipped(), _shipped())
        assert merged == _shipped()
        assert not report.changed

    def test_a_deny_of_the_wrong_type_is_the_users_to_fix(self) -> None:
        settings = {"permissions": {"deny": "oops"}}
        restored, added = restore_deny_rules(settings)
        assert restored == settings
        assert added == ()

    @pytest.mark.parametrize("permissions", ["text", None])
    def test_a_permissions_value_of_the_wrong_type_is_untouched(self, permissions: object) -> None:
        restored, added = restore_deny_rules({"permissions": permissions})
        assert restored == {"permissions": permissions}
        assert added == ()

    def test_a_permissions_block_without_deny_gains_the_rules(self) -> None:
        restored, added = restore_deny_rules({"permissions": {"allow": ["x"]}})
        assert restored["permissions"] == {"allow": ["x"], "deny": list(daemon_deny_rules())}
        assert added == daemon_deny_rules()
