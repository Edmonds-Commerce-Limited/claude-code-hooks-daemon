"""The shell's entry point into the settings merge (Plan 00176 Task 2.3).

`install_version.sh` and `upgrade_version.sh` cannot import the daemon, so the
merge reaches them as a subcommand. The exit code is the whole contract: the
shell has to be able to tell "merged fine" from "I refused, keep going and tell
the human", and those must NOT collapse into the usual 0/1 — a 1 in these
scripts means abort, and aborting the fast path leaves new forwarders with old
settings and no snapshot to roll back to.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_settings_merge
from claude_code_hooks_daemon.install.settings_merge import ESCALATION_EXIT_CODE
from claude_code_hooks_daemon.utils.hook_registration import (
    HOOK_EVENTS_IN_SETTINGS,
    build_hook_registration,
)


def _shipped() -> dict[str, Any]:
    return {
        "hooks": {
            json_key: build_hook_registration(bash_key)
            for json_key, bash_key in HOOK_EVENTS_IN_SETTINGS.items()
        },
        "permissions": {"deny": ["Edit(//tmp/**)"]},
    }


@pytest.fixture
def workspace(tmp_path: Path) -> dict[str, Path]:
    new_default = tmp_path / "new-default.json"
    new_default.write_text(json.dumps(_shipped()), encoding="utf-8")
    return {"client": tmp_path / "settings.json", "new_default": new_default}


def _args(workspace: dict[str, Path], **overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "client": str(workspace["client"]),
        "new_default": str(workspace["new_default"]),
        "old_default": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestTheExitCodeTellsTheShellWhatHappened:
    def test_a_successful_merge_exits_zero(
        self, workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        workspace["client"].write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        assert cmd_settings_merge(_args(workspace)) == 0

    def test_nothing_to_do_exits_zero(
        self, workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        workspace["client"].write_text(json.dumps(_shipped()), encoding="utf-8")
        assert cmd_settings_merge(_args(workspace)) == 0

    def test_an_escalation_has_its_own_code_not_the_generic_failure(
        self, workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """1 means abort to these scripts; an escalation must not abort them."""
        workspace["client"].write_text("{ broken", encoding="utf-8")
        assert cmd_settings_merge(_args(workspace)) == ESCALATION_EXIT_CODE
        assert ESCALATION_EXIT_CODE != 1

    def test_an_unreadable_daemon_source_also_escalates_rather_than_aborting(
        self, workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        workspace["new_default"].write_text("not json", encoding="utf-8")
        workspace["client"].write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        assert cmd_settings_merge(_args(workspace)) == ESCALATION_EXIT_CODE


class TestWhatItPrints:
    def test_an_escalation_names_both_files(
        self, workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        workspace["client"].write_text("{ broken", encoding="utf-8")
        cmd_settings_merge(_args(workspace))
        captured = capsys.readouterr()
        assert str(workspace["client"]) in captured.out + captured.err

    def test_a_quiet_run_says_nothing_alarming(
        self, workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Narrating every upgrade is how a warning gets trained away."""
        workspace["client"].write_text(json.dumps(_shipped()), encoding="utf-8")
        cmd_settings_merge(_args(workspace))
        assert "WARNING" not in capsys.readouterr().out.upper()

    def test_a_merge_reports_what_it_changed(
        self, workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        workspace["client"].write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        cmd_settings_merge(_args(workspace))
        assert "PreToolUse" in capsys.readouterr().out


class TestTheBaselineIsOptional:
    def test_an_absent_old_default_argument_is_fine(
        self, workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        workspace["client"].write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        assert cmd_settings_merge(_args(workspace, old_default=None)) == 0

    def test_an_empty_string_is_treated_as_absent(
        self, workspace: dict[str, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Shell passes "" when the handover captured nothing."""
        workspace["client"].write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        assert cmd_settings_merge(_args(workspace, old_default="")) == 0
