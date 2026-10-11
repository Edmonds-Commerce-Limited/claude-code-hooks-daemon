"""N95: a test fixture's git setup never borrows the hook-path git budget.

``Timeout.GIT_CONTEXT`` (5 s) bounds the daemon's own git calls on the hook
path. A fixture that builds a scratch repository with it turns host load into
a gate failure. Fixtures take ``tests.support.git_fixtures.git_setup_timeout``
instead.

Two uses of the product constant are legitimate and are listed here by name:
a test whose subject IS the constant, and a FAKE that stands in for a product
function and must keep the product's own default so the test can see a call
site that drops its explicit timeout.

Forms judged: a keyword argument (``timeout=Timeout.GIT_CONTEXT``) and a
module constant (``_GIT_TIMEOUT = Timeout.GIT_CONTEXT``) are fixture uses,
because a constant exists to be handed to a fixture's subprocess call. An
annotated parameter default (``timeout: float = Timeout.GIT_CONTEXT``) is a
product-signature stand-in and is allowed only in the listed fake files.
"""

from __future__ import annotations

import re
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parents[1]

_FIXTURE_FORM = re.compile(
    r"(?:\btimeout\s*=|\b\w*TIMEOUT\w*\s*=)(?!=)\s*Timeout\.GIT_CONTEXT\b", re.IGNORECASE
)
_PARAMETER_DEFAULT = re.compile(r"\btimeout\s*:\s*float\s*=\s*Timeout\.GIT_CONTEXT\b")

#: Files where the product constant is the thing under test.
_PRODUCT_BUDGET_UNDER_TEST = frozenset(
    {
        # Fakes ``subprocess.TimeoutExpired(timeout=Timeout.GIT_CONTEXT)`` to
        # exercise the product's timeout handling.
        "unit/core/test_project_context.py",
        # Asserts the setup budget is larger than the product constant.
        "unit/test_git_fixtures.py",
        # This file names the patterns it forbids.
        "unit/test_fixtures_never_use_the_hook_path_git_budget.py",
    }
)

#: Files holding fakes of product git functions, which keep the product default.
_PRODUCT_FAKES = frozenset(
    {
        # Spies on ``claude_code_hooks_daemon.core.claude_md_injector.run_git``;
        # two assert the timeouts the product passes for add and commit.
        "unit/core/test_claude_md_injector.py",
        # ``loaded_host`` stands in for ``git_file_states._git_paths``'s runner and
        # fails a call that drops its explicit timeout.
        "unit/utils/test_protected_file_index.py",
        # Recording wrappers around ``git_facts.run_git``.
        "unit/plan_qa/conftest.py",
        "unit/plan_qa/test_context.py",
        "unit/utils/test_git_facts.py",
        # Recording wrapper around ``git_sync.run_git``.
        "unit/reference_repos/test_inspection.py",
    }
)


def offending_lines(relative: str, text: str) -> list[int]:
    """1-based numbers of the lines in ``text`` that borrow the hook budget."""
    if relative in _PRODUCT_BUDGET_UNDER_TEST:
        return []
    found: list[int] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if _PARAMETER_DEFAULT.search(line):
            if relative not in _PRODUCT_FAKES:
                found.append(number)
        elif _FIXTURE_FORM.search(line):
            found.append(number)
    return found


def test_no_fixture_borrows_the_hook_path_git_budget() -> None:
    offenders: list[str] = []
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        relative = path.relative_to(TESTS_ROOT).as_posix()
        offenders += [f"{relative}:{n}" for n in offending_lines(relative, path.read_text())]
    assert not offenders, (
        "These fixtures run setup git under the 5 s hook budget; use "
        "tests.support.git_fixtures.git_setup_timeout():\n  " + "\n  ".join(offenders)
    )


class TestThePinSeesEveryForm:
    def test_a_keyword_argument(self) -> None:
        assert offending_lines("unit/x.py", "run(a, timeout=Timeout.GIT_CONTEXT)") == [1]

    def test_a_module_constant(self) -> None:
        assert offending_lines("unit/x.py", "_GIT_TIMEOUT = Timeout.GIT_CONTEXT") == [1]

    def test_a_plain_timeout_constant(self) -> None:
        assert offending_lines("unit/x.py", "_TIMEOUT = Timeout.GIT_CONTEXT") == [1]

    def test_an_annotated_default_outside_the_fake_files(self) -> None:
        line = "def f(cwd, *a, timeout: float = Timeout.GIT_CONTEXT): ..."
        assert offending_lines("unit/x.py", line) == [1]

    def test_an_annotated_default_in_a_fake_file_is_allowed(self) -> None:
        line = "def spy(cwd, *a, timeout: float = Timeout.GIT_CONTEXT): ..."
        assert offending_lines("unit/core/test_claude_md_injector.py", line) == []

    def test_a_keyword_argument_in_a_fake_file_is_still_flagged(self) -> None:
        line = "run(a, timeout=Timeout.GIT_CONTEXT)"
        assert offending_lines("unit/core/test_claude_md_injector.py", line) == [1]

    def test_the_setup_helper_is_not_flagged(self) -> None:
        assert offending_lines("unit/x.py", "run(a, timeout=git_setup_timeout())") == []

    def test_a_comparison_is_not_flagged(self) -> None:
        assert offending_lines("unit/x.py", "if timeout == Timeout.GIT_CONTEXT: pass") == []
