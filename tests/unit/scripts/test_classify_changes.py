"""The CI change classifier (Plan 00475 Phase 3b): which QA tier a change set needs.

Three tiers: ``docs`` (every path is markdown), ``code`` (anything else) and
``full`` (build or CI config changed, or the base is unknown, so nothing can be
narrowed safely). The classifier is the ONLY place the rules live; the workflow
just reads its ``tier=<x>`` line.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "ci" / "classify_changes.py"
_ZERO_SHA = "0" * 40


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("classify_changes", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["classify_changes"] = module
    spec.loader.exec_module(module)
    return module


classify_changes = _load()


class TestClassifyPaths:
    """The path rules, in isolation from git."""

    @pytest.mark.parametrize(
        "path",
        [
            "pyproject.toml",
            "uv.lock",
            ".github/workflows/qa.yml",
            ".github/actions/setup/action.yml",
            ".github/README.md",
            ".claude/hooks-daemon.yaml",
            "scripts/qa/changed_tests_map.yaml",
            "tests/conftest.py",
            "tests/unit/conftest.py",
            "conftest.py",
        ],
    )
    def test_build_and_ci_config_is_full(self, path: str) -> None:
        assert classify_changes.classify_paths([path]) == "full"

    def test_full_wins_over_docs_and_code(self) -> None:
        paths = ["README.md", "src/a.py", "uv.lock"]
        assert classify_changes.classify_paths(paths) == "full"

    @pytest.mark.parametrize(
        "path",
        ["README.md", "CLAUDE/Plan/00475-x/PLAN.md", "docs/guide/a.md", "CLAUDE/LEDGER.md"],
    )
    def test_markdown_only_is_docs(self, path: str) -> None:
        assert classify_changes.classify_paths([path]) == "docs"

    def test_many_markdown_files_are_docs(self) -> None:
        assert classify_changes.classify_paths(["a.md", "b/c.md"]) == "docs"

    @pytest.mark.parametrize(
        "path",
        [
            "src/claude_code_hooks_daemon/core/x.py",
            "tests/unit/test_x.py",
            "scripts/qa/llm_qa.py",
            "CLAUDE/Plan/00475-x/config.yaml",
            "notes.mdx",
            "Makefile",
        ],
    )
    def test_anything_else_is_code(self, path: str) -> None:
        assert classify_changes.classify_paths([path]) == "code"

    def test_markdown_beside_code_is_code(self) -> None:
        assert classify_changes.classify_paths(["a.md", "src/a.py"]) == "code"

    def test_no_paths_is_full(self) -> None:
        """An empty change set proves nothing, so it narrows nothing."""
        assert classify_changes.classify_paths([]) == "full"


class TestBaseKnown:
    """A base that cannot anchor a diff forces the full tier."""

    @pytest.fixture
    def repo(self, tmp_path: Path) -> Path:
        def git(*args: str) -> None:
            subprocess.run(
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                cwd=tmp_path,
                check=True,
                capture_output=True,
            )

        git("init", "-q")
        (tmp_path / "a.md").write_text("one\n")
        git("add", ".")
        git("commit", "-q", "-m", "one")
        (tmp_path / "a.md").write_text("two\n")
        git("commit", "-q", "-am", "two")
        return tmp_path

    def _sha(self, repo: Path, rev: str) -> str:
        out = subprocess.run(
            ["git", "rev-parse", rev], cwd=repo, check=True, capture_output=True, text=True
        )
        return out.stdout.strip()

    def test_known_base_diffs_and_classifies(self, repo: Path) -> None:
        tier = classify_changes.classify_range(self._sha(repo, "HEAD~1"), "HEAD", repo)
        assert tier == "docs"

    @pytest.mark.parametrize("base", ["", _ZERO_SHA])
    def test_missing_or_zero_base_is_full(self, repo: Path, base: str) -> None:
        assert classify_changes.classify_range(base, "HEAD", repo) == "full"

    def test_base_not_in_history_is_full(self, repo: Path) -> None:
        assert classify_changes.classify_range("1" * 40, "HEAD", repo) == "full"

    def test_renamed_config_counts_both_sides(self, repo: Path) -> None:
        """Renaming uv.lock away is a config change, so rename detection is off."""
        (repo / "uv.lock").write_text("lock\n" * 50)
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "lock"],
            cwd=repo,
            check=True,
        )
        base = self._sha(repo, "HEAD")
        subprocess.run(["git", "mv", "uv.lock", "uv.md"], cwd=repo, check=True)
        subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "mv"],
            cwd=repo,
            check=True,
        )
        assert classify_changes.classify_range(base, "HEAD", repo) == "full"


class TestMain:
    """The CLI prints exactly one ``tier=<x>`` line for ``$GITHUB_OUTPUT``."""

    def test_paths_option_prints_tier_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = classify_changes.main(["--paths", "a.md", "b.md"])
        assert code == 0
        assert capsys.readouterr().out == "tier=docs\n"

    def test_range_without_base_prints_full(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = classify_changes.main(["--base", "", "--head", "HEAD"])
        assert code == 0
        assert capsys.readouterr().out == "tier=full\n"

    def test_outside_a_repository_is_full_and_stdout_stays_clean(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Nothing can be diffed: full, never a crash; the reason goes to stderr only."""
        assert classify_changes.classify_range("a" * 40, "HEAD", tmp_path) == "full"
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "full tier" in captured.err
