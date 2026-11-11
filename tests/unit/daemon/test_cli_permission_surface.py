"""The ``permission-surface`` verb: read-only, stdout JSON, notice on stderr."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_permission_surface
from claude_code_hooks_daemon.install.settings_merge import run_settings_merge
from claude_code_hooks_daemon.utils.hook_registration import (
    HOOK_EVENTS_IN_SETTINGS,
    build_hook_registration,
)
from claude_code_hooks_daemon.utils.permission_surface import (
    PERMISSION_REQUEST_EVENT,
    daemon_deny_rules,
)


class TestPermissionSurfaceVerb:
    def test_stdout_is_json_and_stderr_carries_the_notice(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_permission_surface(argparse.Namespace()) == 0
        captured = capsys.readouterr()
        document = json.loads(captured.out)
        assert "nothing was written" in captured.err
        assert document["permissions"]["deny"] == list(daemon_deny_rules())
        assert PERMISSION_REQUEST_EVENT in document["hooks"]

    def test_it_writes_nothing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        cmd_permission_surface(argparse.Namespace())
        assert list(tmp_path.iterdir()) == []

    def test_it_is_registered_with_the_parser(self) -> None:
        args = build_parser().parse_args(["permission-surface"])
        assert args.func is cmd_permission_surface

    def test_printed_rules_equal_the_rules_the_writer_writes_with_the_switch_off(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Drift guard: the verb and the project writer share one definition."""
        shipped = {
            "hooks": {
                key: build_hook_registration(bash) for key, bash in HOOK_EVENTS_IN_SETTINGS.items()
            },
            "permissions": {"deny": list(daemon_deny_rules())},
        }
        new_default = tmp_path / "new-default.json"
        new_default.write_text(json.dumps(shipped), encoding="utf-8")
        client = tmp_path / "settings.json"
        run_settings_merge(client, new_default, omit_permission_surface=False)
        written = json.loads(client.read_text(encoding="utf-8"))

        cmd_permission_surface(argparse.Namespace())
        printed = json.loads(capsys.readouterr().out)

        assert printed["permissions"] == written["permissions"]
        assert (
            printed["hooks"][PERMISSION_REQUEST_EVENT] == written["hooks"][PERMISSION_REQUEST_EVENT]
        )
