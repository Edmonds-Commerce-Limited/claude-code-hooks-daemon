"""Tests for the ``docs-qa`` CLI subcommand (Plan 00284, Task 3.1a)."""

import argparse
import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.cli import cmd_docs_qa


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


def _scaffold(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "CLAUDE").mkdir(parents=True)
    (root / "CLAUDE" / "Foo.md").write_text("# Foo\n\n[link](Bar.md)\n")
    (root / "CLAUDE" / "Bar.md").write_text("# Bar\n")
    (root / ".claude").mkdir()
    (root / ".claude" / "hooks-daemon.yaml").write_text("version: '2.0'\n")
    # Self-install marker so _daemon_untracked_dir resolves to root/untracked.
    (root / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
    return root


class TestSweep:
    def test_clean_corpus_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        assert cmd_docs_qa(_args(root, sweep=True)) == 0
        assert "0 finding" in capsys.readouterr().out

    def test_default_action_is_sweep(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        assert cmd_docs_qa(_args(root)) == 0
        assert "0 finding" in capsys.readouterr().out

    def test_broken_link_in_corpus_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        (root / "CLAUDE" / "Foo.md").write_text("# Foo\n\n[missing](Nope.md)\n")

        assert cmd_docs_qa(_args(root, sweep=True)) == 1
        out = capsys.readouterr().out
        assert "pointer-resolves" in out
        assert "Nope.md" in out

    def test_json_output_is_parseable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        (root / "CLAUDE" / "Foo.md").write_text("# Foo\n\n[missing](Nope.md)\n")

        assert cmd_docs_qa(_args(root, sweep=True, json_output=True)) == 1
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload, list)
        entry = payload[0]
        assert {"check_id", "severity", "message", "remediation", "path"} <= set(entry)

    def test_index_file_is_written_under_untracked(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        cmd_docs_qa(_args(root, sweep=True))
        assert (root / "untracked" / "docs-qa" / "index.json").is_file()

    def test_runs_regardless_of_documentation_enabled(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        (root / ".claude" / "hooks-daemon.yaml").write_text(
            "version: '2.0'\ndocumentation:\n  enabled: false\n"
        )
        assert cmd_docs_qa(_args(root, sweep=True)) == 0
        assert "0 finding" in capsys.readouterr().out


class TestLint:
    def test_lint_clean_file_exits_zero(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        assert cmd_docs_qa(_args(root, lint=root / "CLAUDE" / "Bar.md")) == 0

    def test_lint_broken_link_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        target = root / "CLAUDE" / "New.md"
        target.write_text("# New\n\n[missing](Nope.md)\n")

        assert cmd_docs_qa(_args(root, lint=target)) == 1
        assert "pointer-resolves" in capsys.readouterr().out

    def test_lint_missing_file_exits_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        assert cmd_docs_qa(_args(root, lint=root / "CLAUDE" / "Nope.md")) == 2
        assert "does not exist" in capsys.readouterr().err.lower()

    def test_lint_out_of_scope_file_exits_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        outsider = root / "src" / "notes.md"
        outsider.write_text("# not a doc\n")

        assert cmd_docs_qa(_args(root, lint=outsider)) == 2
        assert "not a documentation file" in capsys.readouterr().err.lower()

    def test_lint_clean_file_does_not_claim_the_corpus_is_clean(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        assert cmd_docs_qa(_args(root, lint=root / "CLAUDE" / "Bar.md")) == 0
        assert "documentation corpus is clean" not in capsys.readouterr().out.lower()

    def test_relative_lint_target_matches_absolute(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _scaffold(tmp_path)
        (root / "CLAUDE" / "New.md").write_text("# New\n\n[missing](Nope.md)\n")
        relative = Path("CLAUDE/New.md")

        absolute_exit = cmd_docs_qa(_args(root, lint=root / relative))
        monkeypatch.chdir(root)
        relative_exit = cmd_docs_qa(_args(root, lint=relative))

        assert absolute_exit == 1
        assert relative_exit == absolute_exit


class TestCheckStaged:
    def test_not_implemented_exits_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        assert cmd_docs_qa(_args(root, check_staged=True)) == 2
        assert "not implemented" in capsys.readouterr().err.lower()
