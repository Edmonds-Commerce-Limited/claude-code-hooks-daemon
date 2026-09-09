"""Plan 00291 Task 2.3 — ``--include-unreleased`` on the two manifest commands.

The flag forces the UNRELEASED staging directory in from a release install
(first-party use, and tests). Without it the loaders decide from the install
stamp, which a release install answers "no" to.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import (
    cmd_check_config_migrations,
    cmd_check_truth_changes,
    main,
)
from claude_code_hooks_daemon.install import config_migrations, truth_changes

_CONFIG_MANIFEST = """\
version: "3.63.0"
date: "UNRELEASED"
breaking: false
config_changes:
  added:
    - key: "handlers.pre_tool_use.staged_handler.enabled"
      description: "Staged for the next release"
      example_yaml: "handlers:\\n  pre_tool_use:\\n    staged_handler:\\n      enabled: true\\n"
  renamed: []
  removed: []
  changed: []
"""


@pytest.fixture
def upgrades_tree(tmp_path: Path) -> Path:
    upgrades = tmp_path / "UPGRADES"
    (upgrades / "config-changes").mkdir(parents=True)
    (upgrades / "truth-changes").mkdir(parents=True)
    staged_cfg = upgrades / "UNRELEASED" / "config-changes"
    staged_truth = upgrades / "UNRELEASED" / "truth-changes"
    staged_cfg.mkdir(parents=True)
    staged_truth.mkdir(parents=True)
    (staged_cfg / "v3.63.0.yaml").write_text(_CONFIG_MANIFEST)
    (staged_truth / "v3.63.0.yaml").write_text(
        "version: '3.63.0'\ntruth_changes:\n  - was: Old truth.\n    now: Staged truth.\n"
    )
    return upgrades


@pytest.fixture(autouse=True)
def release_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_migrations, "is_branch_install", lambda: False)
    monkeypatch.setattr(truth_changes, "is_branch_install", lambda: False)


class TestCheckConfigMigrationsFlag:
    def _args(self, upgrades: Path, config: Path, **overrides: object) -> argparse.Namespace:
        defaults: dict[str, object] = {
            "from_version": "3.62.0",
            "to_version": "3.63.0",
            "config": str(config),
            "format": "json",
            "manifests_dir": str(upgrades / "config-changes"),
            "include_unreleased": False,
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_flag_surfaces_the_staged_option(
        self, upgrades_tree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        config.write_text("version: '1.0'\nhandlers:\n  pre_tool_use: {}\n")
        rc = cmd_check_config_migrations(self._args(upgrades_tree, config, include_unreleased=True))
        assert rc == 1
        payload = json.loads(capsys.readouterr().out)
        assert [s["key"] for s in payload["suggestions"]] == [
            "handlers.pre_tool_use.staged_handler.enabled"
        ]

    def test_without_the_flag_a_release_install_sees_nothing(
        self, upgrades_tree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        config.write_text("version: '1.0'\nhandlers:\n  pre_tool_use: {}\n")
        rc = cmd_check_config_migrations(self._args(upgrades_tree, config))
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["suggestions"] == []

    def test_argparse_wires_the_flag(
        self, upgrades_tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config = tmp_path / "hooks-daemon.yaml"
        config.write_text("version: '1.0'\nhandlers:\n  pre_tool_use: {}\n")
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "claude-hooks-daemon",
                "check-config-migrations",
                "--from",
                "3.62.0",
                "--to",
                "3.63.0",
                "--config",
                str(config),
                "--manifests-dir",
                str(upgrades_tree / "config-changes"),
                "--include-unreleased",
                "--format",
                "json",
            ],
        )
        assert main() == 1


class TestCheckTruthChangesFlag:
    def _args(self, upgrades: Path, **overrides: object) -> argparse.Namespace:
        defaults: dict[str, object] = {
            "from_version": "3.62.0",
            "to_version": "3.63.0",
            "format": "json",
            "truth_changes_dir": str(upgrades / "truth-changes"),
            "include_unreleased": False,
        }
        defaults.update(overrides)
        return argparse.Namespace(**defaults)

    def test_flag_surfaces_the_staged_truth(
        self, upgrades_tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = cmd_check_truth_changes(self._args(upgrades_tree, include_unreleased=True))
        assert rc == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["changes"][0]["now"] == "Staged truth."

    def test_without_the_flag_a_release_install_sees_nothing(
        self, upgrades_tree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = cmd_check_truth_changes(self._args(upgrades_tree))
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["has_changes"] is False

    def test_argparse_wires_the_flag(
        self, upgrades_tree: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "claude-hooks-daemon",
                "check-truth-changes",
                "--from",
                "3.62.0",
                "--to",
                "3.63.0",
                "--truth-changes-dir",
                str(upgrades_tree / "truth-changes"),
                "--include-unreleased",
                "--format",
                "json",
            ],
        )
        assert main() == 1
