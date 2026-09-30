#!/usr/bin/env python3
"""Print the head sha of the newest main run of qa.yml that reached a verdict.

GitHub keeps one PENDING run per concurrency group, so a run superseded while
pending is cancelled and never tests its commit. A push therefore diffs from
the last commit that WAS tested, not from the sha before its own push: only a
run that concluded ``success`` or ``failure`` counts (not cancelled, skipped,
timed out or still running).

Usage:
    last_verdict_sha.py --repo OWNER/REPO

Needs ``gh`` and a token with ``actions: read`` (``GH_TOKEN`` in the workflow).
Prints the sha, or an empty line when there is none or the API cannot be read;
the reason goes to stderr. Always exits 0: an empty answer makes the classifier
choose the full tier, which is the safe outcome.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from typing import Any, Final

WORKFLOW_FILE: Final[str] = "qa.yml"
BRANCH: Final[str] = "main"
VERDICT_CONCLUSIONS: Final[frozenset[str]] = frozenset({"success", "failure"})


def pick_verdict_sha(runs: Sequence[dict[str, Any]]) -> str:
    """The head sha of the newest main run that reached a verdict, or ''."""
    verdicts = [
        run
        for run in runs
        if run.get("head_branch") == BRANCH and run.get("conclusion") in VERDICT_CONCLUSIONS
    ]
    if not verdicts:
        return ""
    newest = max(verdicts, key=lambda run: str(run.get("run_started_at", "")))
    return str(newest["head_sha"])


def _gh_api(endpoint: str) -> str:
    result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
        ["gh", "api", endpoint], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh exited {result.returncode}: {result.stderr.strip()}")
    return result.stdout


def main(argv: Sequence[str] | None = None) -> int:
    """Print the sha (or an empty line); never fail the workflow."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--repo", required=True, help="OWNER/REPO")
    args = parser.parse_args(argv)
    endpoint = (
        f"repos/{args.repo}/actions/workflows/{WORKFLOW_FILE}/runs"
        f"?branch={BRANCH}&status=completed&per_page=50"
    )
    try:
        payload = json.loads(_gh_api(endpoint))
        runs = payload["workflow_runs"]
    except RuntimeError as exc:
        print(f"workflow runs unavailable ({exc}): full tier", file=sys.stderr)
        print("")
        return 0
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        print(f"workflow runs unreadable ({exc!r}): full tier", file=sys.stderr)
        print("")
        return 0
    print(pick_verdict_sha(runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
