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
        first = llm_qa.run_record(state, exit_code=0, passed=True, output_sha256=None)
        llm_qa.record_provenance(tmp_path, {"lint": first, "format": first})
        second = llm_qa.run_record(
            {"head": _OTHER_HEAD, "tree_digest": "d2"},
            exit_code=0,
            passed=True,
            output_sha256=None,
        )
        llm_qa.record_provenance(tmp_path, {"lint": second})
        recorded = llm_qa.read_provenance(tmp_path)
        assert recorded["format"] == first
        assert recorded["lint"]["head"] == _OTHER_HEAD

    def test_the_record_carries_the_verdict_and_the_outputs_hash(self, tmp_path: Path) -> None:
        output = tmp_path / "out.json"
        output.write_text("{}", encoding="utf-8")
        record = llm_qa.run_record(
            {"head": _HEAD, "tree_digest": "d1"},
            exit_code=3,
            passed=False,
            output_sha256=llm_qa.output_digest(output),
        )
        assert record["exit_code"] == 3
        assert record["passed"] is False
        assert record["output_sha256"] == llm_qa.output_digest(output)

    def test_a_missing_output_hashes_to_none(self, tmp_path: Path) -> None:
        assert llm_qa.output_digest(tmp_path / "absent.json") is None

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


_GREEN = {"summary": {"passed": True, "total_violations": 0}, "violations": []}
_TOOL = "magic_values"


def _run_state() -> dict[str, str]:
    """The tree a stubbed run judges; fresh each call, so no test can alter another's."""
    return {"head": _HEAD, "tree_digest": "d1"}


class TestARunCertifiesOnlyWhatItProduced:
    """Delta review N1, N2 and N6: ``_run_tools`` end to end, with the tool stubbed.

    A run used to stamp the current tree on every tool it ran, whatever the
    tool did. A tool that crashed without writing, or wrote a green report and
    exited non-zero, then read as a PASS under ``--read-only`` on the very tree
    whose live run FAILED.
    """

    @pytest.fixture
    def qa_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setattr(llm_qa, "QA_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr(llm_qa, "worktree_state", lambda root: _run_state())
        return tmp_path

    def _stub_tool(
        self,
        monkeypatch: pytest.MonkeyPatch,
        qa_dir: Path,
        *,
        exit_code: int,
        writes: dict[str, Any] | None,
        calls: list[tuple[str, tuple[str, ...]]] | None = None,
    ) -> None:
        def run_tool(name: str, extra_args: Any = (), lock_fd: int | None = None) -> int:
            if calls is not None:
                calls.append((name, tuple(extra_args)))
            if writes is not None:
                path = qa_dir / llm_qa.TOOL_REGISTRY[name].json_file
                path.write_text(json.dumps(writes), encoding="utf-8")
            return exit_code

        monkeypatch.setattr(llm_qa, "run_tool", run_tool)

    def _seed_old_green(self, qa_dir: Path) -> None:
        (qa_dir / llm_qa.TOOL_REGISTRY[_TOOL].json_file).write_text(
            json.dumps(_GREEN), encoding="utf-8"
        )

    def test_a_tool_that_crashes_without_output_does_not_certify_the_old_report(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        self._seed_old_green(qa_dir)
        self._stub_tool(monkeypatch, qa_dir, exit_code=1, writes=None)
        assert llm_qa._run_tools([_TOOL], read_only=False) != llm_qa.EXIT_SUCCESS
        capsys.readouterr()
        assert llm_qa._run_tools([_TOOL], read_only=True) != llm_qa.EXIT_SUCCESS
        assert "1/1 PASSED" not in capsys.readouterr().out

    def test_a_green_report_from_a_failing_exit_does_not_pass_read_only(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        self._stub_tool(monkeypatch, qa_dir, exit_code=1, writes=_GREEN)
        assert llm_qa._run_tools([_TOOL], read_only=False) != llm_qa.EXIT_SUCCESS
        capsys.readouterr()
        assert llm_qa._run_tools([_TOOL], read_only=True) != llm_qa.EXIT_SUCCESS

    def test_a_clean_run_is_certified(self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_tool(monkeypatch, qa_dir, exit_code=0, writes=_GREEN)
        assert llm_qa._run_tools([_TOOL], read_only=False) == llm_qa.EXIT_SUCCESS
        assert llm_qa._run_tools([_TOOL], read_only=True) == llm_qa.EXIT_SUCCESS
        record = llm_qa.read_provenance(qa_dir)[_TOOL]
        assert (record["head"], record["exit_code"], record["passed"]) == (_HEAD, 0, True)

    def test_a_report_replaced_after_the_run_is_not_certified(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        self._stub_tool(monkeypatch, qa_dir, exit_code=0, writes=_GREEN)
        llm_qa._run_tools([_TOOL], read_only=False)
        swapped = {**_GREEN, "note": "someone else's run"}
        (qa_dir / llm_qa.TOOL_REGISTRY[_TOOL].json_file).write_text(
            json.dumps(swapped), encoding="utf-8"
        )
        capsys.readouterr()
        assert llm_qa._run_tools([_TOOL], read_only=True) != llm_qa.EXIT_SUCCESS
        assert "not the one that run wrote" in capsys.readouterr().out

    def test_a_report_a_later_tool_rewrites_is_not_certified(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        """Review 3 R8: the hash was taken after EVERY tool, so a rewrite was certified."""
        first_report = qa_dir / llm_qa.TOOL_REGISTRY[_TOOL].json_file

        def run_tool(name: str, extra_args: Any = (), lock_fd: int | None = None) -> int:
            if name == _TOOL:
                first_report.write_text(json.dumps(_GREEN), encoding="utf-8")
            else:
                first_report.write_text(json.dumps({**_GREEN, "rewritten": 1}), encoding="utf-8")
                (qa_dir / llm_qa.TOOL_REGISTRY[name].json_file).write_text(
                    json.dumps(_GREEN), encoding="utf-8"
                )
            return 0

        monkeypatch.setattr(llm_qa, "run_tool", run_tool)
        llm_qa._run_tools([_TOOL, "lint"], read_only=False)
        capsys.readouterr()
        assert llm_qa._run_tools([_TOOL], read_only=True) != llm_qa.EXIT_SUCCESS
        assert "not the one that run wrote" in capsys.readouterr().out

    def test_a_recorded_failure_never_reads_as_a_pass(self, qa_dir: Path, capsys: Any) -> None:
        """Review 3 R8: ``passed`` was recorded and never read."""
        report = qa_dir / llm_qa.TOOL_REGISTRY[_TOOL].json_file
        report.write_text(json.dumps(_GREEN), encoding="utf-8")
        record = llm_qa.run_record(
            _run_state(), exit_code=0, passed=False, output_sha256=llm_qa.output_digest(report)
        )
        llm_qa.record_provenance(qa_dir, {_TOOL: record})
        assert llm_qa._run_tools([_TOOL], read_only=True) != llm_qa.EXIT_SUCCESS
        assert "did not pass" in capsys.readouterr().out

    def test_a_tree_that_changes_during_the_run_is_said_at_the_time(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        states = iter([_run_state(), {"head": _HEAD, "tree_digest": "d2"}])
        monkeypatch.setattr(llm_qa, "worktree_state", lambda root: next(states))
        self._stub_tool(monkeypatch, qa_dir, exit_code=0, writes=_GREEN)
        llm_qa._run_tools([_TOOL], read_only=False)
        assert "changed during the run" in capsys.readouterr().out
        assert llm_qa.read_provenance(qa_dir)[_TOOL]["tree_digest"] == "changed-during-run"

    def test_forwarded_options_reach_changed_tests_and_nothing_else(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[tuple[str, tuple[str, ...]]] = []
        self._stub_tool(monkeypatch, qa_dir, exit_code=0, writes=_GREEN, calls=calls)
        llm_qa._run_tools(["lint", "changed_tests"], read_only=False, forwarded=["--base", "t"])
        assert calls == [("lint", ()), ("changed_tests", ("--base", "t"))]
