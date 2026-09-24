"""``llm_qa.py --read-only`` refuses results it cannot tie to HEAD (Plan 00463).

Review finding 3. A read-only summary is how a sub-agent (the release agent,
qa-runner) reads the coordinator's full run without running it. With nothing
tying ``untracked/qa/*.json`` to a commit, a green result from an older commit,
or from before later edits, read as a pass. So each run records the tree it
judged, and a read-only summary FAILS a result recorded for any other tree.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


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


llm_qa = _load("llm_qa.py", "llm_qa_for_provenance_test")

_HEAD = "a" * 40
_OTHER_HEAD = "b" * 40


def _git(head: str = _HEAD, diff: bytes = b"", untracked: bytes = b"", fail: bool = False) -> Any:
    def run(args: list[str], root: Path) -> tuple[int, bytes]:
        if fail:
            return 128, b""
        if args[0] == "rev-parse":
            return 0, f"{head}\n".encode()
        if args[0] == "diff":
            return 0, diff
        if args[0] == "ls-files":
            return 0, untracked
        raise AssertionError(f"unexpected git call: {args}")

    return run


class TestWorktreeState:
    def test_it_records_head_and_a_digest(self, tmp_path: Path) -> None:
        state = llm_qa.worktree_state(tmp_path, git=_git())
        assert state is not None
        assert state["head"] == _HEAD
        assert state["tree_digest"]

    def test_an_uncommitted_edit_changes_the_digest(self, tmp_path: Path) -> None:
        clean = llm_qa.worktree_state(tmp_path, git=_git())
        edited = llm_qa.worktree_state(tmp_path, git=_git(diff=b"+changed\n"))
        assert clean != edited

    def test_an_untracked_files_content_changes_the_digest(self, tmp_path: Path) -> None:
        (tmp_path / "new.py").write_text("one", encoding="utf-8")
        before = llm_qa.worktree_state(tmp_path, git=_git(untracked=b"new.py\0"))
        (tmp_path / "new.py").write_text("two", encoding="utf-8")
        after = llm_qa.worktree_state(tmp_path, git=_git(untracked=b"new.py\0"))
        assert before != after

    def test_an_unreadable_tree_is_none_not_a_guess(self, tmp_path: Path) -> None:
        assert llm_qa.worktree_state(tmp_path, git=_git(fail=True)) is None


class TestStaleReason:
    def test_the_same_tree_is_fresh(self) -> None:
        state = {"head": _HEAD, "tree_digest": "d1"}
        assert llm_qa.stale_reason(dict(state), dict(state)) is None

    @pytest.mark.parametrize(
        ("recorded", "current"),
        [
            (None, {"head": _HEAD, "tree_digest": "d1"}),
            ({"head": _OTHER_HEAD, "tree_digest": "d1"}, {"head": _HEAD, "tree_digest": "d1"}),
            ({"head": _HEAD, "tree_digest": "d0"}, {"head": _HEAD, "tree_digest": "d1"}),
            ({"head": _HEAD, "tree_digest": "d1"}, None),
        ],
        ids=["no-record", "other-commit", "edited-since", "tree-unreadable"],
    )
    def test_anything_else_is_stale(
        self, recorded: dict[str, str] | None, current: dict[str, str] | None
    ) -> None:
        assert llm_qa.stale_reason(recorded, current)


class TestTheRecord:
    def test_a_run_records_the_tree_each_tool_judged(self, tmp_path: Path) -> None:
        state = {"head": _HEAD, "tree_digest": "d1"}
        llm_qa.record_provenance(tmp_path, ["lint", "format"], state)
        llm_qa.record_provenance(tmp_path, ["lint"], {"head": _OTHER_HEAD, "tree_digest": "d2"})
        recorded = llm_qa.read_provenance(tmp_path)
        assert recorded["format"] == state
        assert recorded["lint"]["head"] == _OTHER_HEAD

    def test_a_missing_or_corrupt_record_reads_as_empty(self, tmp_path: Path) -> None:
        assert llm_qa.read_provenance(tmp_path) == {}
        (tmp_path / llm_qa.PROVENANCE_FILE).write_text("{not json", encoding="utf-8")
        assert llm_qa.read_provenance(tmp_path) == {}


class TestReadOnlySummary:
    def _summary(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stale: str | None) -> Any:
        monkeypatch.setattr(llm_qa, "QA_OUTPUT_DIR", tmp_path)
        (tmp_path / "format.json").write_text(
            json.dumps({"summary": {"passed": True, "total_violations": 0}, "violations": []}),
            encoding="utf-8",
        )
        return llm_qa.summarize_tool("format", stale=stale)

    def test_a_stale_green_result_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        passed, text = self._summary(tmp_path, monkeypatch, stale="recorded at bbbb")
        assert passed is False
        assert "STALE" in text
        assert "recorded at bbbb" in text

    def test_a_fresh_green_result_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        passed, text = self._summary(tmp_path, monkeypatch, stale=None)
        assert passed is True
        assert "STALE" not in text
