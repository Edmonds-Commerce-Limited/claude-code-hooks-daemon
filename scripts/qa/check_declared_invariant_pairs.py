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
_RELATIONS: Final[frozenset[str]] = frozenset({"disjoint"})

#: Ways of reading a member set out of a module-level symbol.
_EXTRACTORS: Final[frozenset[str]] = frozenset({"dict_keys", "regex_head_names"})

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
    """One half of a declared pair."""

    file: str
    symbol: str
    extract: str

    @property
    def label(self) -> str:
        return f"{self.file}::{self.symbol}"


@dataclass(frozen=True)
class Row:
    """One declared relation between two sites."""

    row_id: str
    relation: str
    reason: str
    left: Side
    right: Side
    allow: frozenset[str] = field(default_factory=frozenset)


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

    def to_dict(self) -> dict[str, object]:
        named = ", ".join(f"`{m}`" for m in self.members)
        return {
            "rule": self.rule,
            "row": self.row_id,
            "left": self.left,
            "right": self.right,
            "members": list(self.members),
            "message": (
                f"{self.left} and {self.right} must be {self.relation}, but both "
                f"carry {named} — {self.reason}"
            ),
        }


def _side(raw: object, row_id: str) -> Side:
    if not isinstance(raw, dict):
        raise ValueError(f"row `{row_id}`: each side must be a mapping")
    for key in ("file", "symbol", "extract"):
        if key not in raw:
            raise ValueError(f"row `{row_id}`: side is missing `{key}`")
    extract = str(raw["extract"])
    if extract not in _EXTRACTORS:
        raise ValueError(
            f"row `{row_id}`: unknown extractor `{extract}` "
            f"(known: {', '.join(sorted(_EXTRACTORS))})"
        )
    return Side(file=str(raw["file"]), symbol=str(raw["symbol"]), extract=extract)


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
        rows.append(
            Row(
                row_id=row_id,
                relation=relation,
                reason=str(entry.get("reason", "")).strip(),
                left=_side(entry.get("left"), row_id),
                right=_side(entry.get("right"), row_id),
                allow=frozenset(str(a) for a in allow),
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

    if side.extract == "dict_keys":
        members = _dict_keys(value, side)
    else:
        members = _regex_head_names(value, side)
    if not members:
        raise RegistryRotError(f"{side.label} yielded no members")
    return members


def check_row(repo_root: Path, row: Row) -> list[Violation]:
    """Every way ``row``'s declared relation fails to hold."""
    left = extract_members(repo_root, row.left)
    right = extract_members(repo_root, row.right)

    overlap = sorted((left & right) - row.allow)
    if not overlap:
        return []
    return [
        Violation(
            row_id=row.row_id,
            relation=row.relation,
            reason=row.reason,
            left=row.left.label,
            right=row.right.label,
            members=tuple(overlap),
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
            print(f"  [{violation.row_id}] {violation.left}  vs  {violation.right}")
            print(f"      shared: {', '.join(violation.members)}")
        print(f"\n{_REMEDIATION}")
    else:
        print("Every declared invariant pair holds")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
