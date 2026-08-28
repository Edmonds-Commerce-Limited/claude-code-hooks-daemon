"""Tests for the ``docs-qa`` CLI subcommand (Plan 00284, Tasks 3.1a + 3.1e)."""

import argparse
import json
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
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


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


def _init_repo(root: Path) -> None:
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")


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
    def test_clean_staged_tree_exits_zero(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        _init_repo(root)
        _git(root, "add", "-A")

        assert cmd_docs_qa(_args(root, check_staged=True)) == 0

    def test_new_staged_broken_link_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        (root / "CLAUDE" / "New.md").write_text("See [missing](Nope.md).\n")
        _init_repo(root)
        _git(root, "add", "-A")

        assert cmd_docs_qa(_args(root, check_staged=True)) == 1
        out = capsys.readouterr().out
        assert "pointer-resolves" in out

    def test_no_git_repo_is_clean(self, tmp_path: Path) -> None:
        """No .git at all: GitFacts fails soft, so nothing is staged to check."""
        root = _scaffold(tmp_path)
        assert cmd_docs_qa(_args(root, check_staged=True)) == 0


class TestGeneratedDocHandEdit:
    """Default config pre-seeds the manifest with .claude/HOOKS-DAEMON.md."""

    def test_lint_hand_edited_generated_doc_is_blocked(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        target = root / ".claude" / "HOOKS-DAEMON.md"
        target.write_text("# hand edit, not via generate-docs\n")

        assert cmd_docs_qa(_args(root, lint=target)) == 1
        out = capsys.readouterr().out
        assert "generated-doc-hand-edit" in out
        assert "bin/hooks-daemon generate-docs" in out

    def test_sweep_reports_stale_version_marker(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        target = root / ".claude" / "HOOKS-DAEMON.md"
        target.write_text("> Generated on 2020-01-01 (v0.0.1) by `generate-docs`.\n")

        assert cmd_docs_qa(_args(root, sweep=True)) == 1
        out = capsys.readouterr().out
        assert "generated-doc-hand-edit" in out
        assert "0.0.1" in out

    def test_sweep_runs_both_checks_together(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        (root / "CLAUDE" / "Foo.md").write_text("# Foo\n\n[missing](Nope.md)\n")
        (root / ".claude" / "HOOKS-DAEMON.md").write_text(
            "> Generated on 2020-01-01 (v0.0.1) by `generate-docs`.\n"
        )

        assert cmd_docs_qa(_args(root, sweep=True, json_output=True)) == 1
        payload = json.loads(capsys.readouterr().out)
        check_ids = {entry["check_id"] for entry in payload}
        assert check_ids == {"pointer-resolves", "generated-doc-hand-edit"}


class TestQuoteDrift:
    _LONG_SENTENCE = (
        "This is a real sentence that is long enough to clear the minimum "
        "quote length floor for verification purposes."
    )

    def test_lint_drifted_quote_is_blocked(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        (root / "CLAUDE" / "Bar.md").write_text(f"## Anchor\n\n{self._LONG_SENTENCE}\n")
        quoter = root / "CLAUDE" / "Quoter.md"
        quoter.write_text(
            "<!-- ssot-quote: CLAUDE/Bar.md#anchor -->\nThis text has drifted entirely "
            "from the source and no longer matches at all really.\n<!-- /ssot-quote -->\n"
        )

        assert cmd_docs_qa(_args(root, lint=quoter)) == 1
        out = capsys.readouterr().out
        assert "quote-drift" in out
        assert "drift" in out.lower()

    def test_lint_clean_quote_exits_zero(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        (root / "CLAUDE" / "Bar.md").write_text(f"## Anchor\n\n{self._LONG_SENTENCE}\n")
        quoter = root / "CLAUDE" / "Quoter.md"
        quoter.write_text(
            f"<!-- ssot-quote: CLAUDE/Bar.md#anchor -->\n{self._LONG_SENTENCE}\n"
            "<!-- /ssot-quote -->\n"
        )

        assert cmd_docs_qa(_args(root, lint=quoter)) == 0

    def test_sweep_reports_drifted_quote(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _scaffold(tmp_path)
        (root / "CLAUDE" / "Bar.md").write_text(f"## Anchor\n\n{self._LONG_SENTENCE}\n")
        (root / "CLAUDE" / "Quoter.md").write_text(
            "<!-- ssot-quote: CLAUDE/Bar.md#anchor -->\nThis text has drifted entirely "
            "from the source and no longer matches at all really.\n<!-- /ssot-quote -->\n"
        )

        assert cmd_docs_qa(_args(root, sweep=True)) == 1
        out = capsys.readouterr().out
        assert "quote-drift" in out


class TestQuoteSourceStale:
    """``quote-source-stale`` needs a would-be-vs-on-disk DIFF to fire.

    ``--lint`` checks one file's current content against itself (there is
    no "before"), so this check is structurally always silent through the
    CLI — it only ever fires through the PreToolUse handler's real Edit/
    Write diff. These tests pin that ``--lint`` stays clean (never crashes,
    never false-positives) both with and without a prebuilt corpus index.
    """

    _LONG_SENTENCE = (
        "This is a real sentence that is long enough to clear the minimum "
        "quote length floor for verification purposes."
    )

    def test_lint_of_a_known_source_file_is_silent(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        source = root / "CLAUDE" / "Bar.md"
        source.write_text(f"## Anchor\n\n{self._LONG_SENTENCE}\n")
        (root / "CLAUDE" / "Quoter.md").write_text(
            f"<!-- ssot-quote: CLAUDE/Bar.md#anchor -->\n{self._LONG_SENTENCE}\n"
            "<!-- /ssot-quote -->\n"
        )
        # Sweep first so a corpus index exists (quote-source-stale reads it,
        # never builds one, at --lint time) -- still silent, since --lint
        # has no diff to offer it.
        cmd_docs_qa(_args(root, sweep=True))

        assert cmd_docs_qa(_args(root, lint=source)) == 0

    def test_lint_of_source_without_a_prebuilt_index_is_cold_safe(self, tmp_path: Path) -> None:
        root = _scaffold(tmp_path)
        source = root / "CLAUDE" / "Bar.md"
        source.write_text(f"## Anchor\n\n{self._LONG_SENTENCE}\n")
        # No prior --sweep, so no untracked/docs-qa/index.json exists.
        assert cmd_docs_qa(_args(root, lint=source)) == 0
