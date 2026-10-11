"""N95: a test fixture's git setup never borrows the hook-path git budget.

``Timeout.GIT_CONTEXT`` (5 s) bounds the daemon's own git calls on the hook
path. A fixture that builds a scratch repository with it turns host load into
a gate failure. Fixtures take ``tests.support.git_fixtures.git_setup_timeout``
instead. A test whose subject IS the product constant (it fakes a
``TimeoutExpired`` carrying it) is listed here by name.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]

#: A timeout handed to a subprocess, a helper default, or a module constant.
_BORROWS_BUDGET = re.compile(
    r"(?:\btimeout(?:\s*:\s*float)?\s*=|\b_TIMEOUT\s*=)\s*Timeout\.GIT_CONTEXT\b"
)

#: Files where the product constant is the thing under test, not a setup budget.
_PRODUCT_BUDGET_UNDER_TEST = frozenset(
    {
        # Fakes ``subprocess.TimeoutExpired(timeout=Timeout.GIT_CONTEXT)`` to
        # exercise the product's timeout handling.
        "unit/core/test_project_context.py",
        # Asserts the setup budget is larger than the product constant.
        "unit/test_git_fixtures.py",
        # This file names the pattern it forbids.
        "unit/test_fixtures_never_use_the_hook_path_git_budget.py",
    }
)


def test_no_fixture_borrows_the_hook_path_git_budget() -> None:
    offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        relative = path.relative_to(TESTS_ROOT).as_posix()
        if relative in _PRODUCT_BUDGET_UNDER_TEST:
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if _BORROWS_BUDGET.search(line):
                offenders.append(f"{relative}:{number}")
    assert not offenders, (
        "These fixtures run setup git under the 5 s hook budget; use "
        "tests.support.git_fixtures.git_setup_timeout():\n  " + "\n  ".join(offenders)
    )
