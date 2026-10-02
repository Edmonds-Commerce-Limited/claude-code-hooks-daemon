"""``llm_qa.py changed`` records the commit it passed on, in a ref every worktree shares.

Plan 00475 Task 4.2 (ledger 00474 N278). The per-tool ``provenance.json`` lives
in the checkout the run happened in (``untracked/qa/``), so the coordinator, who
merges from the main checkout, cannot read a branch worktree's copy without
knowing where that worktree is. A passing run that covers every tool ``changed``
selects, on a clean tree, therefore also writes
``refs/integration/changed-green/<branch>``, which holds the commit it judged.
The merge-time advisory reads that ref.
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
_BRANCH = "worktree-feature"


def _load(script: str, name: str) -> Any:
    """Import a file under ``scripts/qa/``, which is a script rather than a module."""
    module_path = PROJECT_ROOT / "scripts" / "qa" / script
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


llm_qa = _load("llm_qa.py", "llm_qa_changed_green_under_test")


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


def _commit(repo: Path, name: str, message: str) -> str:
    (repo / name).write_text(message, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _green(repo: Path) -> str | None:
    listed = _git(repo, "for-each-ref", "--format=%(objectname)", llm_qa.changed_green_ref(_BRANCH))
    return listed or None


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository on a work branch, with ``untracked/`` ignored as in this project."""
    _git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / ".gitignore").write_text("untracked/\n", encoding="utf-8")
    _commit(tmp_path, "base.txt", "base")
    _git(tmp_path, "checkout", "-q", "-b", _BRANCH)
    _commit(tmp_path, "feature.txt", "feature")
    return tmp_path


class TestTheRef:
    def test_the_ref_is_keyed_by_branch(self) -> None:
        assert llm_qa.changed_green_ref(_BRANCH) == f"refs/integration/changed-green/{_BRANCH}"


class TestRecording:
    def test_a_clean_tree_records_head(self, repo: Path) -> None:
        head = llm_qa.record_changed_pass(repo, llm_qa.worktree_state(repo))
        assert head == _git(repo, "rev-parse", "HEAD")
        assert _green(repo) == head

    def test_a_later_pass_moves_the_record_to_the_new_head(self, repo: Path) -> None:
        llm_qa.record_changed_pass(repo, llm_qa.worktree_state(repo))
        newer = _commit(repo, "more.txt", "more")
        llm_qa.record_changed_pass(repo, llm_qa.worktree_state(repo))
        assert _green(repo) == newer

    def test_a_dirty_tree_records_nothing(self, repo: Path) -> None:
        (repo / "feature.txt").write_text("edited", encoding="utf-8")
        with pytest.raises(llm_qa.MainMovedError, match="uncommitted"):
            llm_qa.record_changed_pass(repo, llm_qa.worktree_state(repo))
        assert _green(repo) is None

    def test_a_tree_that_changed_during_the_run_records_nothing(self, repo: Path) -> None:
        judged = llm_qa.worktree_state(repo)
        _commit(repo, "during.txt", "during the run")
        with pytest.raises(llm_qa.MainMovedError, match="changed"):
            llm_qa.record_changed_pass(repo, judged)
        assert _green(repo) is None

    def test_a_detached_head_records_nothing(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "--detach")
        with pytest.raises(llm_qa.MainMovedError, match="detached"):
            llm_qa.record_changed_pass(repo, llm_qa.worktree_state(repo))

    def test_an_unreadable_tree_records_nothing(self, repo: Path) -> None:
        with pytest.raises(llm_qa.MainMovedError, match="changed"):
            llm_qa.record_changed_pass(repo, None)
        assert _green(repo) is None


class TestClearing:
    def test_a_failing_run_removes_the_record_for_that_branch(self, repo: Path) -> None:
        llm_qa.record_changed_pass(repo, llm_qa.worktree_state(repo))
        llm_qa.clear_changed_pass(repo)
        assert _green(repo) is None

    def test_clearing_with_no_record_is_quiet(self, repo: Path) -> None:
        llm_qa.clear_changed_pass(repo)
        assert _green(repo) is None

    def test_clearing_on_a_detached_head_is_quiet(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "--detach")
        llm_qa.clear_changed_pass(repo)


class TestTheRunWritesIt:
    """``_run_tools`` over the whole ``changed`` selection, with each tool stubbed."""

    @pytest.fixture
    def stubbed(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        qa_dir = repo / "untracked" / "qa"
        qa_dir.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(llm_qa, "PROJECT_ROOT", repo)
        monkeypatch.setattr(llm_qa, "QA_OUTPUT_DIR", qa_dir)

        def run_tool(name: str, extra_args: Any = (), lock_fd: int | None = None) -> int:
            (qa_dir / llm_qa.TOOL_REGISTRY[name].json_file).write_text("{}", encoding="utf-8")
            return 0

        monkeypatch.setattr(llm_qa, "run_tool", run_tool)
        monkeypatch.setattr(llm_qa, "ensure_live_daemon", lambda tool: None)
        return qa_dir

    def _summaries(self, monkeypatch: pytest.MonkeyPatch, failing: str | None) -> None:
        def summarize(name: str, **_: Any) -> tuple[bool, str]:
            return name != failing, f"{name}\n"

        monkeypatch.setattr(llm_qa, "summarize_tool", summarize)

    def test_a_passing_changed_run_records_head(
        self, repo: Path, stubbed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._summaries(monkeypatch, failing=None)
        assert llm_qa._run_tools(list(llm_qa.CHANGED_TOOL_NAMES), read_only=False) == 0
        assert _green(repo) == _git(repo, "rev-parse", "HEAD")

    def test_a_failing_changed_run_clears_an_earlier_record(
        self, repo: Path, stubbed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        llm_qa.record_changed_pass(repo, llm_qa.worktree_state(repo))
        self._summaries(monkeypatch, failing="lint")
        llm_qa._run_tools(list(llm_qa.CHANGED_TOOL_NAMES), read_only=False)
        assert _green(repo) is None

    def test_a_partial_run_records_nothing(
        self, repo: Path, stubbed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._summaries(monkeypatch, failing=None)
        llm_qa._run_tools(["lint"], read_only=False)
        assert _green(repo) is None

    def test_a_partial_failing_run_keeps_an_earlier_record(
        self, repo: Path, stubbed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only a run of the whole selection speaks for the whole selection."""
        head = llm_qa.record_changed_pass(repo, llm_qa.worktree_state(repo))
        self._summaries(monkeypatch, failing="lint")
        llm_qa._run_tools(["lint"], read_only=False)
        assert _green(repo) == head

    def test_a_dirty_tree_says_so_and_records_nothing(
        self,
        repo: Path,
        stubbed: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (repo / "feature.txt").write_text("edited", encoding="utf-8")
        self._summaries(monkeypatch, failing=None)
        assert llm_qa._run_tools(list(llm_qa.CHANGED_TOOL_NAMES), read_only=False) == 0
        assert _green(repo) is None
        assert "uncommitted" in capsys.readouterr().out

    def test_a_read_only_summary_records_nothing(
        self, repo: Path, stubbed: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._summaries(monkeypatch, failing=None)
        llm_qa._run_tools(list(llm_qa.CHANGED_TOOL_NAMES), read_only=True)
        assert _green(repo) is None
