"""`hooks-daemon branch-keep` (Plan 00571 Phase 3): arguments, output and exit codes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_branch_keep


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
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
        text=True,
    ).stdout.strip()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "hooks-daemon").mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "remote", "add", "origin", str(tmp_path / "none.git"))
    (tmp_path / "f").write_text("f")
    _git(tmp_path, "add", "f")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "branch", "done")
    _git(tmp_path, "checkout", "-q", "-b", "open")
    (tmp_path / "g").write_text("g")
    _git(tmp_path, "add", "g")
    _git(tmp_path, "commit", "-q", "-m", "open work")
    _git(tmp_path, "checkout", "-q", "main")
    return tmp_path


def _run(project: Path, *argv: str) -> int:
    args = build_parser().parse_args(["--project-root", str(project), "branch-keep", *argv])
    args.project_root = project
    return cmd_branch_keep(args)


def test_keep_writes_note_and_reports_a_failed_push(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(project, "done", "--reason", "audit") == 0
    out = capsys.readouterr().out
    assert "Kept done" in out and "Retry: git push origin refs/notes/hooks-daemon/keep" in out
    tip = _git(project, "rev-parse", "done")
    assert "Kept-Reason: audit" in _git(
        project, "notes", "--ref=refs/notes/hooks-daemon/keep", "show", tip
    )


def test_missing_reason_exits_one(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(project, "done") == 1
    assert "reason" in capsys.readouterr().err


def test_unknown_branch_exits_one(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(project, "nope", "--reason", "x") == 1
    assert "no branch" in capsys.readouterr().err


def test_unmerged_branch_exits_one_and_points_at_park(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(project, "open", "--reason", "x") == 1
    assert "branch-park" in capsys.readouterr().err


_LABELS = Path("untracked/branch-inventory/labels.json")


def _stale_labels(project: Path, names: list[str]) -> None:
    tip = _git(project, "rev-parse", "done")
    labels = {
        name: {"group": "merged", "stale": "true", "local_tip": tip, "remote_tip": None}
        for name in names
    }
    (project / _LABELS).parent.mkdir(parents=True, exist_ok=True)
    (project / _LABELS).write_text(json.dumps(labels), encoding="utf-8")


def _stale_names(project: Path) -> set[str]:
    labels = json.loads((project / _LABELS).read_text(encoding="utf-8"))
    return {name for name, label in labels.items() if label.get("stale")}


def test_keep_clears_the_stale_label_of_every_name_at_the_kept_tip(project: Path) -> None:
    """Plan 00594: a keep is a note on the tip, so it keeps a same-tip sibling too;
    the creation guard must stop calling that sibling stale."""
    _git(project, "branch", "done-twin", "done")
    _stale_labels(project, ["done", "done-twin"])

    assert _run(project, "done", "--reason", "audit") == 0

    assert _stale_names(project) == set()


def test_a_same_reason_rekeep_still_clears_the_named_label(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The tip is kept, so the guard must agree even when the re-keep is refused."""
    _git(project, "branch", "done-twin", "done")
    assert _run(project, "done", "--reason", "w") == 0
    _stale_labels(project, ["done-twin"])
    capsys.readouterr()

    assert _run(project, "done-twin", "--reason", "w") == 2

    assert _stale_names(project) == set()


def test_same_reason_exits_two(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(project, "done", "--reason", "w") == 0
    capsys.readouterr()
    assert _run(project, "done", "--reason", "w") == 2
    assert "new reason" in capsys.readouterr().err
