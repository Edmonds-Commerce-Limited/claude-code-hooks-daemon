"""Per-step provenance and ``llm_qa.py all --resume`` (Plan 00500 Task 2.2).

A gate killed part-way (a host reboot) used to record nothing, because the
provenance file was written once after the loop, and the tree was compared once
per run, so most records read ``changed-during-run``. Each step now records
itself as it finishes, judged on the tree just before and just after it, and
``--resume`` re-uses a passing record for the identical tree.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections.abc import Callable, Iterator
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


llm_qa = _load("llm_qa.py", "llm_qa_for_resume_test")

_HEAD = "b" * 40
_GREEN: dict[str, Any] = {"summary": {"passed": True}, "passed": True}


def _tree(digest: str) -> dict[str, str]:
    return {"head": _HEAD, "tree_digest": digest}


def _trees(*digests: str) -> Callable[[Path], dict[str, str]]:
    """A ``worktree_state`` that yields each digest in turn, then repeats the last."""
    values: Iterator[str] = iter(digests)
    last = {"value": digests[-1]}

    def state(root: Path) -> dict[str, str]:
        last["value"] = next(values, last["value"])
        return _tree(last["value"])

    return state


@pytest.fixture
def qa_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(llm_qa, "QA_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(llm_qa, "worktree_state", _trees("d1"))
    return tmp_path


@pytest.fixture
def ran(qa_dir: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stub ``run_tool``: every tool passes and writes a green report; the names are recorded."""
    names: list[str] = []

    def run_tool(name: str, extra_args: Any = (), lock_fd: int | None = None) -> int:
        names.append(name)
        (qa_dir / llm_qa.TOOL_REGISTRY[name].json_file).write_text(
            json.dumps(_GREEN), encoding="utf-8"
        )
        return 0

    monkeypatch.setattr(llm_qa, "run_tool", run_tool)
    return names


class TestEachStepRecordsItselfAsItFinishes:
    def test_an_interrupted_run_keeps_the_steps_that_finished(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, ran: list[str]
    ) -> None:
        inner = llm_qa.run_tool

        def run_tool(name: str, extra_args: Any = (), lock_fd: int | None = None) -> int:
            if name == "smoke_test":
                raise KeyboardInterrupt
            result: int = inner(name, extra_args, lock_fd)
            return result

        monkeypatch.setattr(llm_qa, "run_tool", run_tool)
        with pytest.raises(KeyboardInterrupt):
            llm_qa._run_tools(["lint", "format", "smoke_test"], read_only=False)
        assert set(llm_qa.read_provenance(qa_dir)) == {"lint", "format"}

    def test_the_file_holds_the_earlier_step_while_the_next_runs(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, ran: list[str]
    ) -> None:
        inner = llm_qa.run_tool
        seen: list[set[str]] = []

        def run_tool(name: str, extra_args: Any = (), lock_fd: int | None = None) -> int:
            seen.append(set(llm_qa.read_provenance(qa_dir)))
            result: int = inner(name, extra_args, lock_fd)
            return result

        monkeypatch.setattr(llm_qa, "run_tool", run_tool)
        llm_qa._run_tools(["lint", "format"], read_only=False)
        assert seen == [set(), {"lint"}]

    def test_the_write_is_atomic_and_leaves_no_temp_file(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        replaced: list[tuple[str, str]] = []
        real_replace = os.replace

        def spy(src: Any, dst: Any) -> None:
            replaced.append((str(src), str(dst)))
            real_replace(src, dst)

        monkeypatch.setattr(llm_qa.os, "replace", spy)
        llm_qa.record_provenance(qa_dir, {"lint": {"passed": True}})
        assert replaced
        assert replaced[0][1] == str(qa_dir / llm_qa.PROVENANCE_FILE)
        assert replaced[0][0] != replaced[0][1]
        assert [p.name for p in qa_dir.iterdir()] == [llm_qa.PROVENANCE_FILE]

    def test_existing_records_are_merged_not_replaced(self, qa_dir: Path) -> None:
        llm_qa.record_provenance(qa_dir, {"lint": {"passed": True}})
        llm_qa.record_provenance(qa_dir, {"format": {"passed": False}})
        assert set(llm_qa.read_provenance(qa_dir)) == {"lint", "format"}


class TestEachStepJudgesItsOwnTree:
    def test_a_change_during_one_step_does_not_taint_the_others(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, ran: list[str], capsys: Any
    ) -> None:
        # run start d1; lint ends d1; format ends d2 (changed during it); smoke_test ends d2.
        monkeypatch.setattr(llm_qa, "worktree_state", _trees("d1", "d1", "d2", "d2"))
        llm_qa._run_tools(["lint", "format", "smoke_test"], read_only=False)
        recorded = llm_qa.read_provenance(qa_dir)
        assert recorded["lint"]["tree_digest"] == "d1"
        assert recorded["format"]["tree_digest"] == "changed-during-run"
        assert recorded["smoke_test"]["tree_digest"] == "d2"
        assert "changed during the run" in capsys.readouterr().out

    def test_an_unreadable_tree_records_nothing(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, ran: list[str], capsys: Any
    ) -> None:
        monkeypatch.setattr(llm_qa, "worktree_state", lambda root: None)
        llm_qa._run_tools(["lint"], read_only=False)
        assert llm_qa.read_provenance(qa_dir) == {}
        assert "nothing is recorded" in capsys.readouterr().out


class TestResume:
    def _first_run(self, tools: list[str]) -> None:
        llm_qa._run_tools(tools, read_only=False)

    def test_passing_results_for_this_tree_are_reused(
        self, qa_dir: Path, ran: list[str], capsys: Any
    ) -> None:
        self._first_run(["lint", "format"])
        ran.clear()
        capsys.readouterr()
        assert llm_qa._run_tools(["lint", "format"], read_only=False, resume=True) == 0
        assert ran == []
        out = capsys.readouterr().out
        assert out.count("♻") == 2
        assert "reused, passed on this tree" in out
        assert "2/2 PASSED" in out

    def test_a_missing_failed_or_stale_record_is_re_run(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, ran: list[str]
    ) -> None:
        self._first_run(["lint", "format", "smoke_test"])
        recorded = llm_qa.read_provenance(qa_dir)
        recorded["format"]["passed"] = False
        recorded["format"]["exit_code"] = 1
        recorded["smoke_test"]["tree_digest"] = "older"
        del recorded["lint"]
        (qa_dir / llm_qa.PROVENANCE_FILE).write_text(json.dumps(recorded), encoding="utf-8")
        ran.clear()
        llm_qa._run_tools(
            ["lint", "format", "smoke_test", "security"], read_only=False, resume=True
        )
        assert ran == ["lint", "format", "smoke_test", "security"]

    def test_a_report_that_is_not_the_one_recorded_is_re_run(
        self, qa_dir: Path, ran: list[str]
    ) -> None:
        self._first_run(["lint"])
        (qa_dir / llm_qa.TOOL_REGISTRY["lint"].json_file).write_text("{}", encoding="utf-8")
        ran.clear()
        llm_qa._run_tools(["lint"], read_only=False, resume=True)
        assert ran == ["lint"]

    def test_only_the_steps_after_the_interruption_run(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, ran: list[str]
    ) -> None:
        self._first_run(["lint", "format"])
        ran.clear()
        llm_qa._run_tools(["lint", "format", "smoke_test"], read_only=False, resume=True)
        assert ran == ["smoke_test"]
        assert set(llm_qa.read_provenance(qa_dir)) == {"lint", "format", "smoke_test"}

    def test_without_resume_everything_runs(self, qa_dir: Path, ran: list[str]) -> None:
        self._first_run(["lint"])
        ran.clear()
        llm_qa._run_tools(["lint"], read_only=False)
        assert ran == ["lint"]

    def test_the_summary_counts_reused_steps_and_marks_their_timing(
        self, qa_dir: Path, ran: list[str], capsys: Any
    ) -> None:
        self._first_run(["lint", "format"])
        recorded = llm_qa.read_provenance(qa_dir)
        recorded["lint"]["duration_seconds"] = 40.0
        (qa_dir / llm_qa.PROVENANCE_FILE).write_text(json.dumps(recorded), encoding="utf-8")
        ran.clear()
        capsys.readouterr()
        llm_qa._run_tools(["lint", "format", "smoke_test"], read_only=False, resume=True)
        out = capsys.readouterr().out
        assert "3/3 PASSED" in out
        timing = out[out.index("TIMING") :].splitlines()
        lint_row = next(line for line in timing if line.split()[:1] == ["lint"])
        assert "40.0s" in lint_row
        assert "reused" in lint_row
        smoke_row = next(line for line in timing if line.split()[:1] == ["smoke_test"])
        assert "reused" not in smoke_row

    def test_a_reused_failure_is_not_possible_a_failing_step_fails_the_run(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, ran: list[str]
    ) -> None:
        self._first_run(["lint"])
        monkeypatch.setattr(llm_qa, "run_tool", lambda name, extra_args=(), lock_fd=None: 1)
        result = llm_qa._run_tools(["lint", "format"], read_only=False, resume=True)
        assert result == llm_qa.EXIT_FAILURE

    def test_changed_tests_with_forwarded_options_is_never_reused(
        self, qa_dir: Path, ran: list[str]
    ) -> None:
        self._first_run(["changed_tests"])
        ran.clear()
        llm_qa._run_tools(
            ["changed_tests"], read_only=False, forwarded=["--base", "x"], resume=True
        )
        assert ran == ["changed_tests"]


class TestTheFlag:
    @pytest.fixture
    def calls(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[dict[str, Any]]:
        recorded: list[dict[str, Any]] = []

        def fake_run_tools(tools: list[str], **kwargs: Any) -> int:
            recorded.append({"tools": tools, **kwargs})
            return 0

        monkeypatch.setattr(llm_qa, "_run_tools", fake_run_tools)
        monkeypatch.setattr(llm_qa, "venv_python", lambda: Path(sys.executable))
        monkeypatch.setattr(llm_qa, "host_lock_path", lambda root: tmp_path / "qa.lock")
        monkeypatch.setenv("FULL_QA_LOCK_WAIT_SECONDS", "0")
        return recorded

    def _main(self, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
        monkeypatch.setattr(sys, "argv", ["llm_qa.py", *argv])
        result: int = llm_qa.main()
        return result

    def test_resume_is_passed_to_the_run_and_the_lock_is_still_taken(
        self, monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]]
    ) -> None:
        assert self._main(monkeypatch, "all", "--resume") == llm_qa.EXIT_SUCCESS
        assert calls[0]["resume"] is True
        assert isinstance(calls[0]["lock_fd"], int)

    def test_without_the_flag_resume_is_off(
        self, monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]]
    ) -> None:
        self._main(monkeypatch, "all")
        assert calls[0]["resume"] is False

    def test_resume_with_read_only_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any]], capsys: Any
    ) -> None:
        assert self._main(monkeypatch, "--read-only", "all", "--resume") == llm_qa.EXIT_FAILURE
        assert calls == []
        assert "--resume" in capsys.readouterr().err


class TestResumeReachesTheTestsTool:
    """Plan 00500 Task 2.3: the tests step checkpoints per leg, and only a resume reuses them."""

    @pytest.fixture
    def extras(self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[str, ...]]:
        seen: dict[str, tuple[str, ...]] = {}

        def run_tool(name: str, extra_args: Any = (), lock_fd: int | None = None) -> int:
            seen[name] = tuple(extra_args)
            (qa_dir / llm_qa.TOOL_REGISTRY[name].json_file).write_text(
                json.dumps(_GREEN), encoding="utf-8"
            )
            return 0

        monkeypatch.setattr(llm_qa, "run_tool", run_tool)
        return seen

    def test_a_resumed_run_tells_the_tests_tool_to_resume_its_legs(
        self, extras: dict[str, tuple[str, ...]]
    ) -> None:
        llm_qa._run_tools(["tests", "lint"], read_only=False, resume=True)
        assert extras == {"tests": ("--resume",), "lint": ()}

    def test_a_normal_run_never_does(self, extras: dict[str, tuple[str, ...]]) -> None:
        llm_qa._run_tools(["tests", "lint"], read_only=False)
        assert extras == {"tests": (), "lint": ()}
