"""`hooks-daemon branch-sweep` (Plan 00558 Task 2.2).

The report text and JSON shape are pinned in ``tests/unit/core/test_branch_sweep.py``;
these tests cover the verb: argument parsing, the config it reads (the cap and
its legacy fallback), the exit codes and the output streams.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.branch_cleanup import CleanupReport
from claude_code_hooks_daemon.core.branch_inventory import BranchInventoryError
from claude_code_hooks_daemon.core.branch_sweep import JSON_RECORD_KEYS
from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_branch_sweep

_BUILD = "claude_code_hooks_daemon.core.branch_inventory.build_inventory"
_CLEAN = "claude_code_hooks_daemon.core.branch_cleanup.clean_sweep"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "hooks-daemon").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "remote", "add", "origin", str(tmp_path / "none.git"))
    (tmp_path / "f").write_text("f")
    _git(tmp_path, "add", "f")
    _git(tmp_path, "commit", "-q", "-m", "base")
    for name in ("done", "users/me"):
        _git(tmp_path, "branch", name)
    _git(tmp_path, "checkout", "-q", "-b", "work")
    (tmp_path / "w").write_text("w")
    _git(tmp_path, "add", "w")
    _git(tmp_path, "commit", "-q", "-m", "work")
    _git(tmp_path, "checkout", "-q", "main")
    return tmp_path


def _config(project: Path, yaml_body: str) -> None:
    (project / ".claude" / "hooks-daemon.yaml").write_text(f'version: "2.0"\n{yaml_body}')


def _args(
    project: Path,
    *,
    as_json: bool = False,
    show_all: bool = False,
    clean: bool = False,
    dry_run: bool = False,
    remote: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=project,
        json=as_json,
        all=show_all,
        clean=clean,
        dry_run=dry_run,
        remote=remote,
    )


def _heads(project: Path) -> set[str]:
    out = subprocess.run(
        ["git", "-C", str(project), "for-each-ref", "--format=%(refname:short)", "refs/heads"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return set(out.split())


class TestClean:
    def test_dry_run_deletes_nothing(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_branch_sweep(_args(project, clean=True, dry_run=True)) == 0
        assert "would delete done" in capsys.readouterr().out
        assert "done" in _heads(project)

    def test_clean_deletes_behind_a_bundle(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert cmd_branch_sweep(_args(project, clean=True)) == 0
        out = capsys.readouterr().out
        assert "done" not in _heads(project)
        assert "work" in _heads(project)
        assert str(project / "untracked" / "branch-cleanup") in out

    def test_nothing_to_clean_says_so(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cmd_branch_sweep(_args(project, clean=True))
        capsys.readouterr()
        assert cmd_branch_sweep(_args(project, clean=True)) == 0
        assert "Nothing to clean" in capsys.readouterr().out

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"dry_run": True},
            {"clean": True, "as_json": True},
            {"clean": True, "show_all": True},
            {"remote": True},
        ],
    )
    def test_flag_misuse_is_a_usage_error(
        self, project: Path, capsys: pytest.CaptureFixture[str], kwargs: dict[str, bool]
    ) -> None:
        assert cmd_branch_sweep(_args(project, **kwargs)) == 2
        assert "ERROR" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "error", [BranchInventoryError("no refs"), ValueError("no default branch")]
    )
    def test_a_sweep_failure_exits_1(
        self, project: Path, capsys: pytest.CaptureFixture[str], error: Exception
    ) -> None:
        with patch(_CLEAN, side_effect=error):
            assert cmd_branch_sweep(_args(project, clean=True)) == 1
        assert str(error) in capsys.readouterr().err

    def test_remote_is_passed_to_the_sweep(self, project: Path) -> None:
        with patch(_CLEAN, return_value=CleanupReport()) as clean:
            assert cmd_branch_sweep(_args(project, clean=True, remote=True)) == 0
        assert clean.call_args.kwargs["remote"] is True


class TestParser:
    def test_flags_default_off(self) -> None:
        args = build_parser().parse_args(["branch-sweep"])
        assert args.json is False
        assert args.all is False
        assert args.func is cmd_branch_sweep

    def test_flags_parse(self) -> None:
        args = build_parser().parse_args(["branch-sweep", "--json", "--all"])
        assert args.json is True
        assert args.all is True

    def test_clean_flags_parse(self) -> None:
        args = build_parser().parse_args(["branch-sweep", "--clean", "--dry-run"])
        assert args.clean is True
        assert args.dry_run is True
        plain = build_parser().parse_args(["branch-sweep"])
        assert (plain.clean, plain.dry_run, plain.remote) == (False, False, False)
        remote = build_parser().parse_args(["branch-sweep", "--clean", "--remote"])
        assert remote.remote is True

    def test_help_documents_the_json_keys(self) -> None:
        parser = build_parser()
        sub = next(
            action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
        )
        epilog = sub.choices["branch-sweep"].epilog or ""
        for key in JSON_RECORD_KEYS:
            assert key in epilog


class TestReport:
    def test_text_report(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert cmd_branch_sweep(_args(project)) == 0
        out = capsys.readouterr().out
        assert "bin/hooks-daemon delete-branch done" in out
        assert "work" in out
        assert "users/me" in out  # not exempt: no branches: block
        # done and users/me share a tip, so they count once.
        assert "Open work: 2 of 10 (branches.wip.cap)" in out

    def test_exempt_shown_only_with_all(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _config(project, "branches:\n  exempt: ['users/*']\n")
        cmd_branch_sweep(_args(project))
        assert "users/me" not in capsys.readouterr().out
        cmd_branch_sweep(_args(project, show_all=True))
        assert "users/me" in capsys.readouterr().out

    def test_json_report(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert cmd_branch_sweep(_args(project, as_json=True)) == 0
        document = json.loads(capsys.readouterr().out)
        assert document["open_work"] == 2
        names = {record["name"] for record in document["branches"]}
        assert names == {"main", "done", "users/me", "work"}
        assert all(tuple(record) == JSON_RECORD_KEYS for record in document["branches"])

    def test_explicit_cap(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _config(project, "branches:\n  wip:\n    cap: 2\n")
        cmd_branch_sweep(_args(project))
        assert "Open work: 2 of 2" in capsys.readouterr().out

    def test_legacy_cap_through_the_alias(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _config(
            project,
            "handlers:\n  session_start:\n    branch_count_advisor:\n"
            "      options:\n        max_open_branches: 4\n",
        )
        cmd_branch_sweep(_args(project))
        out = capsys.readouterr().out
        assert "Open work: 2 of 4" in out
        assert "Deprecated" in out


class TestExitCodes:
    def test_inventory_failure_exits_1(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch(_BUILD, side_effect=BranchInventoryError("not a git repository")):
            assert cmd_branch_sweep(_args(project)) == 1
        assert "not a git repository" in capsys.readouterr().err

    def test_not_a_git_repository_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / ".claude" / "hooks-daemon").mkdir(parents=True)
        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            assert cmd_branch_sweep(_args(tmp_path)) == 1
        assert "ERROR" in capsys.readouterr().err
