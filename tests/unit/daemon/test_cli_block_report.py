"""Tests for the `hooks-daemon block-report` CLI command (Plan 00116 Task 2b.1)."""

import argparse
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon.cli import cmd_block_report
from claude_code_hooks_daemon.utils.claude_config import claude_project_dir


def _args(project_root: Path, transcripts_dir: Path, **overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "project_root": str(project_root),
        "transcripts_dir": str(transcripts_dir),
        "json_output": False,
        "no_write": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _deny_line(session_id: str, reason: str) -> str:
    return json.dumps(
        {
            "type": "user",
            "sessionId": session_id,
            "timestamp": "2026-08-30T12:00:00.000Z",
            "toolDenialKind": "permission-rule",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "content": reason,
                        "is_error": True,
                        "tool_use_id": "toolu_1",
                    }
                ],
            },
        }
    )


@pytest.fixture()
def project(tmp_path: Path) -> tuple[Path, Path]:
    """A minimal project root plus a transcripts dir with one session."""
    root = tmp_path / "proj"
    (root / ".claude").mkdir(parents=True)
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / "11111111-1111-1111-1111-111111111111.jsonl").write_text(
        "\n".join(
            [
                _deny_line(
                    "s1",
                    "BLOCKED: sed is forbidden. Use Edit tool (or parallel Haiku agents "
                    "for bulk).\n\nBLOCKED command: echo hi",
                ),
                _deny_line(
                    "s1",
                    "BLOCKED: sed is forbidden. Use Edit tool (or parallel Haiku agents "
                    "for bulk).\n\nBLOCKED command: echo bye",
                ),
            ]
        )
    )
    return root, transcripts


def _init_git_repo(root: Path) -> None:
    """Make ``root`` a real git repo with a remote origin.

    ``ProjectContext.initialize`` FAIL-FASTs unless it can resolve a git
    toplevel and a remote ``origin`` URL — both read from local git
    metadata only, no network access required.
    """
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:example/example.git"],
        cwd=root,
        check=True,
    )


@pytest.fixture()
def git_project(tmp_path: Path) -> tuple[Path, Path]:
    """A project root that is a real git repo, plus an empty transcripts dir.

    Distinct from the ``project`` fixture above: initialising
    ``ProjectContext`` (Plan 00430) FAIL-FASTs on a non-git directory, so
    the attribution regression test needs a project that can actually be
    initialised.
    """
    root = tmp_path / "proj"
    (root / ".claude").mkdir(parents=True)
    (root / ".claude" / "hooks-daemon.yaml").write_text("")
    _init_git_repo(root)
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    return root, transcripts


class TestCmdBlockReport:
    def test_prints_markdown_and_writes_reports(
        self, project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, transcripts = project
        exit_code = cmd_block_report(_args(root, transcripts))
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "| Handler" in out
        reports_dir = root / ".claude" / "hooks-daemon" / "untracked" / "reports"
        assert (reports_dir / "block-report.md").is_file()
        payload = json.loads((reports_dir / "block-report.json").read_text())
        handlers = {row["handler"]: row for row in payload["rows"]}
        assert handlers["sed_blocker"]["total_blocks"] == 2

    def test_reads_promotion_config_thresholds(
        self, project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, transcripts = project
        (root / ".claude" / "hooks-daemon.yaml").write_text(
            "claude_md:\n  promotion:\n    min_blocks: 1\n    min_sessions: 1\n"
        )
        assert cmd_block_report(_args(root, transcripts)) == 0
        reports_dir = root / ".claude" / "hooks-daemon" / "untracked" / "reports"
        payload = json.loads((reports_dir / "block-report.json").read_text())
        assert payload["min_blocks"] == 1
        row = next(r for r in payload["rows"] if r["handler"] == "sed_blocker")
        assert row["recommended_promote"] is True

    def test_json_output_prints_machine_readable(
        self, project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, transcripts = project
        assert cmd_block_report(_args(root, transcripts, json_output=True)) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["sessions_scanned"] == 1

    def test_no_write_skips_report_files(
        self, project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, transcripts = project
        assert cmd_block_report(_args(root, transcripts, no_write=True)) == 0
        assert not (root / ".claude" / "hooks-daemon" / "untracked" / "reports").exists()

    def test_missing_transcripts_dir_still_reports(
        self, project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A fresh project has no transcripts yet — that is a report saying
        so, not an error."""
        root, _ = project
        exit_code = cmd_block_report(_args(root, root / "nope", no_write=True))
        assert exit_code == 0
        assert "0 transcript" in capsys.readouterr().out

    def test_a_missing_derived_directory_is_named_on_stderr(
        self,
        project: tuple[Path, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """00466 N27: an absent derived directory is named, not silently empty."""
        root, _ = project
        config = tmp_path / "hermetic-claude-config"
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
        args = _args(root, root, no_write=True)
        args.transcripts_dir = None
        assert cmd_block_report(args) == 0
        err = capsys.readouterr().err
        assert str(claude_project_dir(root, config_dir=config)) in err


class TestCmdBlockReportAttributesProjectContextReadingHandlers:
    """Plan 00430: five handlers (``markdown_organization`` among them) read
    ``ProjectContext.project_root()`` in ``__init__`` and cannot be
    constructed by handler discovery until it is initialised. Before the
    fix, ``cmd_block_report`` never initialises it, so these handlers'
    denies are silently dropped into ``unattributed_denies`` instead of
    being attributed to their handler."""

    def test_attributes_a_deny_from_a_projectcontext_reading_handler(
        self,
        git_project: tuple[Path, Path],
        capsys: pytest.CaptureFixture[str],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        root, transcripts = git_project
        (transcripts / "11111111-1111-1111-1111-111111111111.jsonl").write_text(
            _deny_line(
                "s1",
                "BLOCKED [R-MARKDOWN-WRONG-LOCATION]: a new `.md` file written "
                "to an unrecognised location",
            )
        )

        with caplog.at_level(logging.ERROR):
            exit_code = cmd_block_report(_args(root, transcripts, no_write=True, json_output=True))

        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        handlers = {row["handler"]: row for row in payload["rows"]}
        assert (
            "markdown_organization" in handlers
        ), f"markdown_organization missing from attributed rows: {handlers.keys()}"
        assert handlers["markdown_organization"]["total_blocks"] == 1
        assert payload["unattributed_denies"] == 0
        inspect_failures = [
            record
            for record in caplog.records
            if "Failed to inspect handler" in record.getMessage()
        ]
        assert (
            inspect_failures == []
        ), f"handler discovery failed to construct handler(s): {inspect_failures}"


class TestCmdBlockReportNoConfigFileStillReports:
    """Plan 00430 Task 1.3: when no config file can be found, ProjectContext
    initialisation must be skipped quietly (as ``_init_project_context_for_explain``
    already does for its other five callers) rather than erroring — the report
    stays exactly as degraded as it is today."""

    def test_missing_config_file_still_produces_a_report(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = tmp_path / "proj"
        root.mkdir()
        # Deliberately no .claude/hooks-daemon.yaml and not a git repo.
        transcripts = tmp_path / "transcripts"
        transcripts.mkdir()

        exit_code = cmd_block_report(_args(root, transcripts, no_write=True))

        assert exit_code == 0
        assert not ProjectContext.is_initialized()
        assert "0 transcript" in capsys.readouterr().out


class TestCmdBlockReportDoesNotPoisonTheRuleIndexAcrossRuns:
    """Plan 00430 Task 1.4: ``_rule_id_to_config_key`` in fingerprints.py
    guards against memoising a PARTIAL index (built while ``ProjectContext``
    is uninitialised) for the rest of the process. This asserts that
    guarantee end-to-end through ``cmd_block_report`` itself: a run against
    an un-initialisable project (no config found) followed by a run against
    a real git project must still attribute correctly on the second run —
    proving the first, degraded run's partial index was never cached."""

    def test_a_degraded_run_does_not_poison_a_later_correct_run(
        self,
        tmp_path: Path,
        git_project: tuple[Path, Path],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        degraded_root = tmp_path / "no-config-proj"
        degraded_root.mkdir()
        degraded_transcripts = tmp_path / "no-config-transcripts"
        degraded_transcripts.mkdir()
        assert cmd_block_report(_args(degraded_root, degraded_transcripts, no_write=True)) == 0
        capsys.readouterr()
        assert not ProjectContext.is_initialized()

        root, transcripts = git_project
        (transcripts / "11111111-1111-1111-1111-111111111111.jsonl").write_text(
            _deny_line(
                "s1",
                "BLOCKED [R-MARKDOWN-WRONG-LOCATION]: a new `.md` file written "
                "to an unrecognised location",
            )
        )
        exit_code = cmd_block_report(_args(root, transcripts, no_write=True, json_output=True))
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        handlers = {row["handler"]: row for row in payload["rows"]}
        assert handlers.get("markdown_organization", {}).get("total_blocks") == 1
        assert payload["unattributed_denies"] == 0
