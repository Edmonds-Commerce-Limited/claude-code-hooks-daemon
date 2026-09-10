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


class TestLintNeverCertifiesWhatItDidNotExamine:
    """Plan 00230.

    ``classify()`` needs an absolute path, and the CLI used to hand it
    whatever the caller typed. A RELATIVE target — the form the shipped
    skill documents — therefore classified as ``OUTSIDE``, every EDIT check
    no-matched, and the run printed a clean bill of health for a file it
    never parsed. The live tree had two BLOCK-level violations sitting
    behind that false clean.

    The invariant these tests pin: a lint run reports "clean" only for a
    file it actually examined. Anything else is an error, never a pass.
    """

    _BAD_STATUS_DOC = "# Plan 00001: first\n\n**Status**: Shipped v3.23.0 (all done)\n"

    def test_relative_target_reports_what_the_absolute_target_reports(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The documented relative invocation must not diverge from the absolute one."""
        root = _scaffold(tmp_path)
        (root / "CLAUDE/Plan/00001-first/PLAN.md").write_text(self._BAD_STATUS_DOC)
        relative = Path("CLAUDE/Plan/00001-first/PLAN.md")

        absolute_exit = cmd_plan_qa(_args(root, lint=root / relative))
        monkeypatch.chdir(root)
        relative_exit = cmd_plan_qa(_args(root, lint=relative))

        assert absolute_exit == 1, "premise: the absolute form must find the violation"
        assert relative_exit == absolute_exit

    def test_relative_target_names_the_violated_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Exit code parity is not enough — the finding itself must be reported."""
        root = _scaffold(tmp_path)
        (root / "CLAUDE/Plan/00001-first/PLAN.md").write_text(self._BAD_STATUS_DOC)
        monkeypatch.chdir(root)

        cmd_plan_qa(_args(root, lint=Path("CLAUDE/Plan/00001-first/PLAN.md")))

        assert "status-enum-and-date" in capsys.readouterr().out

    def test_target_outside_the_plan_tree_is_an_error_not_a_pass(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A file no check can apply to must never exit 0 — CI reads the exit code."""
        root = _scaffold(tmp_path)
        outsider = root / "README.md"
        outsider.write_text("# not a plan document\n")

        assert cmd_plan_qa(_args(root, lint=outsider)) == 2
        assert "not a plan document" in capsys.readouterr().err.lower()

    def test_clean_single_file_lint_does_not_claim_the_tree_is_clean(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Linting ONE file says nothing about the other plans on disk."""
        root = _scaffold(tmp_path)

        assert cmd_plan_qa(_args(root, lint=root / "CLAUDE/Plan/00001-first/PLAN.md")) == 0

        assert "plan tree is clean" not in capsys.readouterr().out.lower()


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


class TestProjectExcludePaths:
    """Plan 00362 Task 2.9: the CLI reads ``daemon.exclude_paths`` from config."""

    def test_sweep_skips_an_excluded_plan_folder(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        rogue = root / "CLAUDE" / "Plan" / "00002-rogue"
        rogue.mkdir()
        (rogue / "PLAN.md").write_text("# Plan 00002: rogue\n\n**Status**: Complete\n")
        assert cmd_plan_qa(_args(root, sweep=True)) == 1

        (root / ".claude" / "hooks-daemon.yaml").write_text(
            _CONFIG_ENABLED + "daemon:\n  exclude_paths:\n    - 'CLAUDE/Plan/00002-rogue/**'\n"
        )
        assert cmd_plan_qa(_args(root, sweep=True)) == 0

    def test_lint_of_an_excluded_file_reports_clean(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        target = root / "CLAUDE" / "Plan" / "00001-first" / "PLAN.md"
        target.write_text("# Plan 00001: first\n\nno status line\n")
        assert cmd_plan_qa(_args(root, lint=target)) == 1

        (root / ".claude" / "hooks-daemon.yaml").write_text(
            _CONFIG_ENABLED + "daemon:\n  exclude_paths:\n    - 'CLAUDE/Plan/00001-first/**'\n"
        )
        assert cmd_plan_qa(_args(root, lint=target)) == 0


class TestASweepNeverCertifiesATreeItNeverExamined:
    """A missing plan directory is an operational error, not a clean tree.

    ``cmd_plan_qa``'s own docstring already promises "2 on operational errors
    (missing plan directory or lint target)", and the ``--lint`` branch fails
    fast with the reason written out beside it: exiting 0 would certify
    something that was never examined, and the exit code is what CI reads.
    The sweep branch had no such guard — measured live, a scratch directory
    with no plan tree printed "Plan QA: 0 findings — plan tree is clean." and
    exited 0.

    That matters more now than it did: Plan 00373 made the sweep a QA tool, so
    this exit code is a release gate. A sweep that certifies an absent corpus
    is the same defect the whole plan was filed about, one layer down.
    """

    def _rootless(self, tmp_path: Path, config_body: str = _CONFIG_ENABLED) -> Path:
        """A configured git repo with NO plan directory at all."""
        root = tmp_path / "repo"
        (root / ".claude").mkdir(parents=True)
        (root / ".claude" / "hooks-daemon.yaml").write_text(config_body)
        subprocess.run(
            ["git", "init", str(root)],
            capture_output=True,
            check=True,
            timeout=Timeout.GIT_CONTEXT,
        )
        return root

    def test_a_missing_plan_directory_is_operational_not_clean(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = self._rootless(tmp_path)

        exit_code = cmd_plan_qa(_args(root, sweep=True))

        captured = capsys.readouterr()
        assert exit_code == 2
        assert "plan tree is clean" not in captured.out.lower()
        assert "CLAUDE/Plan" in captured.err

    def test_json_mode_does_not_emit_a_clean_empty_array(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`[]` is exactly what a clean sweep prints, so it must not appear here."""
        root = self._rootless(tmp_path)

        exit_code = cmd_plan_qa(_args(root, sweep=True, json_output=True))

        assert exit_code == 2
        assert capsys.readouterr().out.strip() != "[]"

    def test_disabling_the_plan_workflow_is_still_a_legitimate_pass(self, tmp_path: Path) -> None:
        """A project that declares it has no plan tree is not a broken one.

        The guard must discriminate "configured for plans, none present" from
        "explicitly not using plans" — otherwise every client without a plan
        tree gets a red QA run for a corpus they never opted into.
        """
        root = self._rootless(tmp_path, _CONFIG_DISABLED)

        assert cmd_plan_qa(_args(root, sweep=True)) == 0
