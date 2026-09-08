"""A `skipif` reason that states something false hides a test that never runs.

Plan 00351 found `test_skills.py` guarding a permission test with
`Path("/").stat().st_uid == 0` under the reason "Running as root". The reason
was the giveaway: it names the *running process*, but the condition asks **who
owns `/`**, which is uid 0 on every normal Linux system. So the condition was a
constant `True` and the test never ran anywhere — including on CI, where the
stated reason was plainly false because GitHub Actions runs as `runner`.

A missing reason would have been *better*: someone would have had to look. The
reason is what stopped anyone looking, so the check here is not "is this
predicate a constant" — `Path("/").stat().st_uid` is a live call and no static
constant-folding would flag it. The check is **does the condition ask what the
reason claims**. For the root case that means asking the process's own euid.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parents[1]

#: The wording that makes a reader believe the guard is about the running user.
_ROOT_WORDS = ("as root", "running as root", "is root", "under root")

#: The only call that answers "is THIS process root". `os.getuid` is accepted
#: too — it differs from `geteuid` only under setuid, which no test here uses.
_ASKS_THE_PROCESS = ("geteuid", "getuid")


@dataclass(frozen=True)
class RootSkip:
    """A `skipif` whose reason claims the process is running as root."""

    line: int
    condition: str
    reason: str


def _reason_of(call: ast.Call) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == "reason" and isinstance(keyword.value, ast.Constant):
            value = keyword.value.value
            return value if isinstance(value, str) else None
    return None


def _is_skipif(func: ast.expr) -> bool:
    return isinstance(func, ast.Attribute) and func.attr == "skipif"


def root_guarded_skips(source: str) -> list[RootSkip]:
    """Every `pytest.mark.skipif` whose reason blames the process being root."""
    tree = ast.parse(source)
    found: list[RootSkip] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_skipif(node.func):
            continue
        reason = _reason_of(node)
        if reason is None or not any(word in reason.lower() for word in _ROOT_WORDS):
            continue
        if not node.args:
            continue
        condition = ast.get_source_segment(source, node.args[0]) or ""
        found.append(RootSkip(line=node.lineno, condition=condition, reason=reason))
    return found


def asks_the_running_process(condition: str) -> bool:
    """Does this condition ask the euid of the process, rather than a path's?"""
    return any(call in condition for call in _ASKS_THE_PROCESS)


_THE_DEFECT = """
import pytest
@pytest.mark.skipif(
    Path("/").stat().st_uid == 0, reason="Running as root - permission test not applicable"
)
def test_thing(): ...
"""

_THE_FIX = """
import pytest
@pytest.mark.skipif(os.geteuid() == 0, reason="running as root, which ignores the mode")
def test_thing(): ...
"""

_UNRELATED = """
import pytest
@pytest.mark.skipif(shutil.which("rustc") is None, reason="rustc not installed")
def test_thing(): ...
"""


class TestRecognisingTheClaim:
    def test_the_original_defect_is_found(self) -> None:
        found = root_guarded_skips(_THE_DEFECT)
        assert len(found) == 1
        assert "st_uid" in found[0].condition

    def test_a_skip_about_something_else_is_not_dragged_in(self) -> None:
        assert root_guarded_skips(_UNRELATED) == []

    def test_a_skipif_with_no_reason_is_not_claimed_about(self) -> None:
        """No reason means nothing false was stated; this check has no opinion."""
        assert root_guarded_skips("import pytest\n@pytest.mark.skipif(True)\ndef t(): ...\n") == []


class TestJudgingTheCondition:
    def test_the_defect_does_not_ask_the_running_process(self) -> None:
        assert not asks_the_running_process(root_guarded_skips(_THE_DEFECT)[0].condition)

    def test_the_fix_does(self) -> None:
        assert asks_the_running_process(root_guarded_skips(_THE_FIX)[0].condition)


def _test_sources() -> list[Path]:
    return sorted(path for path in TESTS_ROOT.rglob("test_*.py") if "__pycache__" not in path.parts)


class TestTheRepositoryItself:
    def test_there_is_something_to_check(self) -> None:
        """A scan that matches nothing would pass forever without checking."""
        assert _test_sources(), "no test modules found to scan"

    @pytest.mark.parametrize("path", _test_sources(), ids=lambda p: p.name)
    def test_every_root_skip_asks_the_running_process(self, path: Path) -> None:
        for skip in root_guarded_skips(path.read_text(encoding="utf-8")):
            assert asks_the_running_process(skip.condition), (
                f"{path.relative_to(TESTS_ROOT)}:{skip.line} says {skip.reason!r} "
                f"but asks {skip.condition!r}, which does not read the process's "
                "own euid — use `os.geteuid() == 0` (Plan 00351)"
            )
