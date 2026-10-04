"""Tests for the ``work-queue`` CLI (Plan 00470 Task 3.3).

A coordinator, and the issue-sdlc runbook, write the durable work queue through
this verb at dispatch and completion, so nobody edits JSON by hand.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.utils.work_queue import (
    STATUS_DONE,
    STATUS_RUNNING,
    WORK_QUEUE_FILENAME,
    read_queue,
)


@pytest.fixture(autouse=True)
def _reset_project_context() -> Iterator[None]:
    from claude_code_hooks_daemon.core.project_context import ProjectContext

    yield
    ProjectContext.reset()


@pytest.fixture
def project(tmp_path: Path) -> Iterator[Path]:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "hooks-daemon.yaml").write_text('version: "2.0"\n', encoding="utf-8")
    with patch(
        "claude_code_hooks_daemon.core.project_context.ProjectContext.daemon_untracked_dir",
        return_value=tmp_path / "untracked",
    ):
        yield tmp_path


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    checkout = tmp_path / "wt"
    checkout.mkdir()
    for argv in (
        ["init", "-q"],
        [
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
        ],
    ):
        subprocess.run(["git", "-C", str(checkout), *argv], check=True, capture_output=True)
    return checkout


def _head(checkout: Path) -> str:
    done = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def _run(project: Path, *argv: str) -> int:
    args = cli.build_parser().parse_args(["work-queue", *argv, "--project-root", str(project)])
    return int(args.func(args))


def _queue(project: Path) -> list[object]:
    return list(read_queue(project / "untracked" / WORK_QUEUE_FILENAME))


class TestAdd:
    def test_it_records_the_dispatch_and_reads_the_sha_from_the_worktree(
        self, project: Path, worktree: Path
    ) -> None:
        code = _run(
            project,
            "add", "p470-queue",
            "--worktree", str(worktree),
            "--branch", "worktree-p470-queue",
            "--brief", "Build the queue.",
        )  # fmt: skip
        assert code == 0
        (record,) = read_queue(project / "untracked" / WORK_QUEUE_FILENAME)
        assert record.name == "p470-queue"
        assert record.worktree == str(worktree)
        assert record.last_sha == _head(worktree)
        assert record.status == STATUS_RUNNING

    def test_an_explicit_sha_wins(self, project: Path, worktree: Path) -> None:
        _run(
            project,
            "add", "a",
            "--worktree", str(worktree),
            "--branch", "b",
            "--brief", "x",
            "--sha", "deadbee",
        )  # fmt: skip
        (record,) = read_queue(project / "untracked" / WORK_QUEUE_FILENAME)
        assert record.last_sha == "deadbee"

    def test_a_brief_file_is_stored_as_a_path(self, project: Path, worktree: Path) -> None:
        brief = project / "brief.md"
        brief.write_text("Do the thing.", encoding="utf-8")
        code = _run(
            project,
            "add", "a",
            "--worktree", str(worktree),
            "--branch", "b",
            "--brief-file", str(brief),
        )  # fmt: skip
        assert code == 0
        (record,) = read_queue(project / "untracked" / WORK_QUEUE_FILENAME)
        assert record.brief_file == str(brief)
        assert record.brief == ""

    def test_a_missing_brief_file_is_refused(
        self, project: Path, worktree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = _run(
            project,
            "add", "a",
            "--worktree", str(worktree),
            "--branch", "b",
            "--brief-file", str(project / "nope.md"),
        )  # fmt: skip
        assert code == 1
        assert "nope.md" in capsys.readouterr().err
        assert _queue(project) == []

    def test_a_worktree_that_is_not_a_checkout_needs_an_explicit_sha(
        self, project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        code = _run(project, "add", "a", "--worktree", str(plain), "--branch", "b", "--brief", "x")
        assert code == 1
        assert "--sha" in capsys.readouterr().err
        assert _queue(project) == []

    def test_a_brief_is_required(self, project: Path, worktree: Path) -> None:
        with pytest.raises(SystemExit):
            _run(project, "add", "a", "--worktree", str(worktree), "--branch", "b")


class TestUpdateAndDone:
    def _seed(self, project: Path, worktree: Path) -> None:
        _run(project, "add", "a", "--worktree", str(worktree), "--branch", "b", "--brief", "x")

    def test_update_moves_the_sha(self, project: Path, worktree: Path) -> None:
        self._seed(project, worktree)
        assert _run(project, "update", "a", "--sha", "cafe123") == 0
        (record,) = read_queue(project / "untracked" / WORK_QUEUE_FILENAME)
        assert record.last_sha == "cafe123"
        assert record.status == STATUS_RUNNING

    def test_done_closes_the_record_and_may_carry_the_final_sha(
        self, project: Path, worktree: Path
    ) -> None:
        self._seed(project, worktree)
        assert _run(project, "done", "a", "--sha", "f1na1") == 0
        (record,) = read_queue(project / "untracked" / WORK_QUEUE_FILENAME)
        assert record.status == STATUS_DONE
        assert record.last_sha == "f1na1"

    def test_update_can_abandon(self, project: Path, worktree: Path) -> None:
        self._seed(project, worktree)
        assert _run(project, "update", "a", "--status", "abandoned") == 0

    def test_an_unknown_name_is_an_error_not_a_silent_success(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "done", "ghost") == 1
        assert "ghost" in capsys.readouterr().err


class TestList:
    def test_it_lists_running_records_only_by_default(
        self, project: Path, worktree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for name in ("alive", "finished"):
            _run(project, "add", name, "--worktree", str(worktree), "--branch", "b", "--brief", "x")
        _run(project, "done", "finished")
        capsys.readouterr()
        assert _run(project, "list") == 0
        out = capsys.readouterr().out
        assert "alive" in out
        assert "finished" not in out

    def test_all_includes_closed_records(
        self, project: Path, worktree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _run(
            project, "add", "finished", "--worktree", str(worktree), "--branch", "b", "--brief", "x"
        )
        _run(project, "done", "finished")
        capsys.readouterr()
        _run(project, "list", "--all")
        assert "finished" in capsys.readouterr().out

    def test_json_carries_the_full_brief(
        self, project: Path, worktree: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        brief = "z" * 3000
        _run(project, "add", "a", "--worktree", str(worktree), "--branch", "b", "--brief", brief)
        capsys.readouterr()
        assert _run(project, "list", "--json") == 0
        (entry,) = json.loads(capsys.readouterr().out)
        assert entry["brief"] == brief
        assert entry["name"] == "a"

    def test_an_empty_queue_says_so(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(project, "list") == 0
        assert "no running" in capsys.readouterr().out.lower()

    def test_a_corrupt_queue_is_an_error(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = project / "untracked" / WORK_QUEUE_FILENAME
        path.parent.mkdir()
        path.write_text("{oops", encoding="utf-8")
        assert _run(project, "list") == 1
        assert "unreadable" in capsys.readouterr().err
