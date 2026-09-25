"""No test may skip, xfail or early-return because the process is root.

Plan 00351 found `test_skills.py` guarding a permission test with
`Path("/").stat().st_uid == 0` under the reason "Running as root" — a
condition that asks who owns `/` (uid 0 on every normal Linux system,
whoever is running), not who is running, so it was a constant `True` and the
test never ran anywhere. That plan's fix, and this file's original check,
was narrower than the defect deserved: it verified that a root-skip's
*condition* matched its stated reason (asking `os.geteuid()` rather than a
path's owner), but it still endorsed skipping on root at all.

Plan 00466 N56: the owner set the rule directly. This container, and the
dogfood server, run as root — so a root-guarded skip is a test that never
runs where the work happens, regardless of whether its condition is written
correctly. Every test in this repository must prove its behaviour as root;
permission checks that root bypasses need a different fault (an injected
`PermissionError`, a directory or symlink in the path's place, or patching
the specific OS call), not a skip.

This is a blanket static scan rather than the narrower per-file rewrites,
because a root-conditioned skip anywhere under `tests/` — not just in the
four files N56 found by hand — regresses this rule the same way.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parents[1]

#: The only calls that answer "is THIS process root". `os.getuid` is accepted
#: too — it differs from `geteuid` only under setuid, which no test here uses.
_ASKS_THE_PROCESS = ("geteuid", "getuid")

#: `pytest.mark.<name>` decorators whose first argument is a boolean
#: condition evaluated at collection time — both can hide a test from ever
#: running.
_CONDITIONAL_MARKS = ("skipif", "xfail")

#: Calls inside a hand-written `if <root check>: ...` block that skip the
#: test outright, as distinct from a `return` (below), which is caught by
#: statement type rather than by name.
_SKIP_CALLS = ("skip", "xfail")


@dataclass(frozen=True)
class RootConditionedSkip:
    """A place a test's execution is gated on the process's own euid/uid."""

    line: int
    kind: str
    snippet: str


def _call_name(call: ast.Call) -> str | None:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _mentions_root_uid(node: ast.AST) -> bool:
    """Whether an expression subtree compares a `getuid()`/`geteuid()` call to 0.

    Walks the whole subtree rather than pattern-matching one shape, so it
    catches the comparison on either side (`0 == os.geteuid()` as well as
    `os.geteuid() == 0`) and however deeply it is nested inside `and`/`or`.
    """
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Compare):
            continue
        operands = [sub.left, *sub.comparators]
        zero_present = any(isinstance(o, ast.Constant) and o.value == 0 for o in operands)
        if not zero_present:
            continue
        for operand in operands:
            if isinstance(operand, ast.Call) and _call_name(operand) in _ASKS_THE_PROCESS:
                return True
    return False


def _snippet(source: str, node: ast.expr | ast.stmt) -> str:
    return (ast.get_source_segment(source, node) or "").strip()


def _decorator_findings(source: str, tree: ast.Module) -> list[RootConditionedSkip]:
    found: list[RootConditionedSkip] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr not in _CONDITIONAL_MARKS:
            continue
        if not node.args:
            continue
        condition = node.args[0]
        if _mentions_root_uid(condition):
            found.append(
                RootConditionedSkip(
                    line=node.lineno, kind=func.attr, snippet=_snippet(source, node)
                )
            )
    return found


def _guarded_skip_or_return(body: list[ast.stmt]) -> ast.stmt | None:
    """The first statement in `body` that skips, xfails, or returns outright."""
    for stmt in body:
        if isinstance(stmt, ast.Return):
            return stmt
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            if _call_name(stmt.value) in _SKIP_CALLS:
                return stmt
    return None


def _if_guarded_findings(source: str, tree: ast.Module) -> list[RootConditionedSkip]:
    """`if <root check>: pytest.skip(...)` / `xfail(...)` / `return` — hand-written."""
    found: list[RootConditionedSkip] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not _mentions_root_uid(node.test):
            continue
        guarded = _guarded_skip_or_return(node.body)
        if guarded is None:
            continue
        kind = "return" if isinstance(guarded, ast.Return) else "skip-or-xfail"
        found.append(
            RootConditionedSkip(line=node.lineno, kind=kind, snippet=_snippet(source, node))
        )
    return found


def root_conditioned_skips(source: str) -> list[RootConditionedSkip]:
    """Every place `source` gates a test's execution on the process's own uid."""
    tree = ast.parse(source)
    return _decorator_findings(source, tree) + _if_guarded_findings(source, tree)


_DECORATOR_SKIPIF = """
import os
import pytest
@pytest.mark.skipif(os.geteuid() == 0, reason="running as root, which ignores the mode")
def test_thing(): ...
"""

_DECORATOR_XFAIL = """
import os
import pytest
@pytest.mark.xfail(os.getuid() == 0, reason="root bypasses this check")
def test_thing(): ...
"""

_IF_GUARDED_SKIP = """
import os
import pytest
def test_thing():
    if os.geteuid() == 0:
        pytest.skip("running as root")
    assert True
"""

_IF_GUARDED_RETURN = """
import os
def test_thing():
    if os.geteuid() == 0:
        return
    assert True
"""

_OPERANDS_REVERSED = """
import os
import pytest
@pytest.mark.skipif(0 == os.geteuid(), reason="root")
def test_thing(): ...
"""

_UNRELATED_SKIPIF = """
import shutil
import pytest
@pytest.mark.skipif(shutil.which("rustc") is None, reason="rustc not installed")
def test_thing(): ...
"""

_UNRELATED_IF_RETURN = """
def test_thing():
    if some_flag():
        return
    assert True
"""

_UNCONDITIONAL_SKIP = """
import pytest
def test_thing():
    pytest.skip("always skipped, not root-conditioned")
"""


class TestRecognisingEachShape:
    def test_skipif_decorator_is_found(self) -> None:
        found = root_conditioned_skips(_DECORATOR_SKIPIF)
        assert len(found) == 1
        assert found[0].kind == "skipif"

    def test_xfail_decorator_is_found(self) -> None:
        found = root_conditioned_skips(_DECORATOR_XFAIL)
        assert len(found) == 1
        assert found[0].kind == "xfail"

    def test_if_guarded_skip_is_found(self) -> None:
        found = root_conditioned_skips(_IF_GUARDED_SKIP)
        assert len(found) == 1
        assert found[0].kind == "skip-or-xfail"

    def test_if_guarded_return_is_found(self) -> None:
        found = root_conditioned_skips(_IF_GUARDED_RETURN)
        assert len(found) == 1
        assert found[0].kind == "return"

    def test_reversed_operand_order_is_still_found(self) -> None:
        assert len(root_conditioned_skips(_OPERANDS_REVERSED)) == 1

    def test_an_unrelated_skipif_is_not_dragged_in(self) -> None:
        assert root_conditioned_skips(_UNRELATED_SKIPIF) == []

    def test_an_unrelated_if_return_is_not_dragged_in(self) -> None:
        assert root_conditioned_skips(_UNRELATED_IF_RETURN) == []

    def test_an_unconditional_skip_is_not_dragged_in(self) -> None:
        """A skip not gated on anything is not this defect — it is not hidden."""
        assert root_conditioned_skips(_UNCONDITIONAL_SKIP) == []


def _test_sources() -> list[Path]:
    return sorted(
        path
        for path in TESTS_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
        and path != Path(__file__).resolve()
        and (path.name.startswith("test_") or path.name == "conftest.py")
    )


class TestTheRepositoryItself:
    def test_there_is_something_to_check(self) -> None:
        """A scan that matches nothing would pass forever without checking."""
        assert _test_sources(), "no test modules found to scan"

    @pytest.mark.parametrize("path", _test_sources(), ids=lambda p: p.name)
    def test_no_root_conditioned_skip_exists(self, path: Path) -> None:
        for finding in root_conditioned_skips(path.read_text(encoding="utf-8")):
            pytest.fail(
                f"{path.relative_to(TESTS_ROOT)}:{finding.line} skips this process's own "
                f"euid/uid ({finding.kind}): {finding.snippet!r}\n"
                "Every test must run as root (Plan 00466 N56). Root bypasses file mode "
                "bits, so fault the operation another way instead: monkeypatch the "
                "specific os/open/Path call to raise PermissionError, replace the file "
                "with a directory or a dangling symlink, or patch the exact check the "
                "code under test performs."
            )
