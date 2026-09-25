"""No test may skip, xfail or early-return because the process is root.

Plan 00351 found `test_skills.py` guarding a permission test with
`Path("/").stat().st_uid == 0` under the reason "Running as root" — a
condition that asks who owns `/` (uid 0 on every normal Linux system,
whoever is running), not who is running, so it was a constant `True` and the
test never ran anywhere. That plan's fix keyed on the REASON text (does it
claim root?) rather than the condition, and this file's first cut of the N56
detector regressed that: it matched only a literal `geteuid()`/`getuid()`
call compared to `0`, which misses Plan 00351's own shape and everything
between it and a bare `geteuid() == 0` (review 1, F1/F2). This detector
combines both legs:

- **Condition analysis**, resolving simple indirection (a module constant, a
  helper function's `return`) so `IS_ROOT = os.geteuid() == 0` then
  `skipif(IS_ROOT)` is caught as surely as the inline form, plus the
  `pwd`/`getpass` and string-condition variants pytest also accepts.
- **Reason-text analysis**, independent of the condition, so a skip whose
  stated reason names root — Plan 00351's own defect — fails whatever its
  condition actually tests.

Plan 00466 N56: the owner set the rule directly. This container, and the
dogfood server, run as root — so a root-guarded skip is a test that never
runs where the work happens. Every test in this repository must prove its
behaviour as root; permission checks that root bypasses need a different
fault (an injected `PermissionError`, a directory or symlink in the path's
place, or patching the specific OS call), not a skip.

This is a blanket static scan of every `.py` file under `tests/` — not just
`test_*.py`/`conftest.py` — because a root-conditioned skip in a helper
module regresses this rule exactly like one in a test module.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parents[1]

#: The only calls that answer "is THIS process root". `os.getuid` is accepted
#: too — it differs from `geteuid` only under setuid, which no test here uses.
_UID_CALL_NAMES = frozenset({"geteuid", "getuid"})

#: `pytest.mark.<name>` / `unittest.<name>` decorators whose condition is
#: evaluated at collection time — any can hide a test from ever running.
#: Matched case-insensitively so `unittest.skipIf` (capital I) counts.
_CONDITIONAL_MARKS = frozenset({"skipif", "xfail"})

#: Wording that makes a reader believe a skip is about the running user,
#: independent of what its condition actually tests (Plan 00351's shape).
_ROOT_REASON_WORDS = ("as root", "running as root", "is root", "under root")


@dataclass(frozen=True)
class RootConditionedSkip:
    """A place a test's execution is gated on the process's own euid/uid."""

    line: int
    kind: str
    snippet: str


# --------------------------------------------------------------------------
# AST helpers
# --------------------------------------------------------------------------


def _dotted_name(node: ast.expr) -> str:
    """Render a `Name`/`Attribute` chain as `a.b.c`, best-effort."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _call_name(call: ast.Call) -> str | None:
    return _dotted_name(call.func).rsplit(".", 1)[-1] or None


def _is_uid_call(node: ast.expr) -> bool:
    """Whether `node` is a call to `(os.)geteuid()`/`(os.)getuid()`."""
    return isinstance(node, ast.Call) and _call_name(node) in _UID_CALL_NAMES


def _is_zero_constant(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and not isinstance(node.value, bool) and node.value == 0


def _is_root_string_constant(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.strip().lower() == "root"
    )


def _contains_zero(node: ast.expr) -> bool:
    """A bare `0`, or a tuple/list/set literal containing one (`in (0,)`)."""
    if _is_zero_constant(node):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(_is_zero_constant(elt) for elt in node.elts)
    return False


def _snippet(source: str, node: ast.expr | ast.stmt) -> str:
    return (ast.get_source_segment(source, node) or "").strip()


# --------------------------------------------------------------------------
# Resolving indirection: `IS_ROOT = os.geteuid() == 0`, `def _is_root(): ...`
# --------------------------------------------------------------------------


@dataclass
class _ResolutionContext:
    """Names and zero-arg helper functions statically known to test root."""

    root_names: set[str]
    root_funcs: set[str]


def _non_nested_statements(body: list[ast.stmt]) -> list[ast.stmt]:
    """Every statement reachable from `body` without crossing into a nested
    function/class — an `if`/`try`/`with`/`for` inside stays in scope, a
    `def`/`class` does not (its own `return` belongs to IT, not the caller).
    """
    out: list[ast.stmt] = []
    for stmt in body:
        out.append(stmt)
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for field in ("body", "orelse", "finalbody"):
            nested = getattr(stmt, field, None)
            if nested:
                out.extend(_non_nested_statements(nested))
    return out


def _resolve_context(tree: ast.Module) -> _ResolutionContext:
    """Fixed-point resolution of module-level root-indicating names/helpers.

    Bounded to a handful of passes: a constant referencing a helper that
    references another constant is already an unrealistic chain for a test
    module, so this never approaches the cap in practice.
    """
    ctx = _ResolutionContext(root_names=set(), root_funcs=set())
    assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)]
    funcdefs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]

    for _ in range(6):
        changed = False
        for assign in assigns:
            for target in assign.targets:
                if isinstance(target, ast.Name) and target.id not in ctx.root_names:
                    if _is_root_expr(assign.value, ctx):
                        ctx.root_names.add(target.id)
                        changed = True
        for func in funcdefs:
            if func.name in ctx.root_funcs:
                continue
            for stmt in _non_nested_statements(func.body):
                if isinstance(stmt, ast.Return) and stmt.value is not None:
                    if _is_root_expr(stmt.value, ctx):
                        ctx.root_funcs.add(func.name)
                        changed = True
                        break
        if not changed:
            break
    return ctx


# --------------------------------------------------------------------------
# Condition analysis
# --------------------------------------------------------------------------


def _is_root_expr(node: ast.expr, ctx: _ResolutionContext) -> bool:
    """Whether `node` — a condition, or a sub-expression of one — tests root.

    Recognises a direct `geteuid()`/`getuid()` comparison (either operand
    order, `==` or `!=` or `in`), `not geteuid()`, a `pwd`/`getpass` identity
    check, a resolved module constant or zero-arg helper call, a boolean
    composition of any of these, and a *string* condition (pytest accepts a
    plain string as a `skipif` condition — parsed and recursed on).
    """
    if isinstance(node, ast.Name):
        return node.id in ctx.root_names

    if isinstance(node, ast.Call):
        simple = _call_name(node)
        return simple is not None and simple in ctx.root_funcs

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _is_uid_call(node.operand) or _is_root_expr(node.operand, ctx)

    if isinstance(node, ast.BoolOp):
        return any(_is_root_expr(value, ctx) for value in node.values)

    if isinstance(node, ast.Compare):
        operands = [node.left, *node.comparators]

        has_uid_call = any(_is_uid_call(o) for o in operands)
        has_zero = any(_contains_zero(o) for o in operands)
        if has_uid_call and has_zero:
            return True

        has_root_string = any(_is_root_string_constant(o) for o in operands)
        if has_root_string:
            for operand in operands:
                if isinstance(operand, ast.Attribute) and operand.attr == "pw_name":
                    return True
                if isinstance(operand, ast.Call) and _call_name(operand) in {
                    "getuser",
                    "pw_name",
                }:
                    return True

        for operand in operands:
            if isinstance(operand, ast.Name) and operand.id in ctx.root_names:
                return True
            if isinstance(operand, ast.Call) and _is_root_expr(operand, ctx):
                return True

        return False

    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        # A string condition (pytest accepts one) or an arbitrary string
        # constant this resolution pass is trying every Assign's RHS against
        # — most are not source at all (a fixture's raw file content, binary
        # test data with embedded NUL bytes), so both the syntax error and
        # the NUL-byte ValueError `compile()` raises mean "not an expression".
        try:
            parsed = ast.parse(node.value.strip(), mode="eval")
        except (SyntaxError, ValueError):
            return False
        return _is_root_expr(parsed.body, ctx)

    return False


# --------------------------------------------------------------------------
# Reason-text analysis — independent of the condition (Plan 00351's shape)
# --------------------------------------------------------------------------

#: The exact (case-insensitive) final dotted component of a call that is a
#: real skip mechanism. Exact match, not substring — `skip_is_a_provisioning_
#: failure(...)` (a real helper in this repo) contains "skip" but is not one.
_SKIP_LIKE_FINAL_NAMES = frozenset({"skip", "skipif", "xfail", "skiptest"})


def _looks_like_skip_related(call: ast.Call) -> bool:
    parts = [p.lower() for p in _dotted_name(call.func).split(".") if p]
    if not parts:
        return False
    if parts[-1] in _SKIP_LIKE_FINAL_NAMES:
        return True
    # `raise pytest.skip.Exception(...)` — the exception class hung off `skip`.
    return parts[-1] == "exception" and len(parts) >= 2 and parts[-2] in _SKIP_LIKE_FINAL_NAMES


def _call_reason_text(call: ast.Call) -> str | None:
    for keyword in call.keywords:
        if (
            keyword.arg == "reason"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        ):
            return keyword.value.value
    for arg in call.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
    return None


def _reason_names_root(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _ROOT_REASON_WORDS)


def _reason_findings(source: str, tree: ast.Module) -> list[RootConditionedSkip]:
    found: list[RootConditionedSkip] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _looks_like_skip_related(node):
            continue
        reason = _call_reason_text(node)
        if reason is not None and _reason_names_root(reason):
            found.append(
                RootConditionedSkip(line=node.lineno, kind="reason", snippet=_snippet(source, node))
            )
    return found


# --------------------------------------------------------------------------
# Decorator findings: skipif / xfail / skipIf, condition= or positional
# --------------------------------------------------------------------------


def _decorator_condition(call: ast.Call) -> ast.expr | None:
    if call.args:
        return call.args[0]
    for keyword in call.keywords:
        if keyword.arg == "condition":
            return keyword.value
    return None


def _decorator_findings(
    source: str, tree: ast.Module, ctx: _ResolutionContext
) -> list[RootConditionedSkip]:
    found: list[RootConditionedSkip] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr.lower() not in _CONDITIONAL_MARKS:
            continue
        condition = _decorator_condition(node)
        if condition is not None and _is_root_expr(condition, ctx):
            found.append(
                RootConditionedSkip(
                    line=node.lineno, kind=func.attr, snippet=_snippet(source, node)
                )
            )
    return found


# --------------------------------------------------------------------------
# Hand-written `if <root check>: skip/xfail/skipTest/raise-skip/return`
# --------------------------------------------------------------------------


def _guarded_action(stmts: list[ast.stmt]) -> tuple[str, ast.stmt] | None:
    """The first skip/xfail/return reachable from `stmts` without crossing
    into a nested function/class — see `_non_nested_statements`.
    """
    for stmt in _non_nested_statements(stmts):
        if isinstance(stmt, ast.Return):
            return ("return", stmt)
        if isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call):
            if _looks_like_skip_related(stmt.exc):
                return ("skip-or-xfail", stmt)
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            if _looks_like_skip_related(stmt.value):
                return ("skip-or-xfail", stmt)
    return None


def _if_guarded_findings(
    source: str, tree: ast.Module, ctx: _ResolutionContext
) -> list[RootConditionedSkip]:
    """`if <root check>: pytest.skip(...)` / `self.skipTest(...)` / `return` —
    hand-written, in either the `if` or the `else` branch.
    """
    found: list[RootConditionedSkip] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or not _is_root_expr(node.test, ctx):
            continue
        guarded = _guarded_action(node.body) or _guarded_action(node.orelse)
        if guarded is None:
            continue
        kind, _stmt = guarded
        found.append(
            RootConditionedSkip(line=node.lineno, kind=kind, snippet=_snippet(source, node))
        )
    return found


def root_conditioned_skips(source: str) -> list[RootConditionedSkip]:
    """Every place `source` gates a test's execution on the process's own uid."""
    tree = ast.parse(source)
    ctx = _resolve_context(tree)
    by_line: dict[int, RootConditionedSkip] = {}
    for finding in (
        _decorator_findings(source, tree, ctx)
        + _if_guarded_findings(source, tree, ctx)
        + _reason_findings(source, tree)
    ):
        by_line.setdefault(finding.line, finding)
    return [by_line[line] for line in sorted(by_line)]


# --------------------------------------------------------------------------
# Regression fixtures — one per evasion shape review 1 named (F2), plus the
# regression shape review 1 named directly (F1). Each is SHOULD_FIND unless
# named otherwise.
# --------------------------------------------------------------------------

_SHOULD_FIND: dict[str, str] = {
    "getuid_eq_0_skipif": """
import os, pytest
@pytest.mark.skipif(os.getuid() == 0, reason="x")
def test_a(): ...
""",
    "zero_eq_geteuid_skipif": """
import os, pytest
@pytest.mark.skipif(0 == os.geteuid(), reason="x")
def test_a(): ...
""",
    "module_constant_IS_ROOT": """
import os, pytest
IS_ROOT = os.geteuid() == 0
@pytest.mark.skipif(IS_ROOT, reason="root")
def test_a(): ...
""",
    "conftest_marker_requires_non_root": """
import os, pytest
requires_non_root = pytest.mark.skipif(os.geteuid() == 0, reason="needs non-root")
""",
    "conftest_marker_via_constant": """
import os, pytest
_ROOT = os.geteuid() == 0
requires_non_root = pytest.mark.skipif(_ROOT, reason="needs non-root")
""",
    "helper_function_skip": """
import os, pytest
def skip_if_root():
    if os.geteuid() == 0:
        pytest.skip("root")
""",
    "helper_function_returning_bool": """
import os, pytest
def _is_root():
    return os.geteuid() == 0
@pytest.mark.skipif(_is_root(), reason="root")
def test_a(): ...
""",
    "importorskip_style_helper": """
import os, pytest
def skip_unless_unprivileged():
    if not os.geteuid():
        pytest.skip("root")
""",
    "not_geteuid": """
import os, pytest
@pytest.mark.skipif(not os.geteuid(), reason="root")
def test_a(): ...
""",
    "pwd_name_root": """
import os, pwd, pytest
@pytest.mark.skipif(pwd.getpwuid(os.getuid()).pw_name == "root", reason="root")
def test_a(): ...
""",
    "getpass_user_root": """
import getpass, pytest
@pytest.mark.skipif(getpass.getuser() == "root", reason="root")
def test_a(): ...
""",
    "fixture_if_skip": """
import os, pytest
@pytest.fixture
def unprivileged():
    if os.geteuid() == 0:
        pytest.skip("root")
    yield
""",
    "fixture_if_skip_after_other_stmt": """
import os, pytest
def test_a():
    if os.geteuid() == 0:
        print("root!")
        pytest.skip("root")
""",
    "skip_reason_mentions_root_other_condition": """
import pytest
from pathlib import Path
@pytest.mark.skipif(Path("/").stat().st_uid == 0, reason="Running as root")
def test_a(): ...
""",
    "unittest_skipIf": """
import os, unittest
class T(unittest.TestCase):
    @unittest.skipIf(os.geteuid() == 0, "root")
    def test_a(self): ...
""",
    "unittest_self_skipTest": """
import os, unittest
class T(unittest.TestCase):
    def test_a(self):
        if os.geteuid() == 0:
            self.skipTest("root")
""",
    "raise_skip_exception": """
import os, pytest
def test_a():
    if os.geteuid() == 0:
        raise pytest.skip.Exception("root")
""",
    "else_branch": """
import os, pytest
def test_a():
    if os.geteuid() != 0:
        assert True
    else:
        pytest.skip("root")
""",
    "euid_in_tuple": """
import os, pytest
@pytest.mark.skipif(os.geteuid() in (0,), reason="root")
def test_a(): ...
""",
    "from_os_import_geteuid": """
from os import geteuid
import pytest
@pytest.mark.skipif(geteuid() == 0, reason="root")
def test_a(): ...
""",
    "skipif_condition_as_kwarg": """
import os, pytest
@pytest.mark.skipif(condition=os.geteuid() == 0, reason="root")
def test_a(): ...
""",
    "pytestmark_module": """
import os, pytest
pytestmark = pytest.mark.skipif(os.geteuid() == 0, reason="root")
""",
    "ternary_return": """
import os
def test_a():
    if os.geteuid() == 0 and True:
        return None
""",
    "string_condition": """
import pytest
@pytest.mark.skipif("os.geteuid() == 0", reason="root")
def test_a(): ...
""",
}

_SHOULD_NOT_FIND: dict[str, str] = {
    "project_root_wording": """
import pytest
PROJECT_ROOT = "/x"
@pytest.mark.skipif(PROJECT_ROOT is None, reason="project root not found")
def test_a():
    if PROJECT_ROOT == 0:
        return
""",
    "root_in_reason_only_unrelated": """
import shutil, pytest
@pytest.mark.skipif(shutil.which("git") is None, reason="needs git at repo root")
def test_a(): ...
""",
    "getuid_used_non_skip": """
import os
def test_a():
    if os.geteuid() == 0:
        assert True
""",
    "unrelated_skipif": """
import shutil
import pytest
@pytest.mark.skipif(shutil.which("rustc") is None, reason="rustc not installed")
def test_thing(): ...
""",
    "unrelated_if_return": """
def test_thing():
    if some_flag():
        return
    assert True
""",
    "unconditional_skip": """
import pytest
def test_thing():
    pytest.skip("always skipped, not root-conditioned")
""",
}


class TestEveryEvasionShapeIsCaught:
    """One assertion per shape review 1's probe named (F1, F2)."""

    @pytest.mark.parametrize("name", sorted(_SHOULD_FIND), ids=lambda n: n)
    def test_shape_is_found(self, name: str) -> None:
        found = root_conditioned_skips(_SHOULD_FIND[name])
        assert found, f"{name}: expected a root-conditioned skip to be found"


class TestNoFalsePositives:
    @pytest.mark.parametrize("name", sorted(_SHOULD_NOT_FIND), ids=lambda n: n)
    def test_shape_is_clean(self, name: str) -> None:
        found = root_conditioned_skips(_SHOULD_NOT_FIND[name])
        assert found == [], f"{name}: expected no finding, got {found!r}"


#: Fixture trees hold deliberately-invalid Python (e.g. a handler with a
#: missing paren, to exercise another handler's own syntax-error path) —
#: unparseable by construction, and not real test code this rule governs.
#: Matches the exclusion convention other handlers in this project already
#: use for tests/fixtures/, tests/assets/, __fixtures__/.
_EXCLUDED_DIR_NAMES = frozenset({"fixtures", "assets", "__fixtures__"})


def _test_sources() -> list[Path]:
    return sorted(
        path
        for path in TESTS_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
        and path != Path(__file__).resolve()
        and not any(part in _EXCLUDED_DIR_NAMES for part in path.parts)
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
