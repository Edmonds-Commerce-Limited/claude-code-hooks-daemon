#!/usr/bin/env python3
"""The runner legs CI splits the test suite over (Plan 00572 Task 2.1).

``scripts/ci/shard_legs.yaml`` is the one declaration: per PROFILE, a list of
legs, each one Python running some shards of ``scripts/qa/test_shards.yaml``.
``.github/workflows/test-shards.yml`` (called by ``release-gate.yml`` and by
``qa.yml``'s full tier and full-suite fallback) asks this script for a
profile's job matrix and the shards its coverage job combines.

Rules every profile keeps (``--check``; the release-gate ``layout`` job and
``tests/unit/scripts/test_shard_legs.py`` both run it):

- each Python in the profile runs every shard exactly once across its legs;
- coverage is collected by at most one Python, and by all of its legs.

Usage:
    shard_legs.py --profile NAME   print ``matrix=<json>`` and
                                   ``coverage-shards=<names>`` (GITHUB_OUTPUT lines)
    shard_legs.py --check          validate every profile; ``::error::`` lines, exit 1

Needs only PyYAML: the workflow's plan job runs it before any venv exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import yaml

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
LEGS_FILE: Final[Path] = _REPO_ROOT / "scripts" / "ci" / "shard_legs.yaml"
SHARDS_FILE: Final[Path] = _REPO_ROOT / "scripts" / "qa" / "test_shards.yaml"

_KEYS: Final[frozenset[str]] = frozenset({"name", "python", "shards", "coverage", "daemon"})

Leg = dict[str, Any]


class LegsError(ValueError):
    """The legs declaration is unreadable or malformed."""


def _checked_leg(profile: str, entry: object) -> Leg:
    if not isinstance(entry, dict):
        raise LegsError(f"profile {profile}: a leg must be a mapping, got {entry!r}")
    keys = set(entry)
    if keys != _KEYS:
        raise LegsError(
            f"profile {profile}: leg keys must be {sorted(_KEYS)}; "
            f"missing {sorted(_KEYS - keys)}, unknown {sorted(keys - _KEYS)}"
        )
    if not isinstance(entry["name"], str) or not entry["name"]:
        raise LegsError(f"profile {profile}: leg name {entry['name']!r} must be a string")
    if not isinstance(entry["python"], str):
        raise LegsError(
            f"profile {profile}, leg {entry['name']}: python {entry['python']!r} must be "
            "a quoted string (YAML reads 3.10 as 3.1)"
        )
    shards = entry["shards"]
    if not isinstance(shards, list) or not shards or not all(isinstance(s, str) for s in shards):
        raise LegsError(f"profile {profile}, leg {entry['name']}: shards must be a list of names")
    for flag in ("coverage", "daemon"):
        if not isinstance(entry[flag], bool):
            raise LegsError(f"profile {profile}, leg {entry['name']}: {flag} must be true or false")
    return dict(entry)


def load_profiles(path: Path = LEGS_FILE) -> dict[str, list[Leg]]:
    """Every profile in ``path``, its legs in declaration order."""
    try:
        document: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LegsError(f"cannot read {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise LegsError(f"cannot parse {path}: {exc}") from exc
    profiles = document.get("profiles") if isinstance(document, dict) else None
    if not isinstance(profiles, dict) or not profiles:
        raise LegsError(f"{path} must hold a non-empty top-level `profiles:` mapping")
    loaded: dict[str, list[Leg]] = {}
    for name, legs in profiles.items():
        if not isinstance(legs, list):
            raise LegsError(f"profile {name} must be a list of legs")
        loaded[str(name)] = [_checked_leg(str(name), entry) for entry in legs]
    return loaded


def load_shard_names(path: Path = SHARDS_FILE) -> list[str]:
    """The shard names ``scripts/qa/test_shards.yaml`` declares."""
    document: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [str(shard["name"]) for shard in document["shards"]]


def check(profile: str, legs: Sequence[Leg], shard_names: Sequence[str]) -> list[str]:
    """Every rule ``legs`` breaks, as readable problems; empty when sound."""
    if not legs:
        return [f"profile {profile} has no legs"]
    problems: list[str] = []
    leg_names = Counter(str(leg["name"]) for leg in legs)
    for name in sorted(n for n, count in leg_names.items() if count > 1):
        problems.append(f"profile {profile}: leg name {name!r} is used twice")

    wanted = Counter(shard_names)
    by_python: dict[str, Counter[str]] = {}
    for leg in legs:
        by_python.setdefault(str(leg["python"]), Counter()).update(leg["shards"])
    for python, chosen in sorted(by_python.items()):
        if chosen != wanted:
            missing = sorted(set(wanted) - set(chosen))
            unknown = sorted(set(chosen) - set(wanted))
            twice = sorted(s for s, count in chosen.items() if count > 1)
            problems.append(
                f"profile {profile}: Python {python} must run every shard once; "
                f"missing {missing}, unknown {unknown}, run twice {twice}"
            )

    coverage_pythons = {str(leg["python"]) for leg in legs if leg["coverage"]}
    if len(coverage_pythons) > 1:
        problems.append(
            f"profile {profile}: coverage must be one Python's legs, got {sorted(coverage_pythons)}"
        )
    for leg in legs:
        if str(leg["python"]) in coverage_pythons and not leg["coverage"]:
            problems.append(
                f"profile {profile}: leg {leg['name']} skips coverage on the coverage Python"
            )
    return problems


def matrix_for(legs: Sequence[Leg]) -> dict[str, list[dict[str, Any]]]:
    """The ``strategy.matrix`` for ``legs``: shards space-joined for the run step."""
    return {"include": [{**leg, "shards": " ".join(leg["shards"])} for leg in legs]}


def coverage_shards(legs: Sequence[Leg]) -> list[str]:
    """The shards whose coverage data the coverage job combines, in leg order."""
    return [shard for leg in legs if leg["coverage"] for shard in leg["shards"]]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--profile", help="print this profile's matrix and coverage shards")
    mode.add_argument("--check", action="store_true", help="validate every profile")
    args = parser.parse_args(argv)

    try:
        profiles = load_profiles()
        shard_names = load_shard_names()
    except LegsError as exc:
        print(f"::error::{exc}")
        return 1

    if args.check:
        problems = [p for name, legs in profiles.items() for p in check(name, legs, shard_names)]
        for problem in problems:
            print(f"::error::{problem}")
        return 1 if problems else 0

    legs = profiles.get(args.profile)
    if legs is None:
        print(f"::error::unknown profile {args.profile!r}; known: {sorted(profiles)}")
        return 1
    problems = check(args.profile, legs, shard_names)
    if problems:
        for problem in problems:
            print(f"::error::{problem}")
        return 1
    print(f"matrix={json.dumps(matrix_for(legs), separators=(',', ':'))}")
    print(f"coverage-shards={' '.join(coverage_shards(legs))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
