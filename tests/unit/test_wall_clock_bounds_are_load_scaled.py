"""N222: a test's wall-clock upper bound is scaled by host load, never a bare number.

``assert elapsed < 10`` is a hang guard that a loaded host turns into a false
failure. Such a bound goes through ``tests.load_scaling.scaled_seconds`` (or a
helper built on it), which only ever lengthens it.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]

#: Something that measures elapsed time: a name containing ``elapsed`` or
#: ``duration``, an ``execution_time_ms`` attribute, or a clock difference.
_MEASURE = (
    r"(?:[\w.]*(?:elapsed|duration|execution_time_ms)[\w.]*"
    r"|(?:time\.)?(?:monotonic|perf_counter|time)\(\)\s*-\s*\w+)"
)

#: ``assert <measure> < <number>`` -- a bare numeric ceiling on time.
_BARE_BOUND = re.compile(rf"\bassert\s+{_MEASURE}\s*<=?\s*\d")

#: ``assert <number> < <measure> < <number>`` -- the same, with a floor.
_CHAINED_BOUND = re.compile(rf"\bassert\s+\d[\d._]*\s*<=?\s*{_MEASURE}\s*<=?\s*\d")

_SELF = "unit/test_wall_clock_bounds_are_load_scaled.py"


def is_bare_bound(line: str) -> bool:
    """Whether ``line`` compares a measured time to a bare number."""
    return _BARE_BOUND.search(line) is not None or _CHAINED_BOUND.search(line) is not None


def test_no_elapsed_time_is_compared_to_a_bare_number() -> None:
    offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        relative = path.relative_to(TESTS_ROOT).as_posix()
        if relative == _SELF:
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if is_bare_bound(line):
                offenders.append(f"{relative}:{number}: {line.strip()}")
    assert not offenders, (
        "These bounds are bare wall-clock numbers; wrap them in "
        "tests.load_scaling.scaled_seconds():\n  " + "\n  ".join(offenders)
    )


class TestThePinSeesEveryForm:
    def test_elapsed_below_a_number(self) -> None:
        assert is_bare_bound("assert elapsed < 10")

    def test_execution_time_attribute_below_a_float(self) -> None:
        assert is_bare_bound("assert result.execution_time_ms < 100.0  # fast")

    def test_a_chained_comparison(self) -> None:
        assert is_bare_bound("assert 0 < elapsed < 5")

    def test_duration_below_a_number(self) -> None:
        assert is_bare_bound("assert duration < 5")

    def test_a_clock_difference_below_a_number(self) -> None:
        assert is_bare_bound("assert time.monotonic() - started < 5")
        assert is_bare_bound("assert perf_counter() - t0 <= 2.5")

    def test_a_scaled_bound_is_fine(self) -> None:
        assert not is_bare_bound("assert elapsed < scaled_seconds(10.0)")
        assert not is_bare_bound("assert result.execution_time_ms < scaled_seconds(100.0)")
        assert not is_bare_bound("assert elapsed < bound")

    def test_a_lower_bound_on_time_is_not_a_hang_guard(self) -> None:
        assert not is_bare_bound("assert elapsed > 1")
