"""Tests for the ``plan-qa`` CLI subcommand (Plan 00144, Task 2.1)."""

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.daemon.cli import cmd_plan_qa

_CONFIG_ENABLED = "plan_workflow:\n  enabled: true\n"
_CONFIG_DISABLED = "plan_workflow:\n  enabled: false\n"


def _args(
    project_root: Path,
    sweep: bool = False,
    check_staged: bool = False,
    lint: Path | None = None,
    json_output: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=project_root,
        sweep=sweep,
        check_staged=check_staged,
        lint=lint,
        json_output=json_output,
    )


def _scaffold(tmp_path: Path, config_body: str = _CONFIG_ENABLED) -> Path:
    """Git repo + plan dir with one clean, indexed, in-progress plan."""
    root = tmp_path / "repo"
    plan_dir = root / "CLAUDE" / "Plan"
    (plan_dir / "Completed").mkdir(parents=True)
    (plan_dir / "Cancelled").mkdir()
    (root / ".claude").mkdir()
    (root / ".claude" / "hooks-daemon.yaml").write_text(config_body)
    folder = plan_dir / "00001-first"
    folder.mkdir()
    (folder / "PLAN.md").write_text(
        "# Plan 00001: first\n\n**Status**: In Progress\n\n- [ ] ⬜ **Task 1.1**: x\n"
    )
    # A JOURNAL/ dir keeps the tree clean under the Plan 00163 journal checks
    # (has_journal → folder-present passes; no dated file → freshness skips).
    (folder / "JOURNAL").mkdir()
    (plan_dir / "README.md").write_text(
        "# Plans Index\n\n## Active Plans\n\n"
        "- [00001: first](00001-first/PLAN.md) - In Progress\n"
    )
    subprocess.run(
        ["git", "init", str(root)],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )
    return root


class TestSweep:
    def test_clean_tree_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        assert cmd_plan_qa(_args(root, sweep=True)) == 0
        assert "0 finding" in capsys.readouterr().out

    def test_drifted_tree_exits_one_and_names_checks(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        # Terminal plan loitering in root, never indexed.
        rogue = root / "CLAUDE/Plan/00002-rogue"
        rogue.mkdir()
        (rogue / "PLAN.md").write_text("# Plan 00002: rogue\n\n**Status**: Complete\n")

        assert cmd_plan_qa(_args(root, sweep=True)) == 1
        out = capsys.readouterr().out
        assert "location-status-coherence" in out
        assert "row-folder-bijection" in out

    def test_default_action_is_sweep(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        assert cmd_plan_qa(_args(root)) == 0
        assert "0 finding" in capsys.readouterr().out

    def test_json_output_is_parseable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        rogue = root / "CLAUDE/Plan/00002-rogue"
        rogue.mkdir()
        (rogue / "PLAN.md").write_text("# Plan 00002: rogue\n\n**Status**: Complete\n")

        assert cmd_plan_qa(_args(root, sweep=True, json_output=True)) == 1
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload, list)
        entry = payload[0]
        assert {"check_id", "level", "message", "remediation", "path"} <= set(entry)

    def test_missing_plan_dir_exits_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "repo"
        (root / ".claude").mkdir(parents=True)
        (root / ".claude" / "hooks-daemon.yaml").write_text(_CONFIG_ENABLED)
        subprocess.run(
            ["git", "init", str(root)],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )

        assert cmd_plan_qa(_args(root, sweep=True)) == 2
        assert "does not exist" in capsys.readouterr().err.lower()


class TestConfigGating:
    def test_plan_workflow_disabled_exits_zero_with_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path, config_body=_CONFIG_DISABLED)
        assert cmd_plan_qa(_args(root, sweep=True)) == 0
        assert "disabled" in capsys.readouterr().out.lower()

    def test_qa_disabled_exits_zero_with_notice(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(
            tmp_path,
            config_body="plan_workflow:\n  enabled: true\n  qa:\n    enabled: false\n",
        )
        assert cmd_plan_qa(_args(root, sweep=True)) == 0
        assert "disabled" in capsys.readouterr().out.lower()


class TestLint:
    def test_lint_valid_plan_exits_zero(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        target = root / "CLAUDE/Plan/00001-first/PLAN.md"
        assert cmd_plan_qa(_args(root, lint=target)) == 0

    def test_lint_invalid_plan_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        target = root / "CLAUDE/Plan/00001-first/PLAN.md"
        target.write_text("# Plan 00001: first\n\nno status header here\n")

        assert cmd_plan_qa(_args(root, lint=target)) == 1
        assert "status-line-present" in capsys.readouterr().out

    def test_lint_missing_file_exits_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        assert cmd_plan_qa(_args(root, lint=root / "CLAUDE/Plan/00009-x/PLAN.md")) == 2
        assert "does not exist" in capsys.readouterr().err.lower()


class TestCheckStaged:
    def test_staged_terminal_flip_without_move_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        for cmd in (
            ["git", "-C", str(root), "config", "user.email", "t@example.com"],
            ["git", "-C", str(root), "config", "user.name", "T"],
            ["git", "-C", str(root), "add", "-A"],
            ["git", "-C", str(root), "commit", "-m", "initial"],
        ):
            subprocess.run(cmd, capture_output=True, check=True, timeout=Timeout.GIT_CONTEXT)
        plan_md = root / "CLAUDE/Plan/00001-first/PLAN.md"
        plan_md.write_text("# Plan 00001: first\n\n**Status**: Complete\n")
        subprocess.run(
            ["git", "-C", str(root), "add", "-A"],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )

        assert cmd_plan_qa(_args(root, check_staged=True)) == 1
        assert "terminal-state-atomic" in capsys.readouterr().out

    def test_clean_stage_exits_zero(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        assert cmd_plan_qa(_args(root, check_staged=True)) == 0
