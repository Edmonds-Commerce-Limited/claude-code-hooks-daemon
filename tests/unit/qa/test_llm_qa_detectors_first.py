"""Detectors run before runners, and a detector failure empties the runners' verdicts (G7).

TOOLING-SPEC 4.5: a static detector is cheap and exact, a runner (the test
suite, the project handlers' tests, the live smoke test) is slow and only
means something when the detectors agree the tree is sound. `llm_qa.py` ran
`tests` 6th and counted its result whatever a detector said, so a red detector
sat beside a green test line and the reader weighed the two.

Every tool still runs (Fable's amendment): stopping at the first red detector
would hide the rest of the findings. But once a detector has failed, a runner's
result is marked "not meaningful: detector failed" and is left out of the pass
count, so a green `tests` line next to a red detector cannot be read as a pass.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load() -> Any:
    module_path = PROJECT_ROOT / "scripts" / "qa" / "llm_qa.py"
    spec = importlib.util.spec_from_file_location("llm_qa_for_detector_order_test", module_path)
    assert spec is not None and spec.loader is not None, f"cannot load {module_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


llm_qa = _load()

_GREEN: dict[str, Any] = {"summary": {"passed": True, "total_violations": 0}, "violations": []}
_RED: dict[str, Any] = {
    "summary": {"passed": False, "total_violations": 1},
    "violations": [{"file": "a.py", "line": 3, "rule": "some-rule", "message": "bad"}],
}


class TestTheRegistryOrder:
    def test_every_static_detector_precedes_every_runner(self) -> None:
        names = list(llm_qa.TOOL_REGISTRY)
        runner_positions = [names.index(n) for n in llm_qa.RUNNER_TOOLS]
        detector_positions = [i for i, n in enumerate(names) if n not in llm_qa.RUNNER_TOOLS]
        assert max(detector_positions) < min(runner_positions)

    def test_the_runners_are_the_tools_that_execute_code(self) -> None:
        assert llm_qa.RUNNER_TOOLS == {"tests", "project_handlers", "changed_tests", "smoke_test"}

    def test_every_runner_is_registered(self) -> None:
        assert set(llm_qa.RUNNER_TOOLS) <= set(llm_qa.TOOL_REGISTRY)

    def test_the_smoke_test_stays_last(self) -> None:
        assert list(llm_qa.TOOL_REGISTRY)[-1] == "smoke_test"

    def test_all_runs_detectors_before_runners(self) -> None:
        tools, _ = llm_qa.resolve_tools(["all"])
        flags = [name in llm_qa.RUNNER_TOOLS for name in tools]
        assert flags == sorted(flags)

    def test_changed_runs_detectors_before_runners(self) -> None:
        tools, _ = llm_qa.resolve_tools(["changed"])
        flags = [name in llm_qa.RUNNER_TOOLS for name in tools]
        assert flags == sorted(flags)
        assert tools[-1] == "changed_tests"

    def test_a_named_runner_is_moved_after_the_named_detectors(self) -> None:
        tools, unknown = llm_qa.resolve_tools(["tests", "lint", "format"])
        assert (tools, unknown) == (["lint", "format", "tests"], [])

    def test_the_order_among_detectors_is_kept(self) -> None:
        tools, _ = llm_qa.resolve_tools(["format", "tests", "lint"])
        assert tools == ["format", "lint", "tests"]


class TestARunnerAfterAFailedDetector:
    @pytest.fixture
    def qa_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setattr(llm_qa, "QA_OUTPUT_DIR", tmp_path)
        monkeypatch.setattr(
            llm_qa, "worktree_state", lambda root: {"head": "a" * 40, "tree_digest": "d"}
        )
        monkeypatch.setattr(llm_qa, "ensure_live_daemon", lambda tool: None)
        return tmp_path

    def _run(
        self,
        qa_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        outcomes: dict[str, dict[str, Any]],
        tools: list[str],
    ) -> tuple[int, list[str]]:
        ran: list[str] = []

        def run_tool(name: str, extra_args: Any = (), lock_fd: int | None = None) -> int:
            ran.append(name)
            data = outcomes[name]
            (qa_dir / llm_qa.TOOL_REGISTRY[name].json_file).write_text(
                json.dumps(data), encoding="utf-8"
            )
            return 0 if data["summary"]["passed"] else 1

        monkeypatch.setattr(llm_qa, "run_tool", run_tool)
        return llm_qa._run_tools(tools, read_only=False), ran

    def test_the_runner_still_runs_and_is_marked_not_meaningful(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        code, ran = self._run(
            qa_dir, monkeypatch, {"lint": _RED, "tests": _GREEN}, ["lint", "tests"]
        )
        out = capsys.readouterr().out
        assert code == 1
        assert ran == ["lint", "tests"]
        assert "NOT MEANINGFUL" in out
        assert "detector failed" in out
        assert "lint" in out.split("NOT MEANINGFUL", 1)[1].splitlines()[0]

    def test_the_runner_is_left_out_of_the_pass_count(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        self._run(
            qa_dir,
            monkeypatch,
            {"format": _GREEN, "lint": _RED, "tests": _GREEN},
            ["format", "lint", "tests"],
        )
        verdict = next(
            line for line in capsys.readouterr().out.splitlines() if line.startswith("QA:")
        )
        assert verdict.startswith("QA: 1/3 PASSED, 1/3 FAILED, 1/3 NOT MEANINGFUL")
        assert "lint" in verdict

    def test_a_failed_runner_after_a_failed_detector_is_also_not_meaningful(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        self._run(qa_dir, monkeypatch, {"lint": _RED, "tests": _RED}, ["lint", "tests"])
        verdict = next(
            line for line in capsys.readouterr().out.splitlines() if line.startswith("QA:")
        )
        assert verdict.startswith("QA: 0/2 PASSED, 1/2 FAILED, 1/2 NOT MEANINGFUL")

    def test_the_provenance_record_keeps_the_real_result(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`--resume` must reuse a runner that really passed, whatever a detector said."""
        self._run(qa_dir, monkeypatch, {"lint": _RED, "tests": _GREEN}, ["lint", "tests"])
        recorded = llm_qa.read_provenance(qa_dir)
        assert recorded["tests"]["passed"] is True
        assert recorded["lint"]["passed"] is False

    def test_a_green_detector_leaves_the_runner_meaningful(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        code, _ = self._run(
            qa_dir, monkeypatch, {"lint": _GREEN, "tests": _GREEN}, ["lint", "tests"]
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "NOT MEANINGFUL" not in out
        assert "QA: 2/2 PASSED" in out

    def test_a_failed_runner_after_green_detectors_is_a_plain_failure(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        code, _ = self._run(
            qa_dir, monkeypatch, {"lint": _GREEN, "tests": _RED}, ["lint", "tests"]
        )
        out = capsys.readouterr().out
        assert code == 1
        assert "NOT MEANINGFUL" not in out
        assert "QA: 1/2 PASSED, 1/2 FAILED" in out

    def test_a_runner_alone_is_judged_normally(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        code, _ = self._run(qa_dir, monkeypatch, {"tests": _GREEN}, ["tests"])
        assert code == 0
        assert "NOT MEANINGFUL" not in capsys.readouterr().out

    def test_the_marked_line_no_longer_shows_a_pass_icon(
        self, qa_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
    ) -> None:
        self._run(qa_dir, monkeypatch, {"lint": _RED, "tests": _GREEN}, ["lint", "tests"])
        marked = next(
            line
            for line in capsys.readouterr().out.splitlines()
            if "tests:" in line and "NOT MEANINGFUL" in line
        )
        assert "✅" not in marked
