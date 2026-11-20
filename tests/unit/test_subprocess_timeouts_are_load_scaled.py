"""Task 2.5: a harness-side subprocess bound is scaled by host load, never a bare number.

The playbook harness (``tests/acceptance/test_playbook_harness.py``) runs the
whole-playbook generator in a subprocess under a fixed ``_GENERATE_TIMEOUT_SECONDS``.
Like a measured wall-clock bound, a bare ceiling there turns a loaded CI runner
into a harness error. The bound goes through ``tests.load_scaling.scaled_seconds``.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]

#: ``_GENERATE_TIMEOUT_SECONDS = 180`` -- a bare number assigned to a generator bound.
_BARE_GENERATE_BOUND = re.compile(r"^_GENERATE_TIMEOUT_SECONDS\s*=\s*\d")


def test_no_generator_timeout_is_a_bare_number() -> None:
    offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        relative = path.relative_to(TESTS_ROOT).as_posix()
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if _BARE_GENERATE_BOUND.search(line):
                offenders.append(f"{relative}:{number}: {line.strip()}")
    assert not offenders, (
        "These subprocess bounds are bare numbers; wrap them in "
        "tests.load_scaling.scaled_seconds():\n  " + "\n  ".join(offenders)
    )


def test_the_pin_sees_a_bare_bound_and_passes_a_scaled_one() -> None:
    assert _BARE_GENERATE_BOUND.search("_GENERATE_TIMEOUT_SECONDS = 180")
    assert not _BARE_GENERATE_BOUND.search("_GENERATE_TIMEOUT_SECONDS = scaled_seconds(180)")
