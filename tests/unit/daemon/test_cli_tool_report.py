"""Tests for the `hooks-daemon tool-report` CLI command (Plan 00293 Task 2.3)."""

import argparse
import json
from pathlib import Path
from typing import Any

import pytest
from tests.claude_plugin_fixture import install_fake_plugin

from claude_code_hooks_daemon.daemon.cli import cmd_tool_report
from claude_code_hooks_daemon.utils.claude_config import claude_project_dir


def _args(project_root: Path, transcripts_dir: Path | None, **overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "project_root": str(project_root),
        "transcripts_dir": None if transcripts_dir is None else str(transcripts_dir),
        "json_output": False,
        "no_write": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _tool_use_line(tool_name: str) -> str:
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "toolu_0", "name": tool_name, "input": {}}],
            },
        }
    )


@pytest.fixture(autouse=True)
def claude_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The plugin section reads the Claude config dir (Plan 00468 G15); never
    the real one."""
    config = tmp_path / "hermetic-claude-config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    return config


@pytest.fixture()
def project(tmp_path: Path) -> tuple[Path, Path]:
    """A minimal project root plus a transcripts dir with one session."""
    root = tmp_path / "proj"
    (root / ".claude").mkdir(parents=True)
    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / "11111111-1111-1111-1111-111111111111.jsonl").write_text(
        "\n".join([_tool_use_line("Bash"), _tool_use_line("Bash"), _tool_use_line("Read")])
    )
    return root, transcripts


class TestCmdToolReport:
    def test_prints_markdown_and_writes_reports(
        self, project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, transcripts = project
        exit_code = cmd_tool_report(_args(root, transcripts))
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "| Tool" in out
        reports_dir = root / ".claude" / "hooks-daemon" / "untracked" / "reports"
        assert (reports_dir / "tool-report.md").is_file()
        payload = json.loads((reports_dir / "tool-report.json").read_text())
        tools = {row["tool"]: row for row in payload["rows"]}
        assert tools["Bash"]["calls"] == 2

    def test_declared_never_want_reaches_the_report(
        self, project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, transcripts = project
        (root / ".claude" / "hooks-daemon.yaml").write_text(
            "tool_policy:\n"
            "  never_want:\n"
            '    - {tool: Artifact, reason: "publishing leaves the repository"}\n'
        )
        assert cmd_tool_report(_args(root, transcripts)) == 0
        reports_dir = root / ".claude" / "hooks-daemon" / "untracked" / "reports"
        payload = json.loads((reports_dir / "tool-report.json").read_text())
        artifact = next(row for row in payload["rows"] if row["tool"] == "Artifact")
        assert artifact["tier"] == "never-want"
        assert artifact["reason"] == "publishing leaves the repository"

    def test_json_output_prints_machine_readable(
        self, project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, transcripts = project
        assert cmd_tool_report(_args(root, transcripts, json_output=True)) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["sessions_scanned"] == 1

    def test_no_write_skips_report_files(
        self, project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        root, transcripts = project
        assert cmd_tool_report(_args(root, transcripts, no_write=True)) == 0
        assert not (root / ".claude" / "hooks-daemon" / "untracked" / "reports").exists()

    def test_missing_transcripts_dir_still_reports(
        self, project: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A fresh project has no transcripts yet — that is a report saying
        so, not an error."""
        root, _ = project
        exit_code = cmd_tool_report(_args(root, root / "nope", no_write=True))
        assert exit_code == 0
        assert "0 transcript" in capsys.readouterr().out

    def test_a_missing_derived_directory_is_named_on_stderr(
        self,
        project: tuple[Path, Path],
        claude_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """00466 N27: an absent derived directory must not read as "no usage"
        without saying where the report looked."""
        root, _ = project
        assert cmd_tool_report(_args(root, None, no_write=True)) == 0
        err = capsys.readouterr().err
        assert str(claude_project_dir(root, config_dir=claude_config)) in err

    def test_enabled_plugins_listing_cost_is_reported(
        self,
        project: tuple[Path, Path],
        claude_config: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Plan 00468 G15: the enabled plugins' always-on cost reaches the report."""
        root, transcripts = project
        install_fake_plugin(
            claude_config, root, skills={"dbf": "name: dbf\ndescription: runs the method"}
        )
        assert cmd_tool_report(_args(root, transcripts, json_output=True, no_write=True)) == 0
        payload = json.loads(capsys.readouterr().out)
        (plugin,) = payload["plugins"]
        assert plugin["plugin_id"] == "defence-before-fix@defence-before-fix"
        assert plugin["skills_listed"] == 1
