"""Plan 00265: prove the STATIC half of the guarantee actually works.

The narrowed result types enforce their tier twice — mypy rejects an out-of-tier
decision, and Pydantic raises on one. ``tests/unit/core/test_result_types.py``
covers the runtime half thoroughly, and would keep passing in full even if mypy
stopped enforcing anything at all: a loosened ``Literal``, a relaxed strictness
setting, a plugin change. The static guarantee would be gone and every test
would still be green.

So this runs the real type checker over a fixture of deliberate violations and
asserts each one is caught. The fixture carries its own expectations as
``VIOLATION: <error-code>`` markers, so adding a case there extends this test
automatically — there is no second list to keep in step.

The fixture is excluded from the QA mypy and ruff runs (see ``pyproject.toml``)
precisely because it must fail; mypy's ``exclude`` only affects directory
crawling, so naming the file explicitly still checks it.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout

#: ``VIOLATION: <code>`` at the end of a line that mypy must report.
_MARKER = re.compile(r"#\s*VIOLATION:\s*([a-z-]+)\s*$")

#: mypy's own output format: ``path:line: error: message  [code]``.
_MYPY_ERROR = re.compile(r"^(?P<path>[^:]+):(?P<line>\d+): error: .*\[(?P<code>[a-z-]+)\]")

_FIXTURE_DIR = Path("tests/fixtures/type_safety_violations")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _fixture_files() -> list[Path]:
    return sorted((_project_root() / _FIXTURE_DIR).glob("*.py"))


def _expected_violations(fixture: Path) -> dict[int, str]:
    """Line number -> error code, read from the fixture's own markers."""
    expected: dict[int, str] = {}
    for index, line in enumerate(fixture.read_text().splitlines(), start=1):
        match = _MARKER.search(line)
        if match:
            expected[index] = match.group(1)
    return expected


@pytest.fixture(scope="module")
def mypy_findings() -> dict[tuple[str, int], str]:
    """(filename, line) -> error code, from one real mypy run over the fixtures.

    Module-scoped because invoking mypy is the expensive part; every assertion
    below reads this one result.

    SECURITY: fixed argument list, no shell, no user input. The interpreter is
    ``sys.executable`` (the venv running the tests) and the only variable part
    is a glob of paths inside this repository's own fixture directory.
    """
    files = _fixture_files()
    assert files, "no violation fixtures found — the checks below prove nothing"

    completed = subprocess.run(
        [sys.executable, "-m", "mypy", "--no-color-output", *[str(f) for f in files]],
        cwd=_project_root(),
        capture_output=True,
        text=True,
        check=False,
        timeout=Timeout.QA_TEST_TIMEOUT,
    )

    findings: dict[tuple[str, int], str] = {}
    for line in completed.stdout.splitlines():
        match = _MYPY_ERROR.match(line)
        if match:
            key = (Path(match.group("path")).name, int(match.group("line")))
            findings[key] = match.group("code")

    assert findings, (
        "mypy reported no errors at all on a file of deliberate type violations. "
        "Either type checking is not running, or the narrowing has been removed.\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    return findings


class TestEveryPlantedViolationIsCaught:
    """The property: mypy really does reject what the tiers forbid."""

    def test_the_fixture_declares_violations(self) -> None:
        """Vacuity guard — an unmarked fixture would satisfy everything below."""
        total = sum(len(_expected_violations(f)) for f in _fixture_files())

        assert (
            total >= 5
        ), f"only {total} violation markers found; the fixture is not exercising the tiers"

    def test_each_marked_line_is_reported(self, mypy_findings: dict[tuple[str, int], str]) -> None:
        missed: list[str] = []
        for fixture in _fixture_files():
            for line_number, code in _expected_violations(fixture).items():
                if (fixture.name, line_number) not in mypy_findings:
                    missed.append(f"{fixture.name}:{line_number} expected [{code}], not reported")

        assert not missed, (
            "mypy did not reject code the narrowed result types are supposed to "
            "make impossible. The static guarantee is not holding:\n  " + "\n  ".join(missed)
        )

    def test_each_reported_error_has_the_expected_code(
        self, mypy_findings: dict[tuple[str, int], str]
    ) -> None:
        """A different error code means it failed for the wrong reason."""
        wrong: list[str] = []
        for fixture in _fixture_files():
            for line_number, expected_code in _expected_violations(fixture).items():
                actual = mypy_findings.get((fixture.name, line_number))
                if actual is not None and actual != expected_code:
                    wrong.append(
                        f"{fixture.name}:{line_number} expected [{expected_code}], got [{actual}]"
                    )

        assert not wrong, "caught, but not for the stated reason:\n  " + "\n  ".join(wrong)

    def test_nothing_unexpected_is_reported(
        self, mypy_findings: dict[tuple[str, int], str]
    ) -> None:
        """An unmarked error means the fixture has drifted into accidental breakage."""
        marked = {
            (fixture.name, line_number)
            for fixture in _fixture_files()
            for line_number in _expected_violations(fixture)
        }
        unexpected = sorted(
            f"{name}:{line} [{code}]"
            for (name, line), code in mypy_findings.items()
            if (name, line) not in marked
        )

        assert not unexpected, (
            "mypy reported errors the fixture does not claim, so the fixture is "
            "broken rather than demonstrating the guarantee:\n  " + "\n  ".join(unexpected)
        )
