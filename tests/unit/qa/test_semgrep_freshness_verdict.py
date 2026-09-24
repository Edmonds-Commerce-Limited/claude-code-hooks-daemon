"""Pin the ``freshness-verdict-read-piecemeal`` semgrep rule (Plan 00415).

A running daemon reports two fingerprints, code and config, and a consumer
that reads only one of them is no better off than before Plan 00415: the half
it skipped drifts unseen and the verdict says FRESH. The rule bans reading
either key out of a health payload anywhere but the module that owns the
combined verdict. A semgrep rule that fails to bind still loads and reports
success, so it is pinned against planted defects here, with expectations
taken from markers IN the fixture rather than duplicated.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RULE_FILE = _REPO_ROOT / "scripts" / "qa" / "semgrep" / "freshness-verdict.yaml"
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "semgrep" / "freshness_verdict_reads.py"

_HIT_MARKER = "# EXPECT-HIT"
_CLEAN_MARKER = "# EXPECT-CLEAN"

# Minimum planted cases, so an emptied fixture cannot make this suite vacuous.
_MIN_PLANTED_DEFECTS = 5
_MIN_PLANTED_CLEAN = 3

_SEMGREP_TIMEOUT_SECONDS = 120

# A real marker is a trailing comment on a line of code; a line that merely
# talks about a marker (the fixture's docstring) is prose.
_PROSE_LINE_PREFIXES = ("#", "*", '"', "'")


def _marked_lines(marker: str) -> set[int]:
    """1-based line numbers where ``marker`` tags a line of CODE."""
    lines = _FIXTURE.read_text(encoding="utf-8").splitlines()
    tagged: set[int] = set()
    for number, text in enumerate(lines, start=1):
        position = text.find(marker)
        if position <= 0:
            continue
        preceding = text[:position].strip()
        if not preceding or preceding.startswith(_PROSE_LINE_PREFIXES):
            continue
        tagged.add(number)
    return tagged


def _semgrep_executable() -> Path:
    """The semgrep binary from the same venv running these tests."""
    return Path(sys.executable).parent / "semgrep"


def _run_rule() -> set[int]:
    """Run the rule over the fixture; return the reported 1-based line numbers.

    SECURITY: fixed argv, no shell, invoking a declared dev-dependency binary
    resolved from this venv.
    """
    completed = subprocess.run(
        [
            str(_semgrep_executable()),
            "scan",
            "--config",
            str(_RULE_FILE),
            "--metrics=off",
            "--disable-version-check",
            "--quiet",
            "--json",
            str(_FIXTURE),
        ],
        capture_output=True,
        text=True,
        timeout=_SEMGREP_TIMEOUT_SECONDS,
        check=False,
    )
    if not completed.stdout.strip():
        raise AssertionError(f"semgrep produced no output. stderr:\n{completed.stderr}")
    payload = json.loads(completed.stdout)
    return {result["start"]["line"] for result in payload.get("results", [])}


@pytest.fixture(scope="module")
def reported_lines() -> set[int]:
    """Run semgrep once and share the result across the assertions below."""
    if not _semgrep_executable().exists():
        pytest.fail(
            "semgrep is not installed in this venv. It is a declared dev "
            "dependency; install with: uv pip install -e '.[dev]'"
        )
    return _run_rule()


class TestFreshnessVerdictReadPiecemealRule:
    """Pin the rule against planted defects and against correct code."""

    def test_fixture_actually_contains_defects_to_find(self) -> None:
        assert len(_marked_lines(_HIT_MARKER)) >= _MIN_PLANTED_DEFECTS
        assert len(_marked_lines(_CLEAN_MARKER)) >= _MIN_PLANTED_CLEAN

    def test_every_planted_defect_is_reported(self, reported_lines: set[int]) -> None:
        missed = _marked_lines(_HIT_MARKER) - reported_lines
        assert not missed, (
            f"the rule is BLIND to planted defects on lines {sorted(missed)}. "
            "Do not 'fix' this by editing the fixture."
        )

    def test_correct_code_is_not_reported(self, reported_lines: set[int]) -> None:
        false_positives = _marked_lines(_CLEAN_MARKER) & reported_lines
        assert (
            not false_positives
        ), f"the rule fires on correct code at lines {sorted(false_positives)}."

    def test_reports_nothing_outside_the_marked_lines(self, reported_lines: set[int]) -> None:
        unexplained = reported_lines - _marked_lines(_HIT_MARKER)
        assert not unexplained, f"unexpected findings on lines {sorted(unexplained)}"
