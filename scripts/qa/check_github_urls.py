#!/usr/bin/env python3
"""Check that every GitHub URL naming this project names THIS repository.

A URL like `github.com/<someone-else>/claude-code-hooks-daemon` is not a broken
link, and that is why this is a QA gate rather than a docs nit. Three shapes of
real harm, all of which were present in the tree when this was written:

- The `report` skill — the one a CLIENT project runs when the daemon
  misbehaves — told the reporter to open an issue at another organisation. That
  aims a client's diagnostics, which include their config and logs, at a
  repository this project does not control.
- Two shipped `RELEASES/` notes carry `git clone` commands pointing at a
  different third organisation. Anyone following them installs code from a
  source nobody here can vouch for.
- Every such link is also a dead end for a user who just wants to report a bug.

**The tree is walked here rather than delegated to `rg`, deliberately.**
`.claude/` is a HIDDEN directory and `rg` skips hidden directories unless told
otherwise — and the deployed copy of the skill at fault lives exactly there. The
one-line sweep reports a clean tree while the worst instance sits untouched.

Usage:
    python scripts/qa/check_github_urls.py [--json] [--path DIR]

Exit codes:
    0 - No violations found
    1 - Violations found
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Final

_PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_QA_OUTPUT_DIR: Final[Path] = _PROJECT_ROOT / "untracked" / "qa"
_ARTEFACT_NAME: Final[str] = "github_urls.json"
_OUTPUT_FILE: Final[Path] = _QA_OUTPUT_DIR / _ARTEFACT_NAME

#: The one organisation/repository pair that may appear.
CANONICAL_REPO: Final[str] = "Edmonds-Commerce-Limited/claude-code-hooks-daemon"

#: The repository NAME, matched under any owner. Anchoring on the name rather
#: than on a list of known-bad orgs is what makes this a closed check: a fourth
#: wrong org that nobody has thought of yet is caught on the commit that adds it.
_REPO_NAME: Final[str] = "claude-code-hooks-daemon"

#: Both URL forms git accepts. Matching only `https://` would leave the ssh
#: form — `git@github.com:owner/repo.git` — completely unguarded, and that is
#: the form a `git remote set-url` lands in.
_URL_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"(?:https?://(?:www\.)?github\.com/|git@github\.com:)"
    r"(?P<owner>[A-Za-z0-9_.-]+)/" + re.escape(_REPO_NAME) + r"\b"
)

#: Directories never worth scanning, all of them gitignored runtime state
#: rather than project source. Two are here for the same specific reason and it
#: is worth stating: `untracked/` holds scratch captures, and `ccy/` holds
#: session transcripts, subagent logs and tool-result dumps. Both RECORD the
#: text of a bad URL while it is being diagnosed, so a checker that read them
#: would fail on its own evidence and stay failing after the real fix landed.
_SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "ccy",
        "node_modules",
        "untracked",
        "venv",
        ".venv",
        "worktrees",
    }
)

#: Paths whose wrong-org URLs are CORRECT as written. Deliberately tiny, and
#: each entry states what makes it legitimate rather than merely tolerated.
_ALLOWED_PREFIXES: Final[tuple[tuple[str, str], ...]] = (
    (
        "CLAUDE/Plan/Completed/00165-install-permission-bug-fixes/",
        "an archived bug report written by a third party — rewriting their words "
        "would falsify a record of what they actually said",
    ),
    (
        "scripts/qa/check_github_urls.py",
        "this checker, which must name the wrong shapes in order to find them",
    ),
    (
        "tests/unit/qa/test_check_github_urls.py",
        "this checker's tests, which quote bad URLs on purpose",
    ),
)

#: Owners that are obviously placeholders in test fixtures rather than real
#: organisations. Scoped to `tests/` so a placeholder cannot creep into a doc.
_FIXTURE_OWNERS: Final[frozenset[str]] = frozenset({"example", "owner", "org", "test"})

_MAX_BYTES: Final[int] = 2_000_000


def _is_allowed(relative: str, owner: str) -> bool:
    if any(relative.startswith(prefix) for prefix, _ in _ALLOWED_PREFIXES):
        return True
    return relative.startswith("tests/") and owner in _FIXTURE_OWNERS


def _candidate_files(root: Path) -> list[Path]:
    """Every file worth reading, hidden directories INCLUDED."""
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        # Judged BELOW the root only (00466 N21). A linked worktree lives at
        # untracked/worktrees/<name>, and matching the root's own ancestors
        # against the skip list dropped every file in it: a sweep of nothing,
        # reported as clean.
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if not path.is_file() or path.is_symlink():
            continue
        found.append(path)
    return found


def find_violations(root: Path, *, unreadable: list[str] | None = None) -> list[dict[str, Any]]:
    """Every GitHub URL naming this project under an owner that is not ours.

    Args:
        root: Directory to sweep.
        unreadable: Optional sink. Every file that could not be decoded is
            appended to it with the reason. Skipping a binary blob is correct —
            it carries no URL to judge — but skipping it SILENTLY is not: an
            encoding change or a permissions mistake could drop a swathe of the
            tree and report a clean sweep, which is indistinguishable from a
            genuinely clean one.

    Returns:
        One record per offending line, with the repo-relative path, the
        1-indexed line, and a message naming the wrong owner — a finding that
        does not say WHICH owner cannot be triaged from the report alone.
    """
    violations: list[dict[str, Any]] = []
    for path in _candidate_files(root):
        relative = path.relative_to(root).as_posix()
        try:
            if path.stat().st_size > _MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            if unreadable is not None:
                unreadable.append(f"{relative}: {exc}")
            continue

        for number, line in enumerate(text.splitlines(), start=1):
            for match in _URL_PATTERN.finditer(line):
                owner = match.group("owner")
                if f"{owner}/{_REPO_NAME}" == CANONICAL_REPO:
                    continue
                if _is_allowed(relative, owner):
                    continue
                violations.append(
                    {
                        "file": relative,
                        "line": number,
                        "rule": "wrong-github-owner",
                        "message": (
                            f"names owner '{owner}' for {_REPO_NAME}; "
                            f"the canonical repository is {CANONICAL_REPO}"
                        ),
                    }
                )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--path", default=str(_PROJECT_ROOT))
    args = parser.parse_args()

    root = Path(args.path).resolve()
    files_scanned = len(_candidate_files(root))
    unreadable: list[str] = []
    violations = find_violations(root, unreadable=unreadable)

    # An unreadable file was counted but never gated on: `passed` read only
    # `violations`, so a swathe of the tree going unreadable (a permissions
    # mistake, an encoding change) still reported a clean sweep —
    # indistinguishable from a genuinely clean one. Each unreadable file is
    # now its own violation, so the failure both fails the gate and carries
    # matching detail in `violations[]`.
    for entry in unreadable:
        relative, _, reason = entry.partition(": ")
        violations.append(
            {
                "file": relative,
                "line": 0,
                "rule": "unreadable-file",
                "message": f"could not be decoded, so it was never checked: {reason}",
            }
        )
    # Zero candidates is no evidence of a clean tree: it is a sweep that looked
    # at nothing (00466 N21), so it fails like any other finding.
    if files_scanned == 0:
        violations.append(
            {
                "file": str(root),
                "line": 0,
                "rule": "nothing-scanned",
                "message": "no file under this root was a candidate, so nothing was checked",
            }
        )

    if args.json_output:
        # A --path scan answers "is this DIRECTORY clean", which is not the
        # question the repository artefact answers. llm_qa publishes that
        # artefact as this check's evidence surface, so a scoped run reports
        # beside what it scanned rather than overwriting it.
        output_file = root / _ARTEFACT_NAME if root != _PROJECT_ROOT else _OUTPUT_FILE
        output_file.parent.mkdir(parents=True, exist_ok=True)
        # `summary.passed` is what `llm_qa._is_passed` reads; a payload without
        # it is treated as a FAILURE regardless of the exit code, which reads
        # as "0 violations ... FAILED" and sends the reader hunting a finding
        # that does not exist.
        output_file.write_text(
            json.dumps(
                {
                    "summary": {
                        "passed": not violations,
                        "total_violations": len(violations),
                        # The input count: how many files were candidates for
                        # scanning. Distinct from `unreadable_files`, which
                        # counts a FAILURE MODE, not an input — a sweep that
                        # scanned zero files would still report zero unreadable.
                        "files_scanned": files_scanned,
                        # Reported, not hidden: a sweep that could not read a
                        # large part of the tree looks identical to a clean one.
                        "unreadable_files": len(unreadable),
                    },
                    "violations": violations,
                    "unreadable": unreadable,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    else:
        for item in violations:
            print(f"{item['file']}:{item['line']}  {item['message']}")
        print(f"\n{len(violations)} violation(s) ({files_scanned} files scanned)")
        if unreadable:
            print(f"{len(unreadable)} file(s) could not be decoded and were not checked")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
