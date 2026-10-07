"""Each ``llm_qa.py`` step records its wall-clock time and the run prints a summary (Plan 00500).

The provenance record is the one place a tool's result is already stored per
tool, tied to a tree and read by ``--read-only``, so the timing lives there too
rather than in a second file that could disagree with it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
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


llm_qa = _load("llm_qa.py", "llm_qa_for_timing_test")

_HEAD = "a" * 40
_GREEN: dict[str, Any] = {"summary": {"passed": True}, "passed": True}
_EPOCH = datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC)


def _state() -> dict[str, str]:
    return {"head": _HEAD, "tree_digest": "d1"}


def _monotonic(readings: list[float]) -> Callable[[], float]:
    """A clock that returns each reading in turn: no real time passes."""
    values: Iterator[float] = iter(readings)
    return lambda: next(values)


def _wall(offsets: list[float]) -> Callable[[], datetime]:
    values: Iterator[float] = iter(offsets)
    return lambda: _EPOCH + timedelta(seconds=next(values))


class TestTheRecordCarriesTiming:
    def test_start_end_and_duration_are_recorded(self) -> None:
        timing = llm_qa.StepTiming(
            started_at="2026-10-07T12:00:00+00:00",
            ended_at="2026-10-07T12:00:12+00:00",
            duration_seconds=12.34,
        )
        record = llm_qa.run_record(
            _state(), exit_code=0, passed=True, output_sha256=None, timing=timing
        )
        assert record["started_at"] == "2026-10-07T12:00:00+00:00"
        assert record["ended_at"] == "2026-10-07T12:00:12+00:00"
        assert record["duration_seconds"] == 12.3

    def test_a_record_without_timing_has_no_timing_keys(self) -> None:
        record = llm_qa.run_record(_state(), exit_code=0, passed=True, output_sha256=None)
        assert "duration_seconds" not in record


class TestAStepIsTimed:
    @pytest.fixture
    def qa_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setattr(llm_qa, "QA_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr(llm_qa, "worktree_state", lambda root: _state())

        def run_tool(name: str, extra_args: Any = (), lock_fd: int | None = None) -> int:
            path = tmp_path / llm_qa.TOOL_REGISTRY[name].json_file
            path.write_text(json.dumps(_GREEN), encoding="utf-8")
            return 0

        monkeypatch.setattr(llm_qa, "run_tool", run_tool)
        return tmp_path

    def test_each_tool_records_its_wall_clock_and_duration(self, qa_dir: Path) -> None:
        llm_qa._run_tools(
            ["lint", "format"],
            read_only=False,
            clock=_monotonic([100.0, 107.25, 107.25, 110.0]),
            wall_clock=_wall([0, 7.25, 7.25, 10]),
        )
        recorded = llm_qa.read_provenance(qa_dir)
        assert recorded["lint"]["started_at"] == _EPOCH.isoformat()
        assert recorded["lint"]["ended_at"] == (_EPOCH + timedelta(seconds=7.25)).isoformat()
        assert recorded["lint"]["duration_seconds"] == 7.2
        assert recorded["format"]["duration_seconds"] == 2.8

    def test_a_failing_tool_is_timed_too(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(llm_qa, "run_tool", lambda name, extra_args=(), lock_fd=None: 1)
        llm_qa._run_tools(
            ["lint"],
            read_only=False,
            clock=_monotonic([0.0, 3.0]),
            wall_clock=_wall([0, 3]),
        )
        assert llm_qa.read_provenance(qa_dir)["lint"]["duration_seconds"] == 3.0


class TestTheSummary:
    def test_it_lists_slowest_first_with_a_total(self) -> None:
        text = llm_qa.format_timing_summary({"lint": 2.0, "tests": 3600.5, "format": 0.4})
        lines = text.splitlines()
        assert lines[0].startswith("TIMING")
        names = [line.split()[0] for line in lines[1:-1]]
        assert names == ["tests", "lint", "format"]
        assert "3600.5s" in lines[1]
        assert lines[-1].split() == ["total", "3602.9s"]

    def test_a_run_prints_it_after_the_verdicts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: Any,
    ) -> None:
        monkeypatch.setattr(llm_qa, "QA_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr(llm_qa, "worktree_state", lambda root: _state())

        def run_tool(name: str, extra_args: Any = (), lock_fd: int | None = None) -> int:
            (tmp_path / llm_qa.TOOL_REGISTRY[name].json_file).write_text(
                json.dumps(_GREEN), encoding="utf-8"
            )
            return 0

        monkeypatch.setattr(llm_qa, "run_tool", run_tool)
        llm_qa._run_tools(
            ["lint", "format"],
            read_only=False,
            clock=_monotonic([0.0, 5.0, 5.0, 65.0]),
            wall_clock=_wall([0, 5, 5, 65]),
        )
        out = capsys.readouterr().out
        assert out.index("QA: ") < out.index("TIMING")
        timing = out[out.index("TIMING") :].splitlines()
        assert timing[1].split() == ["format", "60.0s"]
        assert timing[2].split() == ["lint", "5.0s"]
        assert timing[3].split() == ["total", "65.0s"]


class TestReadOnly:
    @pytest.fixture
    def qa_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setattr(llm_qa, "QA_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr(llm_qa, "worktree_state", lambda root: _state())
        return tmp_path

    def _record(self, qa_dir: Path, name: str, timing: Any) -> None:
        report = qa_dir / llm_qa.TOOL_REGISTRY[name].json_file
        report.write_text(json.dumps(_GREEN), encoding="utf-8")
        record = llm_qa.run_record(
            _state(),
            exit_code=0,
            passed=True,
            output_sha256=llm_qa.output_digest(report),
            timing=timing,
        )
        llm_qa.record_provenance(qa_dir, {name: record})

    def test_durations_are_shown_when_present(self, qa_dir: Path, capsys: Any) -> None:
        timing = llm_qa.StepTiming("2026-10-07T12:00:00+00:00", "2026-10-07T12:01:00+00:00", 60.0)
        self._record(qa_dir, "lint", timing)
        assert llm_qa._run_tools(["lint"], read_only=True) == llm_qa.EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "TIMING" in out
        assert "60.0s" in out

    def test_older_results_with_no_duration_are_tolerated(self, qa_dir: Path, capsys: Any) -> None:
        self._record(qa_dir, "lint", None)
        assert llm_qa._run_tools(["lint"], read_only=True) == llm_qa.EXIT_SUCCESS
        out = capsys.readouterr().out
        assert "TIMING" not in out
        assert "1/1 PASSED" in out
