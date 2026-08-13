"""Unit tests for llm_qa's failing-test naming (Plan 00226).

`scripts/qa/run_tests.sh` extracts the failing node ids; `_summarize_tests` in
`scripts/qa/llm_qa.py` is what actually SHOWS them. The parser is covered by
tests/unit/qa/test_pytest_text_report.py — these tests cover the rendering half,
which is the surface an LLM reads on every QA run.

The last test here is the important one: it binds the producer's outcome token
to the consumer's filter. `_summarize_tests` selects records whose ``outcome``
equals a literal string, so if the producer ever wrote a different token the
summary would print "N failed" and silently name nothing — reintroducing exactly
the blindness this plan fixed, with the count still looking healthy.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import types

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "qa"
RUN_TESTS_SH = SCRIPTS_DIR / "run_tests.sh"

_FAILED_SECTION_MARKER = "failed:"
_OVERFLOW_MARKER = "... and"

# The record shape run_tests.sh emits: {"name": <node id>, "outcome": "<token>"}.
# Captured from the script itself so the two sides cannot drift apart silently.
_PRODUCER_OUTCOME_PATTERN = re.compile(r'"outcome":\s*"([a-z]+)"')


def _load_llm_qa() -> types.ModuleType:
    """Dynamically import llm_qa module (not on sys.path by default)."""
    spec = importlib.util.spec_from_file_location("llm_qa", SCRIPTS_DIR / "llm_qa.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report(tests: list[dict[str, str]], failed: int) -> dict[str, Any]:
    """Build a tests.json-shaped report with the given per-test records."""
    return {
        "summary": {"total": 10, "passed": 10 - failed, "failed": failed, "skipped": 0},
        "tests": tests,
        "coverage": {"percent_covered": 95.0},
    }


def _failed_records(node_ids: list[str], outcome: str = "failed") -> list[dict[str, str]]:
    return [{"name": node_id, "outcome": outcome} for node_id in node_ids]


class TestSummarizeTestsNamesFailures:
    """A red result must say WHICH tests failed, not only how many."""

    def test_a_green_run_names_nothing(self) -> None:
        llm_qa = _load_llm_qa()

        summary = llm_qa._summarize_tests(_report([], failed=0))

        assert _FAILED_SECTION_MARKER not in summary
        assert "0 failed" in summary

    def test_failing_node_ids_appear_in_the_summary(self) -> None:
        llm_qa = _load_llm_qa()
        node_ids = ["tests/unit/test_a.py::TestThing::test_one", "tests/unit/test_b.py::test_two"]

        summary = llm_qa._summarize_tests(_report(_failed_records(node_ids), failed=2))

        assert _FAILED_SECTION_MARKER in summary
        for node_id in node_ids:
            assert node_id in summary

    def test_passing_records_are_not_named(self) -> None:
        """A green test in the record set must not be reported as a failure."""
        llm_qa = _load_llm_qa()
        tests = [
            {"name": "tests/unit/test_a.py::test_broke", "outcome": "failed"},
            {"name": "tests/unit/test_b.py::test_fine", "outcome": "passed"},
        ]

        summary = llm_qa._summarize_tests(_report(tests, failed=1))

        assert "test_broke" in summary
        assert "test_fine" not in summary

    def test_a_mass_breakage_is_capped_and_says_how_many_were_hidden(self) -> None:
        llm_qa = _load_llm_qa()
        cap = llm_qa._MAX_NAMED_FAILURES
        overflow = 7
        node_ids = [f"tests/unit/test_x.py::test_{index}" for index in range(cap + overflow)]

        summary = llm_qa._summarize_tests(_report(_failed_records(node_ids), failed=len(node_ids)))

        assert summary.count("tests/unit/test_x.py::test_") == cap
        assert f"{_OVERFLOW_MARKER} {overflow} more" in summary

    def test_records_without_a_name_are_skipped_not_rendered_blank(self) -> None:
        """Degraded input must not produce empty bullet lines."""
        llm_qa = _load_llm_qa()
        tests = [{"name": "", "outcome": "failed"}, {"name": "tests/t.py::ok", "outcome": "failed"}]

        summary = llm_qa._summarize_tests(_report(tests, failed=2))

        assert "tests/t.py::ok" in summary
        assert summary.count(_FAILED_SECTION_MARKER) == 1


class TestProducerAndConsumerAgreeOnTheOutcomeToken:
    """The half that writes the record and the half that reads it must match.

    Without this, a one-word change on either side turns the fix off silently:
    the count keeps reporting failures and the names quietly stop appearing.
    """

    def test_run_tests_sh_declares_an_outcome_token(self) -> None:
        """Vacuity guard — the coupling test below is meaningless if this is empty."""
        tokens = _PRODUCER_OUTCOME_PATTERN.findall(RUN_TESTS_SH.read_text())

        assert tokens, "run_tests.sh no longer emits a literal outcome token; update this guard"

    def test_the_summariser_renders_the_token_the_producer_writes(self) -> None:
        llm_qa = _load_llm_qa()
        tokens = set(_PRODUCER_OUTCOME_PATTERN.findall(RUN_TESTS_SH.read_text()))
        node_id = "tests/unit/test_coupling.py::test_case"

        for token in tokens:
            summary = llm_qa._summarize_tests(_report(_failed_records([node_id], token), failed=1))

            assert node_id in summary, (
                f"run_tests.sh writes outcome={token!r} but _summarize_tests does not "
                f"render it — a red QA run would report a count and name nothing"
            )

    def test_the_guard_would_fail_on_a_token_mismatch(self) -> None:
        """Teeth: prove the coupling test can actually fail."""
        llm_qa = _load_llm_qa()
        node_id = "tests/unit/test_coupling.py::test_case"

        summary = llm_qa._summarize_tests(_report(_failed_records([node_id], "errored"), failed=1))

        assert node_id not in summary
