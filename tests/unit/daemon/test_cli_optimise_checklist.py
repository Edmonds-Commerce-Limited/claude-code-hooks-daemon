"""``hooks-daemon optimise-checklist`` prints the registry-derived checklist (Plan 00330)."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_optimise_checklist

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _args(**overrides: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "config": str(_REPO_ROOT / ".claude" / "hooks-daemon.yaml"),
        "project_root": str(_REPO_ROOT),
        "format": "text",
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_text_report_covers_every_area(capsys: pytest.CaptureFixture[str]) -> None:
    assert cmd_optimise_checklist(_args()) == 0
    out = capsys.readouterr().out
    assert "Safety" in out
    assert "Other guards" in out
    assert "relevant handlers enabled" in out


def test_json_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert cmd_optimise_checklist(_args(format="json")) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["items"]
    assert "relevant" in data["summary"]


def test_uncovered_worktree_root_is_recommended(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "untracked" / "worktrees" / "wt-one").mkdir(parents=True)
    assert cmd_optimise_checklist(_args(project_root=str(tmp_path))) == 0
    out = capsys.readouterr().out
    assert "**/untracked/worktrees/*/CLAUDE.md" in out
    assert "claudeMdExcludes" in out


def test_no_worktree_root_adds_no_claudemd_recommendation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cmd_optimise_checklist(_args(project_root=str(tmp_path))) == 0
    assert "claudeMdExcludes" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("team_seat_block", "expected"),
    [("", False), ("team_seat:\n  teams_in_use: true\n", True)],
)
def test_team_handlers_follow_the_declared_teams(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], team_seat_block: str, expected: bool
) -> None:
    """Plan 00474 R5: the review builds handlers bare, so the context carries the key."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://example.invalid/r.git"],
        cwd=tmp_path,
        check=True,
    )
    config = tmp_path / ".claude" / "hooks-daemon.yaml"
    config.parent.mkdir()
    config.write_text(f"version: '2.0'\n{team_seat_block}")
    assert (
        cmd_optimise_checklist(_args(config=str(config), project_root=str(tmp_path), format="json"))
        == 0
    )
    items = json.loads(capsys.readouterr().out)["items"]
    lane = [item for item in items if item["config_key"] == "host_seat_lane_guard"]
    assert lane
    assert lane[0]["applicable"] is expected


def test_missing_config_is_an_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cmd_optimise_checklist(_args(config=str(tmp_path / "absent.yaml"))) == 2
    assert "not found" in capsys.readouterr().err.lower()
