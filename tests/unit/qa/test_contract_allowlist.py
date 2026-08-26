"""Tests for scripts/qa/contract_allowlist.py — the shared allowlist protocol
used by check_hook_contract.py and check_input_contract.py (Plan 00273)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_SCRIPTS_QA_DIR = Path(__file__).resolve().parents[3] / "scripts" / "qa"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "contract_allowlist", _SCRIPTS_QA_DIR / "contract_allowlist.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("contract_allowlist", module)
    spec.loader.exec_module(module)
    return module


cal = _load_module()


def _finding(subject: str = "f1") -> object:
    return cal.Finding(rule="some-rule", event="Stop", subject=subject, message="m")


class TestFinding:
    def test_finding_id_and_dict(self) -> None:
        finding = cal.Finding(rule="r", event="E", subject="s", message="m")
        assert finding.finding_id == "r:E:s"
        assert (
            cal.Finding(**{k: v for k, v in finding.to_dict().items() if k != "id"}).finding_id
            == "r:E:s"
        )


class TestReport:
    def test_passed_and_to_dict(self) -> None:
        report = cal.Report(violations=[_finding()], allowlisted=[])
        assert not report.passed
        payload = report.to_dict()
        assert payload["summary"]["total_violations"] == 1
        assert cal.Report().passed


class TestLoadAllowlistFile:
    def test_absent_file_is_empty(self, tmp_path: Path) -> None:
        assert cal.load_allowlist_file(tmp_path / "nope.yaml") == []

    def test_entries_loaded(self, tmp_path: Path) -> None:
        path = tmp_path / "a.yaml"
        path.write_text('entries:\n  - id: "x"\n    reason: "r"\n    link: "l"\n')
        assert cal.load_allowlist_file(path) == [{"id": "x", "reason": "r", "link": "l"}]

    def test_non_list_entries_is_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "a.yaml"
        path.write_text("entries: {}\n")
        assert cal.load_allowlist_file(path) == []


class TestApplyAllowlist:
    def test_match_moves_finding_to_allowlisted(self) -> None:
        finding = _finding()
        entry = {"id": finding.finding_id, "reason": "r", "link": "l"}
        remaining, allowlisted, problems = cal.apply_allowlist([finding], [entry])
        assert remaining == [] and problems == []
        assert allowlisted[0]["reason"] == "r"

    def test_stale_entry_is_a_problem(self) -> None:
        entry = {"id": "no:such:finding", "reason": "r", "link": "l"}
        _remaining, _allowlisted, problems = cal.apply_allowlist([], [entry])
        assert problems[0].rule == cal.RULE_STALE_ALLOWLIST

    def test_malformed_entry_missing_reason_or_link(self) -> None:
        for entry in ({"id": "x", "link": "l"}, {"id": "x", "reason": "r"}, {}):
            _, _, problems = cal.apply_allowlist([], [entry])
            assert problems[0].rule == cal.RULE_MALFORMED_ALLOWLIST
