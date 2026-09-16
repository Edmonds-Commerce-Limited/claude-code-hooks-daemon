#!/usr/bin/env python3
"""Fail when two sites this repository has already reasoned about disagree.

The class -- `asymmetric-sibling-protection` -- is the largest in the run
2026-001 security corpus: thirteen instances drawn from eight reports that
never saw each other. Three reviewers reached for almost identical phrasing
without coordination ("the escaper already exists, in this module, twenty lines
above"), and that convergence is the strongest ranking signal in the review.

**It has no syntactic signature.** Nothing about either site is wrong on its
own; it is wrong only RELATIVE to its sibling. A rule that reads one site can
therefore never find a member, and a rule that tries to PROPOSE pairs -- by
noticing two handlers that judge the same command -- is noisy enough that it
must not gate a build.

So the Defence is a checked-in registry. A human who has read both sides
declares the pair and the relation; this script asserts the relation
mechanically on every run. False positives are near zero by construction,
because every row was written by someone looking at both files.

**The blind spot is the price, and it belongs in the category**: a registry
only covers declared pairs. A divergence with no row is invisible. Adding a row
is the whole of how this Defence grows.

Two properties were bought by checking rows against the code they name rather
than trusting the worklist that proposed them:

- A row declares which MEMBERS participate, not just two symbol names. The
  first row drafted asserted a superset between two verb alternations that were
  each missing members of the other; a naive set comparison would have reported
  a violation in both directions and neither would have been the defect. A
  check that opens with noise gets switched off rather than satisfied.
- An extractor SKIPS an entry it cannot read literally rather than guessing.
  The pipe whitelist mixes plain literals with f-strings built from a shared
  git grammar; inventing a member from one would be a false positive, while
  skipping it merely under-reports.

A renamed file or symbol raises rather than returning an empty set. An empty
set is disjoint from everything, so a rotted row would otherwise read as a row
that passes -- the exact failure a registry exists to prevent.

Usage:
    python scripts/qa/check_declared_invariant_pairs.py [--json] [--registry F]

Exit codes:
    0 -- every declared relation holds
    1 -- at least one relation is violated, or a row has rotted
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

import yaml

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR: Final[Path] = _REPO_ROOT / "untracked" / "qa"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / "declared_invariant_pairs.json"
_DEFAULT_REGISTRY: Final[Path] = _REPO_ROOT / "scripts" / "qa" / "declared-invariant-pairs.yaml"

_RULE: Final[str] = "declared-invariant-pairs"

#: Relations a row may declare. A typo must be rejected at load rather than
#: silently skipped, or the row reads as one that passes.
#:
#: ``disjoint``     -- the two member sets must not overlap.
#: ``superset``     -- every member of the RIGHT side must appear on the LEFT.
#: ``reaches``      -- both sites must CALL the row's ``helper``.
#: ``interpolates`` -- both symbols must REFERENCE the row's ``helper``.
_RELATIONS: Final[frozenset[str]] = frozenset({"disjoint", "superset", "reaches", "interpolates"})

#: Relations whose sides name a FUNCTION and a helper rather than a symbol
#: holding a member set. The class's instances split roughly evenly between the
#: two shapes, and a constant-only registry could express only half of them.
_CALL_PATH_RELATIONS: Final[frozenset[str]] = frozenset({"reaches"})

#: Relations whose sides name a SYMBOL that must be built from a shared
#: fragment. Needed because a shared regex fragment is a constant interpolated
#: into a pattern, not a function called from a body, so `reaches` would read a
#: correct fix as a violation.
_FRAGMENT_RELATIONS: Final[frozenset[str]] = frozenset({"interpolates"})

#: Relations that carry a `helper` naming what both sides must share.
_HELPER_RELATIONS: Final[frozenset[str]] = _CALL_PATH_RELATIONS | _FRAGMENT_RELATIONS

#: Ways of reading a member set out of a module-level symbol.
_EXTRACTORS: Final[frozenset[str]] = frozenset(
    {"dict_keys", "regex_head_names", "str_tuple", "regex_alternation"}
)

#: A `(?:a|b|c)` or `(a|b|c)` group inside a pattern literal.
_ALTERNATION_GROUP_RE: Final[re.Pattern[str]] = re.compile(r"\((?:\?:)?([^()]*\|[^()]*)\)")

#: `^name\b` at the head of a whitelist pattern. Anything else in the pattern
#: is grammar rather than a command name, so only this shape yields a member.
_HEAD_NAME_RE: Final[re.Pattern[str]] = re.compile(r"^\^([A-Za-z0-9_.-]+)\\b")

_REMEDIATION: Final[str] = (
    "Each row above declares two sites that must agree, and they do not.\n"
    "\n"
    "This is not a style finding. The class it defends against is the one\n"
    "where this project's own good reasoning stops propagating: the correct\n"
    "behaviour already exists at the sibling site, often in the same file, and\n"
    "this site re-derives it, derives it shorter, or omits it.\n"
    "\n"
    "Fix the site that is WRONG, not the row. A row is a statement about what\n"
    "the code should be, written by someone who had read both sides; editing\n"
    "it to match the code inverts that. If the relation genuinely no longer\n"
    "holds -- the design changed -- change the row deliberately and say why in\n"
    "its `reason`.\n"
    "\n"
    "If a single member is a reviewed, deliberate exception, name it in the\n"
    "row's `allow` list. That keeps the rest of the relation enforced, which\n"
    "is strictly better than deleting the row."
)


class RegistryRotError(Exception):
    """A declared file or symbol no longer exists.

    Raised rather than returning an empty set: an empty set satisfies
    ``disjoint`` against anything, so a rename would otherwise convert a rotted
    row into a passing one.
    """


@dataclass(frozen=True)
class Side:
    """One half of a declared pair.

    ``only`` restricts the comparison to named members, and it is not a
    convenience. Two verb alternations can each be missing members of the
    other -- one lists `rsync`, the other `tee` -- so an unrestricted set
    relation reports a violation in BOTH directions and neither report is the
    defect. A row therefore declares WHICH MEMBERS participate, not just two
    symbol names.
    """

    file: str
    symbol: str = ""
    extract: str = ""
    only: frozenset[str] = field(default_factory=frozenset)
    #: For a call-path relation, the FUNCTION whose body must reach the helper.
    function: str = ""

    @property
    def label(self) -> str:
        return f"{self.file}::{self.symbol or self.function}"


@dataclass(frozen=True)
class Row:
    """One declared relation between two sites."""

    row_id: str
    relation: str
    reason: str
    left: Side
    right: Side
    allow: frozenset[str] = field(default_factory=frozenset)
    #: For a call-path relation, the helper both sites must call.
    helper: str = ""


@dataclass(frozen=True)
class Violation:
    """One declared relation that does not hold."""

    row_id: str
    relation: str
    reason: str
    left: str
    right: str
    members: tuple[str, ...]
    rule: str = _RULE
    helper: str = ""

    def to_dict(self) -> dict[str, object]:
        named = ", ".join(f"`{m}`" for m in self.members)
        if self.relation == "reaches":
            complaint = f"must both call `{self.helper}`, but {named} does not"
        elif self.relation == "interpolates":
            complaint = f"must both be built from `{self.helper}`, but {named} is not"
        elif self.relation == "disjoint":
            complaint = f"must be disjoint, but both carry {named}"
        else:
            complaint = f"must cover {self.right}, but {named} is missing from it"
        return {
            "rule": self.rule,
            "row": self.row_id,
            "left": self.left,
            "right": self.right,
            "members": list(self.members),
            "message": f"{self.left} {complaint} — {self.reason}",
        }


def _side(raw: object, row_id: str, relation: str) -> Side:
    if not isinstance(raw, dict):
        raise ValueError(f"row `{row_id}`: each side must be a mapping")
    if "file" not in raw:
        raise ValueError(f"row `{row_id}`: side is missing `file`")

    if relation in _CALL_PATH_RELATIONS:
        if "function" not in raw:
            raise ValueError(f"row `{row_id}`: a `{relation}` side needs a `function`")
        return Side(file=str(raw["file"]), function=str(raw["function"]))

    if relation in _FRAGMENT_RELATIONS:
        # A symbol, but no extractor: the row asks what the symbol is BUILT
        # FROM, not what members it holds.
        if "symbol" not in raw:
            raise ValueError(f"row `{row_id}`: an `{relation}` side needs a `symbol`")
        return Side(file=str(raw["file"]), symbol=str(raw["symbol"]))

    for key in ("symbol", "extract"):
        if key not in raw:
            raise ValueError(f"row `{row_id}`: side is missing `{key}`")
    extract = str(raw["extract"])
    if extract not in _EXTRACTORS:
        raise ValueError(
            f"row `{row_id}`: unknown extractor `{extract}` "
            f"(known: {', '.join(sorted(_EXTRACTORS))})"
        )
    only = raw.get("only") or []
    if not isinstance(only, list):
        raise ValueError(f"row `{row_id}`: `only` must be a list")
    return Side(
        file=str(raw["file"]),
        symbol=str(raw["symbol"]),
        extract=extract,
        only=frozenset(str(o) for o in only),
    )


def load_registry(path: Path) -> list[Row]:
    """Every declared row, validated.

    Validation is strict on purpose. A misspelled relation or extractor that
    was merely skipped would leave a row in the file that looks enforced and
    is not, which is worse than having no row at all.
    """
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path}: registry must be a list of rows")

    rows: list[Row] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: each row must be a mapping")
        row_id = str(entry.get("id", "")).strip()
        if not row_id:
            raise ValueError(f"{path}: every row needs an `id`")
        relation = str(entry.get("relation", ""))
        if relation not in _RELATIONS:
            raise ValueError(
                f"row `{row_id}`: unknown relation `{relation}` "
                f"(known: {', '.join(sorted(_RELATIONS))})"
            )
        allow = entry.get("allow") or []
        if not isinstance(allow, list):
            raise ValueError(f"row `{row_id}`: `allow` must be a list")
        helper = str(entry.get("helper", "")).strip()
        if relation in _HELPER_RELATIONS and not helper:
            raise ValueError(f"row `{row_id}`: a `{relation}` row needs a `helper`")
        rows.append(
            Row(
                row_id=row_id,
                relation=relation,
                reason=str(entry.get("reason", "")).strip(),
                left=_side(entry.get("left"), row_id, relation),
                right=_side(entry.get("right"), row_id, relation),
                allow=frozenset(str(a) for a in allow),
                helper=helper,
            )
        )
    return rows


def _assigned_value(tree: ast.Module, symbol: str) -> ast.expr | None:
    """The module-level value bound to ``symbol``, plain or annotated."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == symbol for t in node.targets):
                return node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == symbol:
                return node.value
    return None


def _dict_keys(value: ast.expr, side: Side) -> frozenset[str]:
    if not isinstance(value, ast.Dict):
        raise RegistryRotError(f"{side.label} is not a dict literal")
    return frozenset(
        k.value for k in value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)
    )


def _regex_head_names(value: ast.expr, side: Side) -> frozenset[str]:
    """The `^name\\b` head of each LITERAL pattern in a tuple/list.

    A non-literal entry is skipped. The real whitelist mixes plain literals
    with `rf"^{GIT_INVOCATION}log\\b"`, whose head is a shared grammar rather
    than a command name; inventing a member from it would be the false positive
    that gets this rule switched off, while skipping it merely under-reports.
    """
    if not isinstance(value, ast.Tuple | ast.List):
        raise RegistryRotError(f"{side.label} is not a tuple or list literal")
    names: set[str] = set()
    for element in value.elts:
        if not (isinstance(element, ast.Constant) and isinstance(element.value, str)):
            continue
        match = _HEAD_NAME_RE.match(element.value)
        if match is not None:
            names.add(match.group(1))
    return frozenset(names)


def _str_tuple(value: ast.expr, side: Side) -> frozenset[str]:
    """String members of a module-level tuple or list literal."""
    if not isinstance(value, ast.Tuple | ast.List):
        raise RegistryRotError(f"{side.label} is not a tuple or list literal")
    return frozenset(
        e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
    )


def _regex_alternation(value: ast.expr, side: Side) -> frozenset[str]:
    """Members of every ``(a|b|c)`` group inside a pattern literal.

    Reads through a ``re.compile(...)`` call to its first argument, because
    that is how this repository spells a module-level pattern constant.

    Only grouped alternations count. A top-level alternative such as ``>`` or
    ``of=`` in the same pattern is an operator rather than a named member, and
    folding it in would put punctuation into a set that is compared against
    command names.
    """
    if isinstance(value, ast.Call) and value.args:
        value = value.args[0]
    if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
        raise RegistryRotError(f"{side.label} is not a pattern literal")
    members: set[str] = set()
    for group in _ALTERNATION_GROUP_RE.findall(value.value):
        members.update(part for part in group.split("|") if part)
    return frozenset(members)


def extract_members(repo_root: Path, side: Side) -> frozenset[str]:
    """The member set ``side`` declares.

    Raises :class:`RegistryRotError` when the file or symbol has gone, rather
    than returning an empty set that would satisfy every relation.
    """
    path = repo_root / side.file
    if not path.is_file():
        raise RegistryRotError(f"{side.file} does not exist")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    value = _assigned_value(tree, side.symbol)
    if value is None:
        raise RegistryRotError(f"{side.symbol} is not assigned at module level in {side.file}")

    extractors = {
        "dict_keys": _dict_keys,
        "regex_head_names": _regex_head_names,
        "str_tuple": _str_tuple,
        "regex_alternation": _regex_alternation,
    }
    members = extractors[side.extract](value, side)
    if not members:
        raise RegistryRotError(f"{side.label} yielded no members")
    if side.only:
        # Restricting AFTER the emptiness check on purpose: an `only` naming a
        # member that has since been renamed away should surface as a violation
        # to look at, not as a silently empty comparison.
        members &= side.only
    return members


def _function_body(repo_root: Path, side: Side) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """The named function's definition, wherever it sits in the module."""
    path = repo_root / side.file
    if not path.is_file():
        raise RegistryRotError(f"{side.file} does not exist")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == side.function:
            return node
    raise RegistryRotError(f"{side.function} is not defined in {side.file}")


def _called_names(body: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Every name this function calls, whether bare or through an attribute."""
    names: set[str] = set()
    for node in ast.walk(body):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def reaches_helper(repo_root: Path, side: Side, helper: str) -> bool:
    """Whether ``side``'s function CALLS ``helper``, directly or one hop away.

    Calling, not naming. A function that accepts ``content_guard`` as a
    parameter and never invokes it has exactly the defect a call-path row
    exists to catch, so a name-mention test would report the bug as fixed.

    An attribute call (``guards.content_guard(x)``) counts: reaching the helper
    through a module is still reaching it, and the row is about whether the
    protection runs.

    **One hop is followed, and no further.** A row names the function that owns
    the responsibility, and extracting the work into a small helper method is
    ordinary refactoring -- a rule that read only the named body would call
    that a violation and push code to stay inline just to satisfy a check.
    Repointing the row at the inner helper instead is worse: the inner helper
    then satisfies the row even when nothing calls it, so dead code turns it
    green. Following arbitrarily far is the opposite failure, where the row
    degrades into "this function eventually reaches something".
    """
    body = _function_body(repo_root, side)
    called = _called_names(body)
    if helper in called:
        return True

    tree = ast.parse((repo_root / side.file).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if node.name in called and node is not body and helper in _called_names(node):
            return True
    return False


def _print_violation(violation: Violation) -> None:
    """One violation, rendered for a terminal.

    Kept out of ``main`` because a relation has TWO renderers -- this one and
    ``Violation.to_dict`` -- and a relation added to only one of them crashes
    the Detector on the first real violation instead of reporting it.
    """
    labels = {
        "disjoint": "shared",
        "superset": "missing from left",
        "reaches": f"does not call {violation.helper}",
        "interpolates": f"not built from {violation.helper}",
    }
    print(f"  [{violation.row_id}] {violation.left}  vs  {violation.right}")
    print(f"      {labels[violation.relation]}: {', '.join(violation.members)}")


def interpolates_fragment(repo_root: Path, side: Side, helper: str) -> bool:
    """Whether ``side``'s symbol is BUILT FROM ``helper``.

    Referencing, not spelling. A pattern whose literal text happens to contain
    the fragment's NAME is exactly as strict as it was before, so only an
    ``ast.Name`` lookup counts -- the same distinction ``reaches_helper`` draws
    between calling a helper and naming it.

    Concatenation (``SUDO_INVOCATION + OPTIONAL_PATH + r"pip\\b"``) and
    f-string interpolation (``rf"^{OPTIONAL_PATH}gh\\b"``) both count: this
    repository spells the same sharing both ways, and a row is about whether
    the fragment is in the pattern, not about which syntax put it there.
    """
    path = repo_root / side.file
    if not path.is_file():
        raise RegistryRotError(f"{side.file} does not exist")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    value = _assigned_value(tree, side.symbol)
    if value is None:
        raise RegistryRotError(f"{side.symbol} is not assigned at module level in {side.file}")
    return any(isinstance(node, ast.Name) and node.id == helper for node in ast.walk(value))


def check_row(repo_root: Path, row: Row) -> list[Violation]:
    """Every way ``row``'s declared relation fails to hold.

    ``members`` on the returned violation is always "the members that make the
    relation false", so the deny message reads the same whichever relation the
    row declared.
    """
    if row.relation in _HELPER_RELATIONS:
        # BOTH sides are checked. A row is a claim about the pair, so a
        # reference site that stops sharing the helper has broken the relation
        # just as surely as the site the row was written about.
        shares = reaches_helper if row.relation in _CALL_PATH_RELATIONS else interpolates_fragment
        missing = frozenset(
            side.symbol or side.function
            for side in (row.left, row.right)
            if not shares(repo_root, side, row.helper)
        )
        offending = missing - row.allow
        if not offending:
            return []
        return [
            Violation(
                row_id=row.row_id,
                relation=row.relation,
                reason=row.reason,
                left=row.left.label,
                right=row.right.label,
                members=tuple(sorted(offending)),
                helper=row.helper,
            )
        ]

    left = extract_members(repo_root, row.left)
    right = extract_members(repo_root, row.right)

    if row.relation == "disjoint":
        offending = (left & right) - row.allow
    else:
        offending = (right - left) - row.allow

    if not offending:
        return []
    return [
        Violation(
            row_id=row.row_id,
            relation=row.relation,
            reason=row.reason,
            left=row.left.label,
            right=row.right.label,
            members=tuple(sorted(offending)),
        )
    ]


def scan(repo_root: Path, registry_path: Path) -> list[Violation]:
    """Every violation across the whole registry."""
    violations: list[Violation] = []
    for row in load_registry(registry_path):
        violations.extend(check_row(repo_root, row))
    return violations


def main() -> int:
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    json_mode = "--json" in args
    registry_path = _DEFAULT_REGISTRY
    for index, arg in enumerate(args):
        if arg == "--registry" and index + 1 < len(args):
            registry_path = Path(args[index + 1]).resolve()

    violations = scan(_REPO_ROOT, registry_path)

    output = {
        "tool": "declared_invariant_pairs",
        "summary": {
            "passed": len(violations) == 0,
            "total_violations": len(violations),
        },
        "violations": [v.to_dict() for v in violations],
    }

    if json_mode:
        _QA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _OUTPUT_FILE.write_text(json.dumps(output, indent=2))

    if violations:
        print(f"Found {len(violations)} declared invariant pair(s) that do not hold:")
        for violation in violations:
            _print_violation(violation)
        print(f"\n{_REMEDIATION}")
    else:
        print("Every declared invariant pair holds")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
