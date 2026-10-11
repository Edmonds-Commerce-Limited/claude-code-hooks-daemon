"""N222: a test's wall-clock upper bound is scaled by host load, never a bare number.

``assert elapsed < 10`` is a hang guard that a loaded host turns into a false
failure. Such a bound goes through ``tests.load_scaling.scaled_seconds`` (or a
helper built on it), which only ever lengthens it.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]

#: ``assert <something-elapsed> < <number>`` -- a bare numeric ceiling on time.
_BARE_BOUND = re.compile(r"\bassert\s+\w*(?:elapsed|execution_time_ms)\w*\s*<=?\s*\d")

_SELF = "unit/test_wall_clock_bounds_are_load_scaled.py"


def test_no_elapsed_time_is_compared_to_a_bare_number() -> None:
    offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        relative = path.relative_to(TESTS_ROOT).as_posix()
        if relative == _SELF:
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if _BARE_BOUND.search(line):
                offenders.append(f"{relative}:{number}: {line.strip()}")
    assert not offenders, (
        "These bounds are bare wall-clock numbers; wrap them in "
        "tests.load_scaling.scaled_seconds():\n  " + "\n  ".join(offenders)
    )
