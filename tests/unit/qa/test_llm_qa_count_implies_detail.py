"""A non-zero count must imply reachable detail, for EVERY report (Plan 00229).

Plan 00226 fixed one instance of this: the `tests` report said "N failed" and
named nothing, because producer and consumer disagreed on one token. An agent
reading that artifact cannot tell "no detail exists" from "the detail was
dropped", so the only recourse is a full re-run — and during Plan 00224 a
re-run failed to reproduce an order-dependent failure, which was therefore
never identified.

That fix was per-report. This is the class guard Plan 00226 named as its own
follow-up: twenty reports can take the same shape and nothing asked the general
question.

WHY THE HINT IS THE CONTRACT. Every `TOOL_REGISTRY` entry carries a `jq_hint`
that is PRINTED TO THE OPERATOR beneath the summary line:

    ✅ magic_values: 0 violations
       magic_values.json | jq '.violations[] | {file, line, rule, message}'

That hint is a promise about where the detail lives. Deriving the detail array
from it — rather than from a hand-maintained table — keeps one source of truth
and covers a newly added report without anyone remembering to extend a list.
A hardcoded list would be blind to exactly the report nobody thought about,
which is the failure mode Plan 00228 designed against.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest


def _load_llm_qa() -> Any:
    """Import `scripts/qa/llm_qa.py`, which is a script rather than a module."""
    project_root = Path(__file__).resolve().parents[3]
    module_path = project_root / "scripts" / "qa" / "llm_qa.py"
    spec = importlib.util.spec_from_file_location("llm_qa_under_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


llm_qa = _load_llm_qa()

# The leading `.<key>[]` of a jq hint — the array the operator is sent to.
# `jq '.violations[] | {file, line}'` -> "violations".
_HINT_ARRAY_PATTERN = re.compile(r"\.(?P<key>\w+)\[\]")

# Summary keys that count BAD things. A report is required to have detail only
# when one of these is non-zero; `passed`/`total_probes` say nothing about it.
_FAILURE_COUNT_KEYS: tuple[str, ...] = (
    "total_violations",
    "total_errors",
    "total_issues",
    "failed",
    "failed_probes",
)

# Reports whose hint legitimately names no detail array. Each entry must state
# why, because an exemption without a reason is indistinguishable from an
# unnoticed hole (Plan 00228's exemption-map pattern).
#
# Empty by design: Plan 00229 Decision 1 REJECTED exempting `tests`, the only
# candidate. It has a `.tests[]` array — that is where Plan 00226's missing
# names lived — so its hint was fixed to point at it rather than the report
# being excused. Exempting the one report with a proven history of losing
# detail would have preserved the exact blindness this guard exists to remove.
_REPORTS_WITHOUT_DETAIL: dict[str, str] = {}


def _detail_array_key(jq_hint: str) -> str | None:
    """The array a hint sends the operator to, or None if it names none."""
    match = _HINT_ARRAY_PATTERN.search(jq_hint)
    return match.group("key") if match else None


def _failure_count(summary: dict[str, Any]) -> int:
    """Total of whichever failure-count keys this report's summary carries."""
    return sum(int(summary.get(key, 0)) for key in _FAILURE_COUNT_KEYS)


def _detail_is_reachable(report: dict[str, Any], jq_hint: str) -> bool:
    """Would an operator following the printed hint actually see something?"""
    key = _detail_array_key(jq_hint)
    if key is None:
        return False
    return bool(report.get(key))


def _in_scope_reports() -> dict[str, Any]:
    return {
        name: config
        for name, config in llm_qa.TOOL_REGISTRY.items()
        if name not in _REPORTS_WITHOUT_DETAIL
    }


class TestTheGuardIsNotVacuous:
    """A guard that cannot fail proves nothing."""

    def test_the_registry_is_discovered_not_hardcoded(self) -> None:
        assert len(llm_qa.TOOL_REGISTRY) > 1

    def test_the_in_scope_set_is_not_empty(self) -> None:
        assert _in_scope_reports()

    def test_every_exemption_names_a_real_report(self) -> None:
        stale = set(_REPORTS_WITHOUT_DETAIL) - set(llm_qa.TOOL_REGISTRY)

        assert not stale, f"exemptions name reports that no longer exist: {sorted(stale)}"

    def test_every_exemption_states_a_reason(self) -> None:
        unexplained = [
            name for name, reason in _REPORTS_WITHOUT_DETAIL.items() if not reason.strip()
        ]

        assert not unexplained, f"exemptions without a stated reason: {unexplained}"


class TestTheGuardHasTeeth:
    """Prove the guard rejects the shape it exists to catch."""

    def test_a_count_with_an_empty_detail_array_is_rejected(self) -> None:
        """The Plan 00226 shape: a number, and nothing behind it."""
        report = {"summary": {"total_violations": 3}, "violations": []}

        assert _failure_count(report["summary"]) > 0
        assert _detail_is_reachable(report, "jq '.violations[]'") is False

    def test_a_count_with_a_populated_detail_array_is_accepted(self) -> None:
        report = {"summary": {"total_violations": 1}, "violations": [{"file": "x.py"}]}

        assert _detail_is_reachable(report, "jq '.violations[]'") is True

    def test_a_hint_naming_no_array_is_rejected(self) -> None:
        """`jq '.summary'` sends the reader back to the count they already had.

        This is the exact Plan 00226 blind spot, and the reason Decision 1
        fixed the `tests` hint instead of exempting the report.
        """
        report = {"summary": {"failed": 2}, "tests": [{"name": "t", "outcome": "failed"}]}

        assert _detail_is_reachable(report, "jq '.summary'") is False

    def test_zero_count_needs_no_detail(self) -> None:
        """A clean report is not required to carry an empty array."""
        report: dict[str, Any] = {"summary": {"total_violations": 0}}

        assert _failure_count(report["summary"]) == 0


@pytest.mark.parametrize("name", sorted(_in_scope_reports()))
def test_every_report_hint_names_a_detail_array(name: str) -> None:
    """Every in-scope report must send the operator somewhere with detail.

    Checked against the REGISTRY rather than against whatever `untracked/qa/`
    happens to hold: a guard driven by a real run only fires when QA is already
    red, which is precisely when nobody is reading it.
    """
    jq_hint = llm_qa.TOOL_REGISTRY[name].jq_hint

    assert _detail_array_key(jq_hint) is not None, (
        f"{name}'s jq_hint ({jq_hint!r}) names no detail array, so an operator "
        f"following it to explain a non-zero count is sent nowhere useful. "
        f"Point it at the array holding the detail, or add {name} to "
        f"_REPORTS_WITHOUT_DETAIL with a reason."
    )


# Array keys used across the QA report schemas. Probed to discover which array
# a summariser actually reads, since that cannot be read off the registry.
_CANDIDATE_DETAIL_KEYS: tuple[str, ...] = (
    "violations",
    "errors",
    "issues",
    "tests",
    "probes",
)

# A detail row rich enough for any summariser to render from: `tests` filters
# on `outcome`, and the others read file/line/message shaped fields.
_DETAIL_ROW: dict[str, Any] = {
    "name": "tests/unit/test_x.py::test_y",
    "outcome": "failed",
    "file": "src/x.py",
    "line": 1,
    "message": "boom",
}


def _arrays_the_summarizer_reads(name: str) -> set[str]:
    """Which detail arrays actually change this report's rendered summary."""
    summarizer = llm_qa.SUMMARIZERS[name]
    baseline = summarizer({"summary": {}})
    reads = set()
    for key in _CANDIDATE_DETAIL_KEYS:
        if summarizer({"summary": {}, key: [_DETAIL_ROW]}) != baseline:
            reads.add(key)
    return reads


@pytest.mark.parametrize("name", sorted(_in_scope_reports()))
def test_summarizer_detail_agrees_with_the_hint(name: str) -> None:
    """A report that renders detail inline must read the array its hint names.

    Plan 00226's defect lived in exactly this gap: the summariser read
    `.tests[]` while the hint pointed at `.summary`, so the two disagreed about
    where the detail was and neither surface could show the other was wrong.

    Most summarisers read no array at all — 19 of 20 render a count and
    delegate to the hint, which is a deliberate design that keeps the artifact
    small. That is fine. What must never happen is a summariser rendering
    detail from an array the operator is never sent to.
    """
    key = _detail_array_key(llm_qa.TOOL_REGISTRY[name].jq_hint)
    assert key is not None, f"{name} has no hint array; the sibling test covers that"

    reads = _arrays_the_summarizer_reads(name)

    assert reads <= {key}, (
        f"{name}'s summariser renders detail from {sorted(reads - {key})}, but its "
        f"jq_hint sends the operator to '.{key}[]'. Point the hint at the array "
        f"the summariser reads, so the two cannot disagree about where detail lives."
    )
