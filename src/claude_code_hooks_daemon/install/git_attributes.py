"""Managed ``.gitattributes`` block for daemon-owned files (Plan 00552).

A merge, rebase or stash pop that conflicts on a deployed hook stub or on
``.claude/init.sh`` makes git write ``<<<<<<<`` markers into a bash script.
The script then fails to parse and exits 2, which Claude Code reads as a
block. The ``-merge`` attribute makes git keep the current side intact and
write no markers, while still reporting the conflict.

``.claude/settings.json`` is deliberately not covered: it is a merged file
holding project-owned entries beside the daemon's, so ``-merge`` would
silently drop one side of a genuine edit. ``reconcile-settings`` re-adds
missing daemon registrations instead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

GITATTRIBUTES_NAME = ".gitattributes"
BEGIN_MARKER = "# BEGIN claude-code-hooks-daemon managed block (rewritten on install and upgrade)"
END_MARKER = "# END claude-code-hooks-daemon managed block"
MANAGED_PATTERNS: tuple[str, ...] = (".claude/hooks/**", ".claude/init.sh")


def _managed_lines() -> list[str]:
    return [BEGIN_MARKER, *(f"{pattern} -merge" for pattern in MANAGED_PATTERNS), END_MARKER]


def _splice(existing: list[str]) -> list[str]:
    """Return ``existing`` with the managed block inserted or replaced."""
    begins = [i for i, line in enumerate(existing) if line == BEGIN_MARKER]
    ends = [i for i, line in enumerate(existing) if line == END_MARKER]
    if not begins and not ends:
        return [*existing, *_managed_lines()]
    if not begins:
        raise ValueError(f"{GITATTRIBUTES_NAME} has an end marker but no begin marker")
    if not ends or ends[-1] < begins[0]:
        raise ValueError(f"{GITATTRIBUTES_NAME} has a begin marker but no end marker")
    return [*existing[: begins[0]], *_managed_lines(), *existing[ends[-1] + 1 :]]


def ensure_managed_block(project_root: Path) -> bool:
    """Write or update the managed block in the project's ``.gitattributes``.

    Args:
        project_root: Root of the client project (must exist).

    Returns:
        True when the file was changed, False when it already held the block.

    Raises:
        FileNotFoundError: If ``project_root`` does not exist.
        ValueError: If the file holds only one of the two markers.
    """
    if not project_root.is_dir():
        raise FileNotFoundError(f"Project root not found: {project_root}")
    path = project_root / GITATTRIBUTES_NAME
    current = path.read_text() if path.exists() else ""
    lines = _splice(current.splitlines())
    updated = "\n".join(lines) + "\n"
    if updated == current:
        return False
    path.write_text(updated)
    return True


def main(argv: list[str] | None = None) -> int:
    """CLI entry point used by the shell installer and upgrader."""
    parser = argparse.ArgumentParser(description="Write the managed .gitattributes block")
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        changed = ensure_managed_block(args.project_root)
    except (FileNotFoundError, ValueError) as exc:
        print(f"gitattributes block not written: {exc}", file=sys.stderr)
        return 1
    print("gitattributes block updated" if changed else "gitattributes block already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
