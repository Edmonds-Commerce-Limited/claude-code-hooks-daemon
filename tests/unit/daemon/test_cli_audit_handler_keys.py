"""Tests for the audit-handler-keys CLI command (Plan 00362 Task 1.2).

Covers the argparse-facing wrapper: text/json output, the tri-state exit
contract (0 clean / 1 findings / 2 operational error), and the
``--migrated-from`` summary the upgrade script reads.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest
import yaml

from claude_code_hooks_daemon.daemon.cli import cmd_audit_handler_keys, main

_CLEAN_EXIT = 0
_FINDINGS_EXIT = 1
_ERROR_EXIT = 2


def _write(path: Path, config: dict[str, object]) -> Path:
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {"config": None, "format": "text", "migrated_from": None}
    values.update(overrides)
    return argparse.Namespace(**values)


class TestExitCodes:
    def test_clean_config_exits_zero(self, tmp_path: Path) -> None:
        cfg = _write(tmp_path / "c.yaml", {"handlers": {"stop": {"auto_continue_stop": {}}}})
        assert cmd_audit_handler_keys(_args(config=str(cfg))) == _CLEAN_EXIT

    def test_stale_key_exits_one(self, tmp_path: Path) -> None:
        cfg = _write(tmp_path / "c.yaml", {"handlers": {"stop": {"hedging_language_detector": {}}}})
        assert cmd_audit_handler_keys(_args(config=str(cfg))) == _FINDINGS_EXIT

    def test_missing_config_exits_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_audit_handler_keys(_args(config=str(tmp_path / "nope.yaml"))) == _ERROR_EXIT
        assert "ERROR" in capsys.readouterr().err


class TestOutput:
    def test_text_names_the_new_home(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cfg = _write(tmp_path / "c.yaml", {"handlers": {"stop": {"hedging_language_detector": {}}}})
        cmd_audit_handler_keys(_args(config=str(cfg)))
        assert "pseudo_events.nitpick.handlers.hedging_language" in capsys.readouterr().out

    def test_json_carries_findings_and_applied_migrations(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        backup = _write(
            tmp_path / "c.yaml.backup", {"handlers": {"stop": {"hedging_language_detector": {}}}}
        )
        cfg = _write(
            tmp_path / "c.yaml",
            {
                "handlers": {"stop": {}},
                "pseudo_events": {"nitpick": {"handlers": {"hedging_language": {}}}},
            },
        )
        rc = cmd_audit_handler_keys(
            _args(config=str(cfg), format="json", migrated_from=str(backup))
        )
        assert rc == _CLEAN_EXIT
        data = json.loads(capsys.readouterr().out)
        assert data["findings"] == []
        assert [m["summary"] for m in data["applied_migrations"]] == [
            "handlers.stop.hedging_language_detector -> "
            "pseudo_events.nitpick.handlers.hedging_language"
        ]


class TestParser:
    def test_verb_is_registered(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _write(tmp_path / "c.yaml", {"handlers": {"stop": {"auto_continue_stop": {}}}})
        monkeypatch.setattr(
            sys, "argv", ["hooks-daemon", "audit-handler-keys", "--config", str(cfg)]
        )
        assert main() == _CLEAN_EXIT
