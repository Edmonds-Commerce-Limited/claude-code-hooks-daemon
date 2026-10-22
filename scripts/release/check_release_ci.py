#!/usr/bin/env python3
"""Refuse to tag a release commit that its pull request's CI did not pass.

``untracked/release-state.json`` carries a ``ci`` record of the release pull
request's CI run::

    "ci": {"pr_number": 12, "run_id": 987654,
           "head_sha": "<40-hex sha the run tested>", "conclusion": "success"}

Resuming ``/release`` runs this checker before tagging. It exits 0 only when the
record exists and is well formed, concluded ``success``, tested exactly the
commit currently at HEAD, and GitHub still reports the same conclusion and
head commit for the run. Anything else exits 1 with ONE line naming the reason
(``release-ci: <reason>: <detail>``). There is no fallback: a missing record, an
unknown field or an unreachable GitHub is a failure, never a pass.

Usage:
    check_release_ci.py [--state-file untracked/release-state.json]

Needs ``gh`` (authenticated) for the live lookup.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

DEFAULT_STATE_FILE: Final[str] = "untracked/release-state.json"
CI_KEY: Final[str] = "ci"
GREEN: Final[str] = "success"
SHA_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{40}")
INT_FIELDS: Final[tuple[str, ...]] = ("pr_number", "run_id")
STR_FIELDS: Final[tuple[str, ...]] = ("head_sha", "conclusion")
CI_FIELDS: Final[frozenset[str]] = frozenset(INT_FIELDS + STR_FIELDS)

FetchRun = Callable[[int], Mapping[str, Any]]
HeadResolver = Callable[[], str]


class ReleaseCiError(Exception):
    """The release CI record does not authorise tagging; message is ``reason: detail``."""


@dataclass(frozen=True)
class CiRecord:
    """The release pull request's CI result as recorded in the state file."""

    pr_number: int
    run_id: int
    head_sha: str
    conclusion: str


def load_state(path: Path) -> dict[str, Any]:
    """Read the release state file; it must exist and hold a JSON object."""
    if not path.is_file():
        raise ReleaseCiError(f"no-state-file: {path} does not exist")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseCiError(f"unreadable-state-file: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ReleaseCiError(f"unreadable-state-file: {path} is not a JSON object")
    return data


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def parse_ci_record(state: Mapping[str, Any]) -> CiRecord:
    """Strictly validate the ``ci`` record: every field present, typed, none unknown."""
    if CI_KEY not in state:
        raise ReleaseCiError(f"no-ci-record: state file has no '{CI_KEY}' record")
    raw = state[CI_KEY]
    if not isinstance(raw, dict):
        raise ReleaseCiError(f"malformed-ci-record: '{CI_KEY}' is not an object")
    missing = sorted(CI_FIELDS - raw.keys())
    if missing:
        raise ReleaseCiError(f"malformed-ci-record: missing {', '.join(missing)}")
    unknown = sorted(str(key) for key in raw.keys() - CI_FIELDS)
    if unknown:
        raise ReleaseCiError(f"malformed-ci-record: unknown field {', '.join(unknown)}")
    for name in INT_FIELDS:
        if not _positive_int(raw[name]):
            raise ReleaseCiError(f"malformed-ci-record: {name} must be a positive integer")
    sha = raw["head_sha"]
    if not isinstance(sha, str) or not SHA_PATTERN.fullmatch(sha):
        raise ReleaseCiError("malformed-ci-record: head_sha must be 40 lowercase hex digits")
    conclusion = raw["conclusion"]
    if not isinstance(conclusion, str) or not conclusion:
        raise ReleaseCiError("malformed-ci-record: conclusion must be a non-empty string")
    return CiRecord(
        pr_number=raw["pr_number"],
        run_id=raw["run_id"],
        head_sha=sha,
        conclusion=conclusion,
    )


def fetch_live_run(run_id: int) -> dict[str, Any]:
    """Ask GitHub for the run's conclusion and head sha (the network seam)."""
    cmd = ["gh", "run", "view", str(run_id), "--json", "conclusion,headSha"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise ReleaseCiError(f"live-run-unavailable: cannot run gh: {exc}") from exc
    if result.returncode != 0:
        raise ReleaseCiError(
            f"live-run-unavailable: gh exited {result.returncode}: {result.stderr.strip()}"
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseCiError(f"live-run-unavailable: gh printed non-JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseCiError("live-run-unavailable: gh did not print a JSON object")
    return payload


def resolve_head() -> str:
    """The commit about to be tagged: the full sha at HEAD."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise ReleaseCiError(f"head-unresolvable: git exited {result.returncode}")
    return result.stdout.strip()


def verify(state: Mapping[str, Any], *, head_sha: str, fetch_run: FetchRun) -> CiRecord:
    """Raise ReleaseCiError unless CI passed on exactly ``head_sha``, recorded and live."""
    record = parse_ci_record(state)
    if record.conclusion != GREEN:
        raise ReleaseCiError(
            f"ci-not-green: run {record.run_id} concluded '{record.conclusion}', not '{GREEN}'"
        )
    if record.head_sha != head_sha:
        raise ReleaseCiError(f"head-not-tested: CI passed {record.head_sha} but HEAD is {head_sha}")
    live = fetch_run(record.run_id)
    for live_key, expected in (("conclusion", record.conclusion), ("headSha", record.head_sha)):
        actual = live.get(live_key)
        if actual != expected:
            raise ReleaseCiError(
                f"live-run-mismatch: run {record.run_id} {live_key} is {actual!r}, "
                f"state file records {expected!r}"
            )
    return record


def main(
    argv: Sequence[str] | None = None,
    *,
    head_resolver: HeadResolver = resolve_head,
    fetch_run: FetchRun = fetch_live_run,
) -> int:
    """Exit 0 when CI authorises tagging HEAD; otherwise print one reason line, exit 1."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--state-file", default=DEFAULT_STATE_FILE, type=Path)
    args = parser.parse_args(argv)
    try:
        state = load_state(args.state_file)
        record = verify(state, head_sha=head_resolver(), fetch_run=fetch_run)
    except ReleaseCiError as exc:
        print(f"release-ci: {exc}", file=sys.stderr)
        return 1
    print(f"release-ci: ok: run {record.run_id} on PR #{record.pr_number} passed {record.head_sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
