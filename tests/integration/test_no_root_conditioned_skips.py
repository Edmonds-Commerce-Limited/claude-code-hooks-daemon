"""No test may skip, xfail or early-return because the process is root.

Plan 00351 found `test_skills.py` guarding a permission test with
`Path("/").stat().st_uid == 0` under the reason "Running as root" — a
condition that asks who owns `/` (uid 0 on every normal Linux system,
whoever is running), not who is running, so it was a constant `True` and the
test never ran anywhere. That plan's fix keyed on the REASON text (does it
claim root?) rather than the condition, and this file's first cut of the N56
detector regressed that: it matched only a literal `geteuid()`/`getuid()`
call compared to `0`, which misses Plan 00351's own shape and everything
between it and a bare `geteuid() == 0` (review 1, F1/F2).

Review 2 (B1) found the *name*-matching approach itself was the defect: an
alias, a local variable holding a raw uid value, an `AnnAssign`, a lambda, a
parameterised helper, `pwd`/`grp` subscripts, an env var check, `Path.home`,
`os.access`, `Path.stat().st_uid`, `unittest.skipUnless`, an `IfExp` marker
and a conftest collection hook all evaded it, because each is a different
*name* for the same *data flow*. This rewrite keys on DATA FLOW instead:

- **Identity-source classification** (`_identity_kind`): any expression that
  is, or is derived from, a call that answers "who is running this process" —
  `geteuid`/`getuid`/`getegid`/`getgid`/`getresuid`/`getresgid`,
  `getpass.getuser`, a `pwd`/`grp` lookup (and its `.pw_name`/`.pw_uid`/
  `.gr_name`/`.gr_gid` fields or positional subscript), `os.environ`/
  `os.getenv` of `USER`/`LOGNAME`/`HOME`/`SUDO_*`, `Path.home()`/
  `os.path.expanduser("~")`, `os.access(...)`, and `<expr>.stat().st_uid` — is
  tainted, through an alias (`from os import geteuid as euid`, `_uid =
  os.geteuid`), a local variable, a module-level constant (`Assign` or
  `AnnAssign`), and one level of same-module helper function (a `def` or a
  zero-arg `lambda`, including a parameterised helper called with literal
  arguments, its parameters substituted before evaluation).
- **Condition analysis** (`_is_root_expr`) flags a condition that compares an
  identity-source value against 0 / `"root"` / another identity-source value,
  that uses one bare (a truthiness check, `not`, arithmetic, a walrus), or
  that is a resolved boolean name/helper — recursing through `BoolOp`,
  `UnaryOp`, `IfExp` and a *string* condition (pytest accepts one).
- **Reason-text analysis**, independent of the condition, so a skip whose
  stated reason names root — Plan 00351's own defect — fails whatever its
  condition actually tests.
- **Collection-hook analysis** (`_collection_hook_findings`): a
  `pytest_ignore_collect` whose return value is an identity condition, or a
  `pytest_collection_modifyitems`/`pytest_runtest_setup` whose root-guarded
  branch calls `item.add_marker(...)`, clears/mutates the items list, or does
  anything else this file already treats as skip-like.
- **Unproven references** (review 2's "computed attribute or a helper in
  another module"): a name/attribute this scan cannot resolve — a
  cross-module import, a class attribute — is not silently passed when its
  own spelling (case-insensitively) names root/uid/gid/privilege/sudo; it is
  reported as `kind="unproven"` instead, since the alternative is treating
  "cannot analyse" as "cannot be a violation".

Plan 00466 N56: the owner set the rule directly. This container, and the
dogfood server, run as root — so a root-guarded skip is a test that never
runs where the work happens. Every test in this repository must prove its
behaviour as root; permission checks that root bypasses need a different
fault (an injected `PermissionError`, a directory or dangling symlink in the
path's place, or patching the specific OS call), not a skip.

This is a blanket static scan of every `.py` file under `tests/` — not just
`test_*.py`/`conftest.py` — because a root-conditioned skip in a helper
module regresses this rule exactly like one in a test module. Review 2 (B2)
found the scan's own exclusion list (a `fixtures`/`assets`/`__fixtures__`
directory name, and the detector's own file) was itself a hole pytest would
actually collect through; there is no exclusion list any more. A file that
fails to parse is either something pytest would import (`test_*.py`,
`conftest.py`, or a module this file's own scan can reach) — an unparseable
one of those is a genuine failure — or it is not, in which case a note is
logged and the file is treated as clean rather than failing the whole scan
for a fixture that was never going to run.
"""

from __future__ import annotations

import ast
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import pytest

TESTS_ROOT = Path(__file__).resolve().parents[1]

#: Identity-source call names, matched on the RESOLVED bare name (after alias
#: resolution) — never on the literal source spelling, so
#: `from os import geteuid as euid` and `_uid = os.geteuid` are covered the
#: same as `os.geteuid`.
_UID_GID_VALUE_CALLS = frozenset({"geteuid", "getuid", "getegid", "getgid"})
_RESUID_CALLS = frozenset({"getresuid", "getresgid"})
_PW_LOOKUP_CALLS = frozenset({"getpwuid", "getpwnam"})
_GRP_LOOKUP_CALLS = frozenset({"getgrgid", "getgrnam"})
_USER_STRING_CALLS = frozenset({"getuser"})
_HOME_CALLS = frozenset({"home"})
_ACCESS_CALLS = frozenset({"access"})
_ENV_GET_DOTTED = frozenset({"os.environ.get", "environ.get", "os.getenv", "getenv"})
_ENV_IDENTITY_KEYS = frozenset({"USER", "LOGNAME", "HOME"})

#: `pytest.mark.<name>` / `unittest.<name>` decorators whose condition is
#: evaluated at collection time — any can hide a test from ever running.
#: Matched case-insensitively so `unittest.skipIf`/`skipUnless` count.
_CONDITIONAL_MARKS = frozenset({"skipif", "xfail", "skipunless"})

#: Wording that makes a reader believe a skip is about the running user,
#: independent of what its condition actually tests (Plan 00351's shape).
_ROOT_REASON_WORDS = (
    "as root",
    "running as root",
    "is root",
    "under root",
    "root user",
    "uid 0",
    "superuser",
    "unprivileged",
    "an unprivileged user",
)

#: A name/attribute this scan cannot resolve (cross-module import, class
#: attribute) is reported rather than passed when its own spelling suggests
#: it is about process identity — review 2's UNPROVEN category.
_UNPROVEN_NAME_WORDS = ("root", "uid", "gid", "priv", "sudo", "superuser")

#: conftest collection hooks whose control flow can hide a test from running.
_COLLECTION_HOOK_NAMES = frozenset(
    {"pytest_collection_modifyitems", "pytest_runtest_setup", "pytest_ignore_collect"}
)
#: For this one, the RETURN VALUE (not a nested skip call) IS the decision.
_HOOK_RETURN_IS_DECISION = frozenset({"pytest_ignore_collect"})


@dataclass(frozen=True)
class RootConditionedSkip:
    """A place a test's execution is gated on the process's own identity."""

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


def _bare_name(dotted: str) -> str:
    return dotted.rsplit(".", 1)[-1] if dotted else ""


def _is_zero_constant(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and not isinstance(node.value, bool) and node.value == 0


def _is_root_string_constant(node: ast.expr) -> bool:
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
        return False
    value = node.value.strip().lower()
    return value in {"root", "/root"}


def _contains_zero(node: ast.expr) -> bool:
    """A bare `0`, or a tuple/list/set literal containing one (`in (0,)`)."""
    if _is_zero_constant(node):
        return True
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(_is_zero_constant(elt) for elt in node.elts)
    return False


def _is_identity_env_key(node: ast.expr | None) -> bool:
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
        return False
    key = node.value
    return key in _ENV_IDENTITY_KEYS or key.startswith("SUDO_")


def _snippet(source: str, node: ast.expr | ast.stmt) -> str:
    return (ast.get_source_segment(source, node) or "").strip()


# --------------------------------------------------------------------------
# Resolution context: aliases, module/local constants, one-level helpers
# --------------------------------------------------------------------------


@dataclass
class _ResolutionContext:
    """Names and helpers statically known to carry identity information.

    `root_names`/`root_funcs` already resolve to a *boolean* ("is root").
    `value_names`/`value_funcs` resolve to a raw identity *value* (an int
    uid/gid, a user/home string, a pwd/grp record) that becomes a root
    signal only once compared. `call_aliases` maps a locally bound name to
    the canonical bare identity-call name it refers to.
    """

    root_names: set[str] = field(default_factory=set)
    root_funcs: set[str] = field(default_factory=set)
    value_names: set[str] = field(default_factory=set)
    value_funcs: set[str] = field(default_factory=set)
    call_aliases: dict[str, str] = field(default_factory=dict)
    funcdefs: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(default_factory=dict)
    lambdas: dict[str, ast.Lambda] = field(default_factory=dict)
    #: Every name this scan COULD analyse (a module/local assignment target,
    #: regardless of what it resolved to) — a name here that did NOT land in
    #: `root_names`/`value_names` was checked and found unrelated, which is a
    #: different fact from "never checked". Only the latter is UNPROVEN.
    all_assigned_names: set[str] = field(default_factory=set)


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
        for field_name in ("body", "orelse", "finalbody"):
            nested = getattr(stmt, field_name, None)
            if nested:
                out.extend(_non_nested_statements(nested))
    return out


def _assign_targets(stmt: ast.stmt) -> list[tuple[str, ast.expr]]:
    """`(name, value)` pairs from an `Assign` or a simple `AnnAssign`."""
    if isinstance(stmt, ast.Assign):
        out = []
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                out.append((target.id, stmt.value))
        return out
    if (
        isinstance(stmt, ast.AnnAssign)
        and isinstance(stmt.target, ast.Name)
        and stmt.value is not None
    ):
        return [(stmt.target.id, stmt.value)]
    return []


def _build_call_aliases(tree: ast.Module) -> dict[str, str]:
    """`from os import geteuid as euid` and `_uid = os.geteuid` (unaliased
    reference to a function object, not a call) both bind a local name to a
    canonical identity-call name.
    """
    known = (
        _UID_GID_VALUE_CALLS
        | _RESUID_CALLS
        | _PW_LOOKUP_CALLS
        | _GRP_LOOKUP_CALLS
        | _USER_STRING_CALLS
        | _HOME_CALLS
        | _ACCESS_CALLS
    )
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in known:
                    aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
            if isinstance(target, ast.Name) and not isinstance(value, ast.Call):
                bare = _bare_name(_dotted_name(value))
                if bare in known:
                    aliases[target.id] = bare
    return aliases


def _resolve_context(tree: ast.Module) -> _ResolutionContext:
    """Fixed-point resolution of module-level root-indicating names/helpers.

    Bounded to a handful of passes: a constant referencing a helper that
    references another constant is already an unrealistic chain for a test
    module, so this never approaches the cap in practice.
    """
    ctx = _ResolutionContext(call_aliases=_build_call_aliases(tree))
    assigns = [n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign))]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ctx.funcdefs[node.name] = node
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            if isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Lambda):
                ctx.lambdas[node.targets[0].id] = node.value

    for assign in assigns:
        for name, _value in _assign_targets(assign):
            ctx.all_assigned_names.add(name)

    for _ in range(6):
        changed = False
        for assign in assigns:
            for name, value in _assign_targets(assign):
                if name not in ctx.root_names and _is_root_expr(value, ctx):
                    ctx.root_names.add(name)
                    changed = True
                elif name not in ctx.value_names and _identity_kind(value, ctx) is not None:
                    ctx.value_names.add(name)
                    changed = True
        for name, lam in ctx.lambdas.items():
            if lam.args.args or lam.args.posonlyargs or lam.args.kwonlyargs:
                continue
            if name not in ctx.root_funcs and _is_root_expr(lam.body, ctx):
                ctx.root_funcs.add(name)
                changed = True
            elif name not in ctx.value_funcs and _identity_kind(lam.body, ctx) is not None:
                ctx.value_funcs.add(name)
                changed = True
        for name, func in ctx.funcdefs.items():
            if func.args.args or func.args.posonlyargs or func.args.kwonlyargs:
                continue  # parameterised helpers are resolved per call site
            if name in ctx.root_funcs:
                continue
            local_ctx = _local_context(func.body, ctx)
            for stmt in _non_nested_statements(func.body):
                if isinstance(stmt, ast.Return) and stmt.value is not None:
                    if _is_root_expr(stmt.value, local_ctx):
                        ctx.root_funcs.add(name)
                        changed = True
                        break
                    if (
                        name not in ctx.value_funcs
                        and _identity_kind(stmt.value, local_ctx) is not None
                    ):
                        ctx.value_funcs.add(name)
                        changed = True
        if not changed:
            break
    return ctx


def _local_context(body: list[ast.stmt], ctx: _ResolutionContext) -> _ResolutionContext:
    """Extend `ctx` with names assigned earlier in the SAME function body
    (`euid = os.geteuid(); return euid == 0`) — scoped to this call only.
    """
    local = _ResolutionContext(
        root_names=set(ctx.root_names),
        root_funcs=set(ctx.root_funcs),
        value_names=set(ctx.value_names),
        value_funcs=set(ctx.value_funcs),
        call_aliases=ctx.call_aliases,
        funcdefs=ctx.funcdefs,
        lambdas=ctx.lambdas,
        all_assigned_names=set(ctx.all_assigned_names),
    )
    for stmt in _non_nested_statements(body):
        for name, value in _assign_targets(stmt):
            local.all_assigned_names.add(name)
            if _is_root_expr(value, local):
                local.root_names.add(name)
            elif _identity_kind(value, local) is not None:
                local.value_names.add(name)
    return local


def _substitute(node: ast.expr, mapping: dict[str, ast.expr]) -> ast.expr:
    """Replace every `Name` in `mapping` with its bound constant, so a
    parameterised helper's return expression can be evaluated at a call
    site that passes literal arguments (`def _uid_is(n): return
    os.geteuid() == n` then `_uid_is(0)`).
    """

    class _Sub(ast.NodeTransformer):
        def visit_Name(self, node: ast.Name) -> ast.expr:
            return mapping.get(node.id, node)

    clone = ast.parse(ast.unparse(node), mode="eval").body
    result = ast.fix_missing_locations(_Sub().visit(clone))
    assert isinstance(result, ast.expr)
    return result


def _call_with_substituted_params(call: ast.Call, ctx: _ResolutionContext) -> ast.expr | None:
    """For a call to a same-module helper with parameters, all supplied as
    positional literal constants, return its `return` expression with the
    parameters substituted — `None` if the helper can't be resolved this way.
    """
    if not isinstance(call.func, ast.Name):
        return None
    func = ctx.funcdefs.get(call.func.id)
    if func is None or func.args.posonlyargs or func.args.kwonlyargs or func.args.vararg:
        return None
    params = func.args.args
    if len(call.args) != len(params) or call.keywords:
        return None
    if not all(isinstance(a, ast.Constant) for a in call.args):
        return None
    mapping = {p.arg: a for p, a in zip(params, call.args, strict=True)}
    for stmt in _non_nested_statements(func.body):
        if isinstance(stmt, ast.Return) and stmt.value is not None:
            try:
                return _substitute(stmt.value, mapping)
            except (SyntaxError, ValueError):
                return None
    return None


# --------------------------------------------------------------------------
# Identity-source classification (data flow, not names)
# --------------------------------------------------------------------------


def _resolved_bare_call_name(func: ast.expr, ctx: _ResolutionContext) -> str:
    if isinstance(func, ast.Name) and func.id in ctx.call_aliases:
        return ctx.call_aliases[func.id]
    return _bare_name(_dotted_name(func))


def _identity_kind(node: ast.expr, ctx: _ResolutionContext) -> str | None:
    """Classify `node` as an identity source: `"value"` (raw uid/gid int),
    `"user"` (a user-identifying string), `"path"` (a home-directory path),
    `"bool"` (already a yes/no identity signal), `"restuple"` (the 3-tuple
    `getresuid()`/`getresgid()` returns) or `"pwrecord"` (a pwd/grp struct) —
    or `None` if it is not identity-related. `_is_root_expr` decides whether
    a *use* of one of these is actually root-conditioned.
    """
    if isinstance(node, ast.NamedExpr):
        return _identity_kind(node.value, ctx)
    if isinstance(node, ast.Call):
        bare = _resolved_bare_call_name(node.func, ctx)
        dotted = _dotted_name(node.func)
        if bare in _UID_GID_VALUE_CALLS:
            return "value"
        if bare in _RESUID_CALLS:
            return "restuple"
        if bare in _USER_STRING_CALLS:
            return "user"
        if bare in _PW_LOOKUP_CALLS or bare in _GRP_LOOKUP_CALLS:
            return "pwrecord"
        if bare in _HOME_CALLS:
            return "path"
        if bare == "expanduser" and node.args and isinstance(node.args[0], ast.Constant):
            return "path" if node.args[0].value == "~" else None
        if bare in _ACCESS_CALLS:
            return "bool"
        if dotted in _ENV_GET_DOTTED and node.args and _is_identity_env_key(node.args[0]):
            return "user"
        if bare == "bool" and len(node.args) == 1 and not node.keywords:
            return _identity_kind(node.args[0], ctx)
        if bare in ctx.value_funcs:
            return "value"
        substituted = _call_with_substituted_params(node, ctx)
        if substituted is not None:
            return _identity_kind(substituted, ctx)
        return None
    if isinstance(node, ast.Attribute):
        if node.attr == "st_uid":
            return "value"
        base_kind = _identity_kind(node.value, ctx)
        if base_kind == "pwrecord" and node.attr in {"pw_uid", "gr_gid"}:
            return "value"
        if base_kind == "pwrecord" and node.attr in {"pw_name", "gr_name"}:
            return "user"
        return None
    if isinstance(node, ast.Subscript):
        base_kind = _identity_kind(node.value, ctx)
        key = node.slice
        if base_kind == "restuple":
            return "value"
        if base_kind == "pwrecord" and isinstance(key, ast.Constant):
            if key.value == 0:
                return "user"
            if key.value == 2:
                return "value"
            return None
        base_dotted = _dotted_name(node.value)
        if base_dotted in {"os.environ", "environ"} and _is_identity_env_key(key):
            return "user"
        return None
    if isinstance(node, ast.Name):
        if node.id in ctx.value_names:
            return "value"
        return None
    if isinstance(node, ast.BinOp):
        return _identity_kind(node.left, ctx) or _identity_kind(node.right, ctx)
    if isinstance(node, ast.UnaryOp) and not isinstance(node.op, ast.Not):
        return _identity_kind(node.operand, ctx)
    return None


def _is_unproven_identity_ref(node: ast.expr, ctx: _ResolutionContext) -> bool:
    """A `Name`/`Attribute`/`Call` this scan cannot resolve (cross-module
    import, class attribute, a helper in another module), whose own
    spelling suggests it is about process identity. Reported rather than
    silently passed — review 2's UNPROVEN category.
    """
    if isinstance(node, ast.Name):
        if node.id in ctx.root_names or node.id in ctx.value_names:
            return False
        if node.id in ctx.all_assigned_names:
            return False  # resolvable locally, and resolved to non-identity
        candidate = node.id
    elif isinstance(node, ast.Attribute):
        if _identity_kind(node, ctx) is not None:
            return False
        candidate = node.attr
    elif isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute)):
        bare = _resolved_bare_call_name(node.func, ctx)
        if (
            bare in ctx.root_funcs
            or bare in ctx.value_funcs
            or _identity_kind(node, ctx) is not None
        ):
            return False
        if bare in ctx.funcdefs or bare in ctx.lambdas:
            return False  # resolvable locally, and resolved to non-identity
        candidate = bare
    else:
        return False
    # Restricted to SCREAMING_SNAKE_CASE / PascalCase-constant spellings (an
    # imported flag, a class attribute) so this heuristic does not fire on
    # this detector's OWN lowercase identifiers (`ctx.root_names`,
    # `_is_root_expr`) during the whole-repo self-scan (review 2, B2) — those
    # are ordinary snake_case code, not the ALL-CAPS-constant shape every
    # SHOULD_FIND fixture for this category uses (`IS_ROOT`, `C.ROOT`).
    stripped = candidate.strip("_")
    if not stripped or not stripped[0].isupper():
        return False
    lowered = candidate.lower()
    return any(word in lowered for word in _UNPROVEN_NAME_WORDS)


# --------------------------------------------------------------------------
# Condition analysis
# --------------------------------------------------------------------------


def _is_root_expr(node: ast.expr, ctx: _ResolutionContext) -> bool:
    """Whether `node` — a condition, or a sub-expression of one — tests root."""
    if isinstance(node, ast.NamedExpr):
        return _is_root_expr(node.value, ctx) or _identity_kind(node.value, ctx) is not None

    if isinstance(node, ast.Name):
        return node.id in ctx.root_names or _is_unproven_identity_ref(node, ctx)

    if isinstance(node, ast.Attribute):
        return _identity_kind(node, ctx) is not None or _is_unproven_identity_ref(node, ctx)

    if isinstance(node, ast.Call):
        bare = _resolved_bare_call_name(node.func, ctx)
        if bare in ctx.root_funcs:
            return True
        if _identity_kind(node, ctx) is not None:
            return True
        substituted = _call_with_substituted_params(node, ctx)
        if substituted is not None and _is_root_expr(substituted, ctx):
            return True
        return _is_unproven_identity_ref(node, ctx)

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return _is_root_expr(node.operand, ctx) or _identity_kind(node.operand, ctx) is not None

    if isinstance(node, ast.BoolOp):
        return any(_is_root_expr(value, ctx) for value in node.values)

    if isinstance(node, ast.IfExp):
        return _is_root_expr(node.test, ctx)

    if isinstance(node, ast.Compare):
        operands = [node.left, *node.comparators]

        if any(_identity_kind(o, ctx) is not None for o in operands):
            return True

        has_root_string = any(_is_root_string_constant(o) for o in operands)
        if has_root_string and any(_identity_kind(o, ctx) == "user" for o in operands):
            return True
        if has_root_string and any(
            isinstance(o, ast.Attribute) and o.attr in {"pw_name", "gr_name"} for o in operands
        ):
            return True

        has_zero = any(_contains_zero(o) for o in operands)
        if has_zero and any(_identity_kind(o, ctx) is not None for o in operands):
            return True

        for operand in operands:
            if isinstance(operand, ast.Name) and operand.id in ctx.root_names:
                return True
            if isinstance(operand, ast.Call) and _is_root_expr(operand, ctx):
                return True
            if _is_unproven_identity_ref(operand, ctx):
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

    kind = _identity_kind(node, ctx)
    return kind is not None


# --------------------------------------------------------------------------
# Reason-text analysis — independent of the condition (Plan 00351's shape)
# --------------------------------------------------------------------------

#: The exact (case-insensitive) final dotted component of a call that is a
#: real skip mechanism. Exact match, not substring — `skip_is_a_provisioning_
#: failure(...)` (a real helper in this repo) contains "skip" but is not one.
_SKIP_LIKE_FINAL_NAMES = frozenset({"skip", "skipif", "xfail", "skiptest", "importorskip", "exit"})


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
# Decorator findings: skipif / xfail / skipUnless, condition= or positional
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
# `maybe = pytest.mark.skip(...) if <root check> else ...` (an IfExp marker)
# --------------------------------------------------------------------------


def _expr_is_skip_marker(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and _looks_like_skip_related(node)


def _ifexp_findings(
    source: str, tree: ast.Module, ctx: _ResolutionContext
) -> list[RootConditionedSkip]:
    found: list[RootConditionedSkip] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.IfExp):
            continue
        if not _is_root_expr(node.test, ctx):
            continue
        if _expr_is_skip_marker(node.body) or _expr_is_skip_marker(node.orelse):
            found.append(
                RootConditionedSkip(line=node.lineno, kind="ifexp", snippet=_snippet(source, node))
            )
    return found


# --------------------------------------------------------------------------
# Hand-written `if <root check>: skip/xfail/skipTest/raise-skip/return`
# --------------------------------------------------------------------------


def _guarded_action(stmts: list[ast.stmt]) -> tuple[str, ast.stmt] | None:
    """The first skip/xfail/return/item-mutation reachable from `stmts`
    without crossing into a nested function/class — see
    `_non_nested_statements`. `add_marker`/`clear` cover the two ways a
    conftest collection hook can hide a test without ever naming a "skip".
    """
    for stmt in _non_nested_statements(stmts):
        if isinstance(stmt, ast.Return):
            return ("return", stmt)
        if isinstance(stmt, ast.Raise) and isinstance(stmt.exc, ast.Call):
            if _looks_like_skip_related(stmt.exc):
                return ("skip-or-xfail", stmt)
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            if _looks_like_skip_related(call):
                return ("skip-or-xfail", stmt)
            attr = call.func.attr if isinstance(call.func, ast.Attribute) else None
            if attr in {"add_marker", "clear"}:
                return ("collection-hook", stmt)
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


# --------------------------------------------------------------------------
# Collection hooks: pytest_ignore_collect / pytest_collection_modifyitems /
# pytest_runtest_setup
# --------------------------------------------------------------------------


def _collection_hook_findings(
    source: str, tree: ast.Module, ctx: _ResolutionContext
) -> list[RootConditionedSkip]:
    found: list[RootConditionedSkip] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in _COLLECTION_HOOK_NAMES:
            continue
        if node.name in _HOOK_RETURN_IS_DECISION:
            for stmt in _non_nested_statements(node.body):
                if (
                    isinstance(stmt, ast.Return)
                    and stmt.value is not None
                    and _is_root_expr(stmt.value, ctx)
                ):
                    found.append(
                        RootConditionedSkip(
                            line=stmt.lineno, kind="collection-hook", snippet=_snippet(source, stmt)
                        )
                    )
        else:
            for stmt in _non_nested_statements(node.body):
                if not (isinstance(stmt, ast.If) and _is_root_expr(stmt.test, ctx)):
                    continue
                if _guarded_action(stmt.body) or _guarded_action(stmt.orelse):
                    found.append(
                        RootConditionedSkip(
                            line=stmt.lineno, kind="collection-hook", snippet=_snippet(source, stmt)
                        )
                    )
    return found


def root_conditioned_skips(source: str) -> list[RootConditionedSkip]:
    """Every place `source` gates a test's execution on the process's own identity."""
    tree = ast.parse(source)
    ctx = _resolve_context(tree)
    by_line: dict[int, RootConditionedSkip] = {}
    for finding in (
        _decorator_findings(source, tree, ctx)
        + _if_guarded_findings(source, tree, ctx)
        + _reason_findings(source, tree)
        + _ifexp_findings(source, tree, ctx)
        + _collection_hook_findings(source, tree, ctx)
    ):
        by_line.setdefault(finding.line, finding)
    return [by_line[line] for line in sorted(by_line)]


# --------------------------------------------------------------------------
# Regression fixtures — one per evasion shape review 1 and review 2 named
# (F1, F2, B1), plus review 1's regression shape (F1). Each is SHOULD_FIND
# unless named otherwise.
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
    # -- review 2 (B1) evasions --------------------------------------------
    "alias_from_import_as": """
from os import geteuid as euid
import pytest
@pytest.mark.skipif(euid() == 0, reason='x')
def test_a(): ...
""",
    "alias_assigned_function": """
import os, pytest
_uid = os.geteuid
@pytest.mark.skipif(_uid() == 0, reason='x')
def test_a(): ...
""",
    "module_EUID_value_then_compare": """
import os, pytest
EUID = os.geteuid()
@pytest.mark.skipif(EUID == 0, reason='x')
def test_a(): ...
""",
    "helper_local_var": """
import os, pytest
def _is_root():
    euid = os.geteuid()
    return euid == 0
@pytest.mark.skipif(_is_root(), reason='x')
def test_a(): ...
""",
    "helper_with_param": """
import os, pytest
def _uid_is(n):
    return os.geteuid() == n
@pytest.mark.skipif(_uid_is(0), reason='x')
def test_a(): ...
""",
    "getpass_root_bareword": """
import getpass, pytest
@pytest.mark.skipif(getpass.getuser() == 'root', reason='x')
def test_a(): ...
""",
    "os_getuid_eq0_bareword": """
import os, pytest
@pytest.mark.skipif(os.getuid() == 0, reason='x')
def test_a(): ...
""",
    "pwd_subscript": """
import os, pwd, pytest
@pytest.mark.skipif(pwd.getpwuid(os.geteuid())[0] == 'root', reason='x')
def test_a(): ...
""",
    "pwd_getpwnam_uid": """
import os, pwd, pytest
@pytest.mark.skipif(pwd.getpwnam('root').pw_uid == os.geteuid(), reason='x')
def test_a(): ...
""",
    "env_USER_get": """
import os, pytest
@pytest.mark.skipif(os.environ.get('USER') == 'root', reason='x')
def test_a(): ...
""",
    "env_USER_getenv": """
import os, pytest
@pytest.mark.skipif(os.getenv('USER') == 'root', reason='x')
def test_a(): ...
""",
    "env_USER_subscript": """
import os, pytest
@pytest.mark.skipif(os.environ['USER'] == 'root', reason='x')
def test_a(): ...
""",
    "env_HOME_root": """
import os, pytest
@pytest.mark.skipif(os.path.expanduser('~') == '/root', reason='x')
def test_a(): ...
""",
    "lt_one": """
import os, pytest
@pytest.mark.skipif(os.geteuid() < 1, reason='x')
def test_a(): ...
""",
    "getresuid": """
import os, pytest
@pytest.mark.skipif(os.getresuid()[1] == 0, reason='x')
def test_a(): ...
""",
    "os_access_probe": """
import os, pytest
@pytest.mark.skipif(os.access('/etc/shadow', os.R_OK), reason='x')
def test_a(): ...
""",
    "unittest_skipUnless": """
import os, unittest
class T(unittest.TestCase):
    @unittest.skipUnless(os.geteuid() != 0, 'x')
    def test_a(self): ...
""",
    "ifexp_skip_marker": """
import os, pytest
maybe = pytest.mark.skip(reason='x') if os.geteuid() == 0 else pytest.mark.usefixtures()
@maybe
def test_a(): ...
""",
    "conftest_ignore_collect": """
import os
def pytest_ignore_collect(collection_path, config):
    return os.geteuid() == 0
""",
    "conftest_modifyitems_add_marker": """
import os, pytest
def pytest_collection_modifyitems(config, items):
    if os.geteuid() == 0:
        for item in items:
            item.add_marker(pytest.mark.skip(reason='x'))
""",
    "conftest_modifyitems_clear": """
import os
def pytest_collection_modifyitems(config, items):
    if os.geteuid() == 0:
        items.clear()
""",
    "conftest_runtest_setup_skip": """
import os, pytest
def pytest_runtest_setup(item):
    if os.geteuid() == 0:
        pytest.skip('x')
""",
    "importorskip_gate": """
import os, pytest
def test_a():
    if os.geteuid() == 0:
        pytest.importorskip('no_such_module_xyz')
""",
    "pytest_exit": """
import os, pytest
def test_a():
    if os.geteuid() == 0:
        pytest.exit('x')
""",
    "raise_SkipTest": """
import os, unittest
def test_a():
    if os.geteuid() == 0:
        raise unittest.SkipTest('x')
""",
    "walrus": """
import os, pytest
@pytest.mark.skipif((u := os.geteuid()) == 0, reason='x')
def test_a(): ...
""",
    "reason_root_user": """
import sys, pytest
@pytest.mark.skipif(sys.platform == 'x', reason='root user bypasses modes')
def test_a(): ...
""",
    "reason_uid_0": """
import sys, pytest
@pytest.mark.skipif(sys.platform == 'x', reason='uid 0 ignores chmod')
def test_a(): ...
""",
    "reason_superuser": """
import sys, pytest
@pytest.mark.skipif(sys.platform == 'x', reason='superuser ignores chmod')
def test_a(): ...
""",
    "reason_privileged": """
import sys, pytest
@pytest.mark.skipif(sys.platform == 'x', reason='needs an unprivileged user')
def test_a(): ...
""",
    "geteuid_plus_zero": """
import os, pytest
@pytest.mark.skipif(os.geteuid() + 0 == 0, reason='x')
def test_a(): ...
""",
    "bool_not_uid": """
import os, pytest
@pytest.mark.skipif(not bool(os.geteuid()), reason='x')
def test_a(): ...
""",
    "is_not_zero_truthy": """
import os, pytest
def test_a():
    if os.geteuid():
        assert True
    else:
        pytest.skip('x')
""",
    "annassign_constant": """
import os, pytest
IS_ROOT: bool = os.geteuid() == 0
@pytest.mark.skipif(IS_ROOT, reason='x')
def test_a(): ...
""",
    "imported_constant": """
import pytest
from tests.helpers import IS_ROOT
@pytest.mark.skipif(IS_ROOT, reason='x')
def test_a(): ...
""",
    "lambda_helper": """
import os, pytest
_is_root = lambda: os.geteuid() == 0
@pytest.mark.skipif(_is_root(), reason='x')
def test_a(): ...
""",
    "root_class_attr": """
import os, pytest
class C:
    ROOT = os.geteuid() == 0
@pytest.mark.skipif(C.ROOT, reason='x')
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
    "unrelated_env_get": """
import os, pytest
@pytest.mark.skipif(os.environ.get('CI') == 'true', reason='CI only')
def test_a(): ...
""",
    "unrelated_collection_hook": """
import pytest
def pytest_collection_modifyitems(config, items):
    for item in items:
        if "slow" in item.keywords and not config.getoption("--run-slow"):
            item.add_marker(pytest.mark.skip(reason="needs --run-slow"))
""",
    "access_used_non_skip": """
import os
def test_a(tmp_path):
    p = tmp_path / "f"
    assert os.access(p, os.W_OK) or True
""",
}


class TestEveryEvasionShapeIsCaught:
    """One assertion per shape review 1 (F1, F2) and review 2 (B1) named."""

    @pytest.mark.parametrize("name", sorted(_SHOULD_FIND), ids=lambda n: n)
    def test_shape_is_found(self, name: str) -> None:
        found = root_conditioned_skips(_SHOULD_FIND[name])
        assert found, f"{name}: expected a root-conditioned skip to be found"


class TestNoFalsePositives:
    @pytest.mark.parametrize("name", sorted(_SHOULD_NOT_FIND), ids=lambda n: n)
    def test_shape_is_clean(self, name: str) -> None:
        found = root_conditioned_skips(_SHOULD_NOT_FIND[name])
        assert found == [], f"{name}: expected no finding, got {found!r}"


# --------------------------------------------------------------------------
# The repository itself — no exclusion list (review 2, B2): every `.py`
# under `tests/` is scanned, including this file and any `fixtures/`-named
# directory pytest would actually collect. A file that pytest would never
# import (not `test_*.py`/`conftest.py`) and that fails to parse is logged
# and treated as clean; an unparseable `test_*.py`/`conftest.py` fails.
# --------------------------------------------------------------------------


def _test_sources() -> list[Path]:
    return sorted(path for path in TESTS_ROOT.rglob("*.py") if "__pycache__" not in path.parts)


def _pytest_would_import(path: Path) -> bool:
    return path.name == "conftest.py" or path.name.startswith("test_")


class TestTheRepositoryItself:
    def test_there_is_something_to_check(self) -> None:
        """A scan that matches nothing would pass forever without checking."""
        assert _test_sources(), "no test modules found to scan"

    @pytest.mark.parametrize("path", _test_sources(), ids=lambda p: p.name)
    def test_no_root_conditioned_skip_exists(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        try:
            findings = root_conditioned_skips(text)
        except SyntaxError as exc:
            if _pytest_would_import(path):
                pytest.fail(
                    f"{path.relative_to(TESTS_ROOT)} is not valid Python "
                    f"({exc}), and pytest would import it as a test module."
                )
            warnings.warn(
                f"{path.relative_to(TESTS_ROOT)} is not valid Python ({exc}); "
                "skipped because pytest would never collect it (not "
                "test_*.py/conftest.py).",
                stacklevel=1,
            )
            return
        for finding in findings:
            pytest.fail(
                f"{path.relative_to(TESTS_ROOT)}:{finding.line} skips this process's own "
                f"identity ({finding.kind}): {finding.snippet!r}\n"
                "Every test must run as root (Plan 00466 N56). Root bypasses file mode "
                "bits, so fault the operation another way instead: monkeypatch the "
                "specific os/open/Path call to raise PermissionError, replace the file "
                "with a directory or a dangling symlink, or patch the exact check the "
                "code under test performs."
            )
