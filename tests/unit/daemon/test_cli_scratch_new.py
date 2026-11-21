"""`hooks-daemon scratch new` (Plan 00627 Task 4.2).

The entry and manifest mechanics are pinned in ``tests/unit/core/test_scratch_session.py``;
these tests cover the verb: the session id from the environment, the checkout it
resolves, the TTL bound from config, the printed path and every refusal.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.support.scratch_tree import build_git_project, git

from claude_code_hooks_daemon.core.scratch_session import MANIFEST_NAME, find_session_dir
from claude_code_hooks_daemon.daemon.cli import build_parser, cmd_scratch_new

_SID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_NOW = datetime(2026, 11, 21, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    project = build_git_project(tmp_path).project
    (project / ".claude" / "hooks-daemon").mkdir(parents=True)
    return project


def _args(
    project: Path,
    name: str = "probe",
    *,
    purpose: str | None = "try a thing",
    plan: str | None = None,
    ttl_hours: int | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=project, name=name, purpose=purpose, plan=plan, ttl_hours=ttl_hours
    )


def _run(args: argparse.Namespace, *, cwd: Path, environ: dict[str, str] | None = None) -> int:
    env = {"CLAUDE_CODE_SESSION_ID": _SID} if environ is None else environ
    return cmd_scratch_new(args, environ=env, cwd=cwd, now=lambda: _NOW)


class TestParser:
    def test_scratch_new_parses(self) -> None:
        args = build_parser().parse_args(
            ["scratch", "new", "probe", "--purpose", "p", "--plan", "00627", "--ttl-hours", "48"]
        )
        assert args.func is cmd_scratch_new
        assert (args.name, args.purpose, args.plan, args.ttl_hours) == ("probe", "p", "00627", 48)

    def test_defaults(self) -> None:
        args = build_parser().parse_args(["scratch", "new", "probe"])
        assert (args.purpose, args.plan, args.ttl_hours) == (None, None, None)


class TestCreates:
    def test_prints_only_the_path_and_records_the_entry(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(_args(project, plan="00627", ttl_hours=48), cwd=project) == 0
        out = capsys.readouterr().out.strip()
        session = find_session_dir(project / "untracked" / "scratch", _SID)
        assert session is not None
        assert out == str(session / "probe")
        assert (session / "probe").is_dir()
        record = json.loads((session / MANIFEST_NAME).read_text())["entries"]["probe"]
        assert record == {
            "born": "2026-11-21T10:00:00Z",
            "purpose": "try a thing",
            "plan": "00627",
            "ttl_hours": 48,
        }

    def test_reuses_the_session_directory(self, project: Path) -> None:
        assert _run(_args(project, "one"), cwd=project) == 0
        assert _run(_args(project, "two"), cwd=project) == 0
        listing = [p.name for p in (project / "untracked" / "scratch").iterdir()]
        assert len([n for n in listing if n.startswith("s-")]) == 1

    def test_linked_worktree_mirrors_the_main_checkout_name(self, project: Path) -> None:
        assert _run(_args(project, "main-entry"), cwd=project) == 0
        worktree = project.parent / "wt"
        git(project, "worktree", "add", "-q", "-b", "wt", str(worktree))
        assert _run(_args(project, "wt-entry"), cwd=worktree / "src") == 0
        main_dir = find_session_dir(project / "untracked" / "scratch", _SID)
        wt_dir = find_session_dir(worktree / "untracked" / "scratch", _SID)
        assert main_dir is not None and wt_dir is not None
        assert wt_dir.name == main_dir.name
        assert (wt_dir / "wt-entry").is_dir()
        assert not (main_dir / "wt-entry").exists()

    def test_cwd_outside_the_project_uses_the_project_root(
        self, project: Path, tmp_path: Path
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        assert _run(_args(project), cwd=elsewhere) == 0
        assert find_session_dir(project / "untracked" / "scratch", _SID) is not None


class TestRefuses:
    @pytest.mark.parametrize("environ", [{}, {"CLAUDE_CODE_SESSION_ID": "../../etc"}])
    def test_missing_or_invalid_session_id(
        self, project: Path, environ: dict[str, str], capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _run(_args(project), cwd=project, environ=environ) == 1
        assert "session id" in capsys.readouterr().err
        assert not any((project / "untracked" / "scratch").glob("s-*"))

    def test_ttl_above_the_bound(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert _run(_args(project, ttl_hours=73), cwd=project) == 1
        assert "between 1 and 72" in capsys.readouterr().err

    def test_bad_entry_name(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert _run(_args(project, "../x"), cwd=project) == 1
        assert "entry name" in capsys.readouterr().err

    def test_existing_entry(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert _run(_args(project), cwd=project) == 0
        assert _run(_args(project), cwd=project) == 1
        assert "already exists" in capsys.readouterr().err

    def test_malformed_root_ttl(self, project: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (project / ".claude" / "hooks-daemon.yaml").write_text(
            "version: '2.0'\nscratch:\n  untracked_ttl:\n    scratch: soon\n"
        )
        assert _run(_args(project, ttl_hours=10), cwd=project) == 1
        assert "scratch.untracked_ttl.scratch" in capsys.readouterr().err

    def test_never_cleared_root_bounds_by_max_ttl(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (project / ".claude" / "hooks-daemon.yaml").write_text(
            "version: '2.0'\nscratch:\n  untracked_ttl:\n    scratch: '*'\n"
        )
        assert _run(_args(project, ttl_hours=73), cwd=project) == 1
        assert "between 1 and 72" in capsys.readouterr().err
