"""Prove the ``unlocked-select-then-evict`` semgrep rule is not blind (Plan 00449).

The rule is the Defence for the eviction-race class: a bounded map on a
handler singleton that selects a victim key and deletes it in two unlocked
steps. A semgrep rule that fails to bind still loads, still runs and still
reports success, which is indistinguishable from a clean tree — so the rule is
pinned against planted spellings of the defect, and against the locked spelling
the shared primitives use, with expectations read from markers IN the fixture.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_RULE_FILE: Final[Path] = _REPO_ROOT / "scripts" / "qa" / "semgrep" / "unlocked-eviction.yaml"
_FIXTURE: Final[Path] = _REPO_ROOT / "tests" / "fixtures" / "semgrep" / "unlocked_eviction.py"

_HIT_MARKER: Final[str] = "# EXPECT-HIT"
_CLEAN_MARKER: Final[str] = "# EXPECT-CLEAN"

# Minimum planted cases, so an emptied fixture cannot make this suite vacuous.
_MIN_PLANTED_DEFECTS: Final[int] = 8
_MIN_PLANTED_CLEAN: Final[int] = 3

_SEMGREP_TIMEOUT_SECONDS: Final[int] = 120

# The fixture's docstring explains the markers; a line that merely TALKS about
# one is prose, not a tagged line of code.
_PROSE_LINE_PREFIXES: Final[tuple[str, ...]] = ("#", "*", '"', "'")


def _marked_lines(marker: str) -> set[int]:
    """1-based line numbers where ``marker`` tags a line of CODE."""
    tagged: set[int] = set()
    for number, text in enumerate(_FIXTURE.read_text(encoding="utf-8").splitlines(), start=1):
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


@pytest.fixture(scope="module")
def reported_lines() -> set[int]:
    """Run the rule over the fixture once; return the reported 1-based lines.

    SECURITY: fixed argv, no shell, invoking a declared dev-dependency binary
    resolved from this venv.
    """
    if not _semgrep_executable().exists():
        pytest.fail(
            "semgrep is not installed in this venv. It is a declared dev "
            "dependency; install with: uv pip install -e '.[dev]'"
        )
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


class TestUnlockedEvictionRule:
    def test_fixture_actually_contains_cases(self) -> None:
        assert len(_marked_lines(_HIT_MARKER)) >= _MIN_PLANTED_DEFECTS
        assert len(_marked_lines(_CLEAN_MARKER)) >= _MIN_PLANTED_CLEAN

    def test_every_planted_defect_is_reported(self, reported_lines: set[int]) -> None:
        missed = _marked_lines(_HIT_MARKER) - reported_lines
        assert not missed, (
            f"the rule is BLIND to planted defects on lines {sorted(missed)}; "
            "do not 'fix' this by editing the fixture."
        )

    def test_the_locked_spelling_is_not_reported(self, reported_lines: set[int]) -> None:
        false_positives = _marked_lines(_CLEAN_MARKER) & reported_lines
        assert not false_positives, f"the rule fires on correct code at {sorted(false_positives)}"

    def test_reports_nothing_outside_the_marked_lines(self, reported_lines: set[int]) -> None:
        unexplained = reported_lines - _marked_lines(_HIT_MARKER)
        assert not unexplained, f"unexpected findings on lines {sorted(unexplained)}"
