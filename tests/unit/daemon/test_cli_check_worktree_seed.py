"""Tests for the check-worktree-seed CLI command (Plan 00267 Phase 5).

Covers the argparse-facing wrapper: text/json output and the tri-state exit
contract (0 clean / 1 drift / 2 operational error). The exit code is the whole
point of the command being scriptable — install and upgrade call the same
command an operator runs by hand, so there is exactly one implementation of
the scan.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from claude_code_hooks_daemon.daemon.cli import cmd_check_worktree_seed
from claude_code_hooks_daemon.install.worktree_seed_report import SEED_CONFIG_KEY

_CLEAN_EXIT = 0
_DRIFT_EXIT = 1
_ERROR_EXIT = 2


def _init_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / ".gitignore").write_text(".env.local\n", encoding="utf-8")
    (root / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)


def _write_config(root: Path, seed: object | None) -> Path:
    """Write a hooks-daemon.yaml, optionally carrying a seed option."""
    config: dict = {"version": "1.0"}
    if seed is not None:
        node: dict = config
        *branches, leaf = SEED_CONFIG_KEY.split(".")
        for part in branches:
            node[part] = {}
            node = node[part]
        node[leaf] = seed

    config_dir = root / ".claude"
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "hooks-daemon.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(root)
    return root


def _args(repo: Path, config: Path | None, output_format: str = "text") -> argparse.Namespace:
    """Mirror what argparse produces: --project-root is declared ``type=Path``."""
    return argparse.Namespace(
        config=str(config) if config else None,
        format=output_format,
        project_root=repo,
    )


class TestCmdCheckWorktreeSeed:
    def test_clean_config_exits_zero(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        config = _write_config(repo, None)

        assert cmd_check_worktree_seed(_args(repo, config)) == _CLEAN_EXIT
        assert "up to date" in capsys.readouterr().out

    def test_unconfigured_candidate_exits_one_and_names_it(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
        config = _write_config(repo, None)

        assert cmd_check_worktree_seed(_args(repo, config)) == _DRIFT_EXIT
        assert ".env.local" in capsys.readouterr().out

    def test_missing_source_exits_one(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        config = _write_config(repo, {"entries": [".env.local"]})

        assert cmd_check_worktree_seed(_args(repo, config)) == _DRIFT_EXIT
        assert "MISSING" in capsys.readouterr().out

    def test_json_output_carries_the_structured_result(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
        config = _write_config(repo, None)

        assert cmd_check_worktree_seed(_args(repo, config, "json")) == _DRIFT_EXIT

        payload = json.loads(capsys.readouterr().out)
        assert payload["has_drift"] is True
        assert payload["seed_key_configured"] is False
        assert payload["unconfigured"] == [{"path": ".env.local", "mode": "symlink"}]
        assert payload["missing"] == []
        assert payload["suggested_yaml"]

    def test_json_output_is_clean_when_config_is_current(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
        config = _write_config(repo, {"entries": [".env.local"]})

        assert cmd_check_worktree_seed(_args(repo, config, "json")) == _CLEAN_EXIT

        payload = json.loads(capsys.readouterr().out)
        assert payload["has_drift"] is False
        assert payload["configured"] == [{"path": ".env.local", "mode": "symlink"}]

    def test_absent_config_file_exits_two(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_check_worktree_seed(_args(repo, repo / "nope.yaml")) == _ERROR_EXIT
        assert "ERROR" in capsys.readouterr().err

    def test_config_that_is_not_a_mapping_exits_two(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = repo / "bad.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")

        assert cmd_check_worktree_seed(_args(repo, path)) == _ERROR_EXIT
        assert "ERROR" in capsys.readouterr().err

    def test_config_path_defaults_to_the_project_root(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
        _write_config(repo, None)

        assert cmd_check_worktree_seed(_args(repo, None)) == _DRIFT_EXIT
        assert ".env.local" in capsys.readouterr().out

    def test_nothing_is_written_to_the_config(self, repo: Path) -> None:
        """The command reports. The project owns its config, and a PyYAML
        round-trip would strip every comment out of it."""
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
        config = _write_config(repo, None)
        before = config.read_text(encoding="utf-8")

        cmd_check_worktree_seed(_args(repo, config))

        assert config.read_text(encoding="utf-8") == before
