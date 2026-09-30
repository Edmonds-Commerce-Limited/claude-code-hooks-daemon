#!/usr/bin/env python3
"""Build the GitHub release body from RELEASES/vX.Y.Z.md within GitHub's cap.

RELEASES/vX.Y.Z.md folds every holding-area callout in verbatim and can exceed
GitHub's release-body maximum (v3.67.0: 126,003 characters, HTTP 422 at
``gh release create``, after the tag was pushed). This step runs BEFORE the tag
is created:

- notes that fit are written unchanged;
- notes that do not have the verbatim ``## Highlights`` section replaced by a
  link to that section of the notes at the tag, every other section kept;
- a body still over the cap after that is a hard failure (exit 1).

Usage:
    scripts/release/build_github_release_body.py vX.Y.Z [--notes-file PATH] [--output PATH]

The default output is untracked/release-artifacts/github-release-body.md, the
file ``gh release create --notes-file`` is given.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

GITHUB_BODY_LIMIT = 125_000
HIGHLIGHTS_HEADING = "## Highlights"
REPO_URL = "https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "untracked" / "release-artifacts" / "github-release-body.md"


def _section_bounds(lines: list[str]) -> tuple[int, int]:
    """Return the [start, end) line range of the Highlights section."""
    starts = [i for i, line in enumerate(lines) if line.startswith(HIGHLIGHTS_HEADING)]
    if not starts:
        raise ValueError(
            f"notes exceed {GITHUB_BODY_LIMIT} characters and have no "
            f"'{HIGHLIGHTS_HEADING}' section to shorten"
        )
    start = starts[0]
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
        len(lines),
    )
    return start, end


def build_github_body(notes: str, tag: str) -> str:
    """Return the release body for ``notes``, guaranteed under GITHUB_BODY_LIMIT.

    Raises:
        ValueError: If the notes are over the cap and cannot be brought under it.
    """
    if len(notes) < GITHUB_BODY_LIMIT:
        return notes

    lines = notes.splitlines(keepends=True)
    start, end = _section_bounds(lines)
    callouts = sum(1 for line in lines[start:end] if line.startswith("#### "))
    url = f"{REPO_URL}/blob/{tag}/RELEASES/{tag}.md#highlights"
    replacement = (
        f"{HIGHLIGHTS_HEADING}\n\n"
        f"This release carries {callouts} per-change notes, each in its author's own "
        "words and grouped by audience. Together they exceed GitHub's release-body "
        f"limit, so they are published in full in [RELEASES/{tag}.md at the tag]({url}). "
        "Every one of them also appears as an entry under **Changes** below.\n\n"
    )
    body = "".join(lines[:start]) + replacement + "".join(lines[end:])
    if len(body) >= GITHUB_BODY_LIMIT:
        raise ValueError(
            f"release body is still over the {GITHUB_BODY_LIMIT}-character limit "
            f"({len(body)}) after replacing {HIGHLIGHTS_HEADING}; shorten another section"
        )
    return body


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    parser.add_argument("tag", help="release tag, e.g. v3.67.0")
    parser.add_argument("--notes-file", type=Path, help="default: RELEASES/<tag>.md")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    notes_file: Path = args.notes_file or REPO_ROOT / "RELEASES" / f"{args.tag}.md"
    if not notes_file.is_file():
        print(f"ERROR: release notes not found: {notes_file}", file=sys.stderr)
        return 1
    try:
        body = build_github_body(notes_file.read_text(encoding="utf-8"), args.tag)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(body, encoding="utf-8")
    print(f"{args.output} ({len(body)} characters, limit {GITHUB_BODY_LIMIT})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
