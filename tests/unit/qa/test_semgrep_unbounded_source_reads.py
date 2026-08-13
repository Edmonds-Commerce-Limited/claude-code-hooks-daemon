"""The guard's guard: prove the semgrep rules are not silently blind.

Plan 00232. A semgrep rule that fails to bind still LOADS, still RUNS, and
still reports success — it just matches nothing. That is indistinguishable
from a clean tree, and it is not hypothetical: the first draft of
``unbounded-transcript-file-read`` fired on ZERO of four planted defects
because a ``pattern-either`` nested inside a ``patterns`` block does not bind
its metavariables. Nothing in the QA suite would ever have noticed.

So the rule is pinned against a fixture of deliberately defective code, with
expectations taken from markers IN that fixture rather than duplicated here —
a copy would drift, and a drifted copy is how a guard goes quiet.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RULE_FILE = _REPO_ROOT / "scripts" / "qa" / "semgrep" / "unbounded-source-reads.yaml"
_FIXTURE = _REPO_ROOT / "tests" / "fixtures" / "semgrep" / "unbounded_transcript_reads.py"

_HIT_MARKER = "# EXPECT-HIT"
_CLEAN_MARKER = "# EXPECT-CLEAN"

# Minimum planted cases, so an emptied fixture cannot make this suite vacuous.
_MIN_PLANTED_DEFECTS = 4
_MIN_PLANTED_CLEAN = 2

# Generous: semgrep on one small file is fast, but CI machines are not.
_SEMGREP_TIMEOUT_SECONDS = 120


# A line that merely TALKS about a marker (the fixture's own docstring explains
# them) must not be mistaken for a tagged line. A real marker is a trailing
# comment on a line of code, so it is preceded by actual code.
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
    resolved from this venv — the same trusted-tool pattern the other QA
    scripts use for ruff/mypy/bandit.
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


class TestUnboundedTranscriptReadRule:
    """Pin the rule against planted defects and against correct code."""

    def test_fixture_actually_contains_defects_to_find(self) -> None:
        """Guard the guard's guard — an empty fixture would pass everything."""
        assert len(_marked_lines(_HIT_MARKER)) >= _MIN_PLANTED_DEFECTS
        assert len(_marked_lines(_CLEAN_MARKER)) >= _MIN_PLANTED_CLEAN

    def test_every_planted_defect_is_reported(self, reported_lines: set[int]) -> None:
        """Each EXPECT-HIT line must be found. This is the non-vacuity check."""
        expected = _marked_lines(_HIT_MARKER)
        missed = expected - reported_lines
        assert not missed, (
            f"the rule is BLIND to planted defects on lines {sorted(missed)}. "
            "It still loads and still reports success, which is exactly the "
            "failure mode this test exists to catch — do not 'fix' this by "
            "editing the fixture."
        )

    def test_correct_code_is_not_reported(self, reported_lines: set[int]) -> None:
        """Each EXPECT-CLEAN line must stay silent — precision over recall."""
        clean = _marked_lines(_CLEAN_MARKER)
        false_positives = clean & reported_lines
        assert not false_positives, (
            f"the rule fires on correct code at lines {sorted(false_positives)}. "
            "A gate that blocks commits must not cry wolf."
        )

    def test_reports_nothing_outside_the_marked_lines(self, reported_lines: set[int]) -> None:
        """No unexplained findings — every hit is accounted for by a marker."""
        unexplained = reported_lines - _marked_lines(_HIT_MARKER)
        assert not unexplained, f"unexpected findings on lines {sorted(unexplained)}"
