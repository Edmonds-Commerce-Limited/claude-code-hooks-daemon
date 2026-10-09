"""A failing tool's summary names its first findings, their IDs and the absolute report path (G8).

TOOLING-SPEC 4.4 / DETECTOR-SPEC 5.3: the entry point prints the identifier of
every finding, unaltered, and says where the full output is. `llm_qa.py` printed
a count and a JSON file NAME, so the identifier reached the practitioner only
if they opened the JSON, and the filename alone did not say which directory.
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
    spec = importlib.util.spec_from_file_location("llm_qa_for_findings_test", module_path)
    assert spec is not None and spec.loader is not None, f"cannot load {module_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


llm_qa = _load()


def _report(violations: list[dict[str, Any]], *, passed: bool = False) -> dict[str, Any]:
    return {
        "summary": {"passed": passed, "total_violations": len(violations)},
        "violations": violations,
    }


def _violation(index: int) -> dict[str, Any]:
    return {
        "file": f"src/mod{index}.py",
        "line": index,
        "rule": f"rule-{index}",
        "message": f"finding number {index}",
    }


@pytest.fixture
def qa_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(llm_qa, "QA_OUTPUT_DIR", tmp_path)
    return tmp_path


def _summary(qa_dir: Path, data: dict[str, Any], tool: str = "error_hiding") -> str:
    (qa_dir / llm_qa.TOOL_REGISTRY[tool].json_file).write_text(json.dumps(data), encoding="utf-8")
    return str(llm_qa.summarize_tool(tool, exit_code=1 if not data["summary"]["passed"] else 0)[1])


class TestAFailingToolNamesItsFindings:
    def test_each_finding_shows_its_id_location_and_message(self, qa_dir: Path) -> None:
        text = _summary(qa_dir, _report([_violation(1)]))
        assert "rule-1" in text
        assert "src/mod1.py:1" in text
        assert "finding number 1" in text

    def test_only_the_first_findings_are_shown_and_the_rest_counted(self, qa_dir: Path) -> None:
        limit = llm_qa.MAX_FINDINGS_SHOWN
        text = _summary(qa_dir, _report([_violation(i) for i in range(1, limit + 4)]))
        assert f"rule-{limit}" in text
        assert f"rule-{limit + 1}" not in text
        assert f"first {limit} of {limit + 3}" in text

    def test_the_absolute_report_path_is_printed(self, qa_dir: Path) -> None:
        text = _summary(qa_dir, _report([_violation(1)]))
        assert str(qa_dir / "error_hiding.json") in text
        assert Path(str(qa_dir / "error_hiding.json")).is_absolute()

    def test_a_long_message_is_cut(self, qa_dir: Path) -> None:
        long = {**_violation(1), "message": "x" * 500}
        text = _summary(qa_dir, _report([long]))
        assert "x" * 500 not in text

    def test_the_id_is_printed_unaltered(self, qa_dir: Path) -> None:
        odd = {**_violation(1), "rule": "public-pattern:aws-key"}
        assert "public-pattern:aws-key" in _summary(qa_dir, _report([odd]))

    def test_a_finding_may_name_its_id_under_check_id_or_path(self, qa_dir: Path) -> None:
        item = {"check_id": "plan-doc-size", "path": "CLAUDE/Plan/x/PLAN.md", "message": "big"}
        data = {
            "summary": {"passed": False, "total_issues": 1, "block": 1, "advise": 0},
            "findings": [item],
        }
        text = _summary(qa_dir, data, tool="plan_qa")
        assert "plan-doc-size" in text
        assert "CLAUDE/Plan/x/PLAN.md" in text

    def test_a_finding_with_no_id_is_skipped_not_invented(self, qa_dir: Path) -> None:
        text = _summary(qa_dir, _report([{"row": "r1", "detail": "bad"}]))
        assert "FINDINGS" not in text
        assert str(qa_dir / "error_hiding.json") in text


class TestTheExplainHintIsOnlyForIdsThatResolve:
    """N2: `--explain <ID>` fails for a wrapped tool's own ID, so it is not offered for one."""

    def test_a_registry_id_gets_the_hint(self, qa_dir: Path) -> None:
        item = {**_violation(1), "rule": "silent-pass"}
        assert "--explain" in _summary(qa_dir, _report([item]))

    def test_an_id_no_checker_registers_gets_no_hint(self, qa_dir: Path) -> None:
        item = {**_violation(1), "rule": "F401"}
        text = _summary(qa_dir, _report([item]))
        assert "F401" in text
        assert "--explain" not in text

    def test_a_family_id_gets_the_hint(self, qa_dir: Path) -> None:
        item = {**_violation(1), "rule": "public-pattern:aws-key"}
        assert "--explain" in _summary(qa_dir, _report([item]))

    def test_a_mixed_list_gets_it_with_the_limit_stated(self, qa_dir: Path) -> None:
        items = [{**_violation(1), "rule": "silent-pass"}, {**_violation(2), "rule": "F401"}]
        text = _summary(qa_dir, _report(items))
        assert "--explain" in text
        assert "checker" in text.split("--explain", 1)[1].splitlines()[0]


class TestAPassingToolStaysQuiet:
    def test_no_findings_block_and_no_extra_path_line(self, qa_dir: Path) -> None:
        text = _summary(qa_dir, _report([], passed=True))
        assert "full report" not in text
        assert len(text.strip().splitlines()) == 2


class TestAFailureWithNoDetail:
    def test_the_detail_missing_warning_still_prints_beside_the_path(self, qa_dir: Path) -> None:
        text = _summary(qa_dir, {"summary": {"passed": False, "total_violations": 2}})
        assert "DETAIL MISSING" in text
        assert str(qa_dir / "error_hiding.json") in text
