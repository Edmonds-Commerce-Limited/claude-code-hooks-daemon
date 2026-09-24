"""``llm_qa.py main-moved``: may a batch skip a second full run? (Plan 00463).

The coordinator's batched gate runs the full suite once on an integration
branch built from ``main``. If ``main`` moves before the fast-forward, the
green run no longer covers what would land. Re-running twenty minutes of full
QA because a ledger row landed on ``main`` is exactly the waste the owner
asked to stop, so a DOCS-ONLY move re-runs only the cheap doc checks.

What counts as docs-only must be a checked mechanism, not a judgement, so the
path set lives in ``llm_qa.py`` alone and every boundary is pinned here:

- a file inside a numbered plan folder, or
- a ``.md`` file outside ``src/``, ``tests/`` and ``scripts/``.

The plan directory's own root is NOT docs-only: ``mkplan.bash`` and
``_planlib.inc.bash`` live there, and they are executed code with tests.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_llm_qa() -> Any:
    """Import ``scripts/qa/llm_qa.py``, which is a script rather than a module."""
    module_path = PROJECT_ROOT / "scripts" / "qa" / "llm_qa.py"
    spec = importlib.util.spec_from_file_location("llm_qa_main_moved_under_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


llm_qa = _load_llm_qa()

_DOCS_ONLY_PATHS = [
    "CLAUDE/Plan/00466-niggles-ledger-sixteen/PLAN.md",
    "CLAUDE/Plan/00466-niggles-ledger-sixteen/JOURNAL/00466-Journal-26-09-24.md",
    "CLAUDE/Plan/00463-full-qa-is-a-main-thread-gate/subagent-reports/r.md",
    "CLAUDE/Plan/Completed/00462-php-lsp/PLAN.md",
    "CLAUDE/Plan/Completed/00462-php-lsp/probe.py",
    "CLAUDE/Plan/00471-a-plan/notes.json",
    "CLAUDE/Plan/README.md",
    "CLAUDE/Plan/Completed/README.md",
    "CLAUDE/QA.md",
    "CLAUDE/development/IssueSdlc.md",
    "docs/guides/HANDLER_REFERENCE.md",
    "README.md",
    "RELEASES/v3.66.0.md",
]

_FULL_GATE_PATHS = [
    "CLAUDE/Plan/mkplan.bash",
    "CLAUDE/Plan/_planlib.inc.bash",
    "CLAUDE/Plan/Completed/stray.py",
    "CLAUDE/Plan/00466/PLAN.bash",
    "src/claude_code_hooks_daemon/handlers/pre_tool_use/subagent_full_qa_blocker.py",
    "src/CLAUDE.md",
    "src/claude_code_hooks_daemon/guides/guide.md",
    "tests/CLAUDE.md",
    "scripts/qa/README.md",
    ".claude/hooks-daemon.yaml",
    "pyproject.toml",
    "CLAUDE/QA.MD",
    "docs/diagram.svg",
]


class TestWhichPathsAreDocsOnly:
    @pytest.mark.parametrize("path", _DOCS_ONLY_PATHS)
    def test_a_docs_only_path(self, path: str) -> None:
        assert llm_qa.is_docs_only_path(path) is True

    @pytest.mark.parametrize("path", _FULL_GATE_PATHS)
    def test_a_path_that_needs_the_full_gate(self, path: str) -> None:
        assert llm_qa.is_docs_only_path(path) is False


class TestTheVerdict:
    def test_no_paths_means_main_has_not_moved(self) -> None:
        assert llm_qa.classify_moved_paths([]) == llm_qa.VERDICT_UNMOVED

    def test_only_docs_is_docs_only(self) -> None:
        assert llm_qa.classify_moved_paths(_DOCS_ONLY_PATHS) == llm_qa.VERDICT_DOCS_ONLY

    @pytest.mark.parametrize("code_path", _FULL_GATE_PATHS)
    def test_one_code_path_among_docs_needs_the_full_gate(self, code_path: str) -> None:
        paths = [*_DOCS_ONLY_PATHS, code_path]
        assert llm_qa.classify_moved_paths(paths) == llm_qa.VERDICT_FULL_GATE


class TestTheDocsOnlyRecheck:
    def test_it_is_the_cheap_doc_tools_and_every_one_is_registered(self) -> None:
        assert llm_qa.DOCS_ONLY_TOOL_NAMES == [
            "plan_qa",
            "docs_qa",
            "format",
            "british_english",
            "sensitive_content",
        ]
        assert set(llm_qa.DOCS_ONLY_TOOL_NAMES) <= set(llm_qa.TOOL_REGISTRY)


# ── Against a real repository ─────────────────────────────────────────────


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        timeout=Timeout.QA_TEST_TIMEOUT,
        check=True,
        env=env,
    )
    return result.stdout.strip()


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    for relative, content in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository whose ``main`` has one commit: the batch base."""
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(tmp_path, {"src/app.py": "x = 1\n", "CLAUDE/QA.md": "# QA\n"}, "base")
    return tmp_path


class TestAgainstARealRepository:
    def test_main_unmoved(self, repo: Path) -> None:
        base = _git(repo, "rev-parse", "main")
        outcome = llm_qa.main_moved(base, "main", repo)
        assert outcome.verdict == llm_qa.VERDICT_UNMOVED
        assert outcome.paths == []

    def test_a_ledger_row_on_main_is_docs_only(self, repo: Path) -> None:
        base = _git(repo, "rev-parse", "main")
        _commit(repo, {"CLAUDE/Plan/00466-ledger/PLAN.md": "| N2 |\n"}, "ledger")
        outcome = llm_qa.main_moved(base, "main", repo)
        assert outcome.verdict == llm_qa.VERDICT_DOCS_ONLY
        assert outcome.paths == ["CLAUDE/Plan/00466-ledger/PLAN.md"]

    def test_a_code_change_on_main_needs_the_full_gate(self, repo: Path) -> None:
        base = _git(repo, "rev-parse", "main")
        _commit(repo, {"CLAUDE/QA.md": "# QA 2\n", "src/app.py": "x = 2\n"}, "code")
        outcome = llm_qa.main_moved(base, "main", repo)
        assert outcome.verdict == llm_qa.VERDICT_FULL_GATE
        assert "src/app.py" in outcome.paths

    def test_a_rename_out_of_src_is_seen_by_its_old_path(self, repo: Path) -> None:
        """With rename detection, ``git diff --name-only`` prints only the NEW name.

        Moving ``src/app.py`` to ``docs/app.md`` would then read as docs-only,
        though the move deleted code.
        """
        base = _git(repo, "rev-parse", "main")
        _git(repo, "mv", "src/app.py", "docs-app.md")
        _git(repo, "commit", "-q", "-m", "move")
        outcome = llm_qa.main_moved(base, "main", repo)
        assert outcome.verdict == llm_qa.VERDICT_FULL_GATE
        assert "src/app.py" in outcome.paths

    def test_a_base_that_main_no_longer_contains_needs_the_full_gate(self, repo: Path) -> None:
        """A rewritten main has no meaningful ``base..main`` diff to classify."""
        _git(repo, "checkout", "-q", "-b", "side")
        side = _commit(repo, {"CLAUDE/Plan/00466-ledger/PLAN.md": "x\n"}, "side")
        _git(repo, "checkout", "-q", "main")
        outcome = llm_qa.main_moved(side, "main", repo)
        assert outcome.verdict == llm_qa.VERDICT_FULL_GATE
        assert outcome.reason

    def test_an_unknown_ref_fails_rather_than_passing(self, repo: Path) -> None:
        with pytest.raises(llm_qa.MainMovedError):
            llm_qa.main_moved("no-such-ref", "main", repo)


class TestTheCommand:
    def test_docs_only_prints_the_verdict_and_the_recheck(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = _git(repo, "rev-parse", "main")
        _commit(repo, {"CLAUDE/Plan/00466-ledger/PLAN.md": "| N2 |\n"}, "ledger")
        exit_code = llm_qa.main_moved_command([base], root=repo)
        out = capsys.readouterr().out
        assert exit_code == llm_qa.EXIT_SUCCESS
        assert f"VERDICT: {llm_qa.VERDICT_DOCS_ONLY}" in out
        assert "llm_qa.py " + " ".join(llm_qa.DOCS_ONLY_TOOL_NAMES) in out

    def test_full_gate_exits_with_its_own_code_and_names_the_paths(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base = _git(repo, "rev-parse", "main")
        _commit(repo, {"src/app.py": "x = 3\n"}, "code")
        exit_code = llm_qa.main_moved_command([base, "main"], root=repo)
        out = capsys.readouterr().out
        assert exit_code == llm_qa.EXIT_FULL_GATE
        assert f"VERDICT: {llm_qa.VERDICT_FULL_GATE}" in out
        assert "src/app.py" in out

    def test_unmoved_exits_zero(self, repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
        base = _git(repo, "rev-parse", "main")
        assert llm_qa.main_moved_command([base], root=repo) == llm_qa.EXIT_SUCCESS
        assert f"VERDICT: {llm_qa.VERDICT_UNMOVED}" in capsys.readouterr().out

    def test_a_git_failure_is_an_error_not_a_verdict(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert llm_qa.main_moved_command(["no-such-ref"], root=repo) == llm_qa.EXIT_FAILURE
        assert "VERDICT" not in capsys.readouterr().out

    @pytest.mark.parametrize("args", [[], ["a", "b", "c"], ["--base"]])
    def test_wrong_arguments_are_a_usage_error(
        self, args: list[str], repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert llm_qa.main_moved_command(args, root=repo) == llm_qa.EXIT_FAILURE
        assert "Usage" in capsys.readouterr().err

    def test_main_dispatches_the_subcommand(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Reached from the CLI, before tool resolution and without the run lock."""
        monkeypatch.setattr(sys, "argv", ["llm_qa.py", llm_qa.MAIN_MOVED_COMMAND])
        assert llm_qa.main() == llm_qa.EXIT_FAILURE
        err = capsys.readouterr().err
        assert "Usage" in err
        assert "Unknown tool" not in err
