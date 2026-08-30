"""Tests for the ``transport on|off|status`` CLI subcommand (Plan 00294)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_transport
from claude_code_hooks_daemon.install.transport_toggle import ToggleOutcome

_MINIMAL_CONFIG = """\
version: '1.0'
daemon:
  self_install_mode: false
  transport:
    relay_enabled: false
    nc_enabled: false
handlers:
  pre_tool_use: {}
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    claude_dir = tmp_path / ".claude"
    (claude_dir / "hooks").mkdir(parents=True)
    (claude_dir / "hooks-daemon").mkdir()
    (claude_dir / "hooks-daemon.yaml").write_text(_MINIMAL_CONFIG)
    return tmp_path


def _args(project: Path, action: str, *, as_json: bool = False) -> argparse.Namespace:
    return argparse.Namespace(project_root=project, action=action, json=as_json)


class TestTransportStatus:
    def test_status_prints_the_report_table(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cmd_transport(_args(project, "status"))
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "relay_enabled" in out
        assert "Active rung" in out
        assert "bash+python3" in out

    def test_status_json_is_parseable(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cmd_transport(_args(project, "status", as_json=True))
        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert payload["relay_enabled"] is False
        assert payload["rung"] == "bash+python3"


class TestTransportToggleWiring:
    def test_on_invokes_run_toggle_with_enable_true(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[dict[str, Any]] = []

        def fake_run_toggle(project_root: Path, *, enable: bool, **_: Any) -> ToggleOutcome:
            calls.append({"project_root": project_root, "enable": enable})
            return ToggleOutcome(action="on", changed=True, verified=True)

        monkeypatch.setattr(
            "claude_code_hooks_daemon.install.transport_toggle.run_toggle", fake_run_toggle
        )

        exit_code = cmd_transport(_args(project, "on"))

        assert exit_code == 0
        assert calls == [{"project_root": project.resolve(), "enable": True}]

    def test_off_invokes_run_toggle_with_enable_false(
        self, project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[bool] = []

        def fake_run_toggle(project_root: Path, *, enable: bool, **_: Any) -> ToggleOutcome:
            seen.append(enable)
            return ToggleOutcome(action="off", changed=True, verified=True)

        monkeypatch.setattr(
            "claude_code_hooks_daemon.install.transport_toggle.run_toggle", fake_run_toggle
        )

        assert cmd_transport(_args(project, "off")) == 0
        assert seen == [False]

    def test_no_op_toggle_reports_and_exits_zero(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(
            "claude_code_hooks_daemon.install.transport_toggle.run_toggle",
            lambda *_a, **_k: ToggleOutcome(action="off", changed=False, verified=None),
        )

        exit_code = cmd_transport(_args(project, "off"))
        out = capsys.readouterr().out

        assert exit_code == 0
        assert "already" in out

    def test_verification_failure_exits_nonzero_and_names_failures(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        outcome = ToggleOutcome(
            action="on",
            changed=True,
            verified=False,
            failures=["pre-tool-use-json: response is not JSON: garbage"],
            reverted=True,
            revert_verified=True,
        )
        monkeypatch.setattr(
            "claude_code_hooks_daemon.install.transport_toggle.run_toggle",
            lambda *_a, **_k: outcome,
        )

        exit_code = cmd_transport(_args(project, "on"))
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "pre-tool-use-json" in captured.err
        assert "revert" in captured.err.lower()

    def test_provisioning_failure_exits_nonzero_without_revert_claim(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # D2: a provisioning failure happens BEFORE anything is flipped —
        # changed=False must not be mistaken for a clean no-op, and no
        # AUTO-REVERTED claim may be printed since nothing was reverted.
        outcome = ToggleOutcome(
            action="on",
            changed=False,
            verified=False,
            failures=["relay-binary: provisioning via relay_source=build failed: no toolchain"],
        )
        monkeypatch.setattr(
            "claude_code_hooks_daemon.install.transport_toggle.run_toggle",
            lambda *_a, **_k: outcome,
        )

        exit_code = cmd_transport(_args(project, "on"))
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "relay-binary" in captured.err
        assert "AUTO-REVERTED" not in captured.err
        assert "no state was changed" in captured.err.lower()
        assert "already" not in captured.out

    def test_toggle_error_exits_nonzero(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from claude_code_hooks_daemon.install.transport_toggle import TransportToggleError

        def raise_error(*_a: Any, **_k: Any) -> ToggleOutcome:
            raise TransportToggleError("expected exactly one 'relay_enabled:' line")

        monkeypatch.setattr(
            "claude_code_hooks_daemon.install.transport_toggle.run_toggle", raise_error
        )

        exit_code = cmd_transport(_args(project, "on"))

        assert exit_code == 1
        assert "relay_enabled" in capsys.readouterr().err
