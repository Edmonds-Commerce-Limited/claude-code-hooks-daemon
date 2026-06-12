"""Plan 00123 BUG 1 (CRITICAL) — init.sh has no unguarded ``realpath`` call.

``init.sh`` runs under ``set -euo pipefail`` and is sourced/executed on EVERY
hook event. It contained ``_abs_project_path=$(realpath "$PROJECT_PATH")`` —
a command substitution whose failure aborts the whole script under ``set -e``.
``realpath`` is absent on macOS before 12.3 and on base BSD, so on those hosts
every hook forwarder died. The variable was also dead (never referenced), so
the fix is deletion.

This regression guard asserts ``init.sh`` contains no UNGUARDED ``realpath``
invocation: any future ``realpath`` use must carry a ``||`` fallback on the
same logical line so a missing binary cannot abort the script.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SH = REPO_ROOT / "init.sh"

_REALPATH_CALL = re.compile(r"\brealpath\b")


def test_init_sh_has_no_dead_abs_project_path() -> None:
    """The dead ``_abs_project_path`` realpath assignment must be gone."""
    source = INIT_SH.read_text()
    assert "_abs_project_path" not in source, (
        "BUG 1: the dead `_abs_project_path=$(realpath ...)` assignment must be "
        "removed — it aborts every hook under set -e on macOS (no realpath)."
    )


def test_init_sh_realpath_is_guarded_if_present() -> None:
    """Any ``realpath`` use must have a ``||`` fallback (never abort set -e)."""
    offenders: list[str] = []
    for lineno, line in enumerate(INIT_SH.read_text().splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # comments/docs may mention realpath
        if _REALPATH_CALL.search(line) and "||" not in line:
            offenders.append(f"{lineno}: {stripped}")
    assert not offenders, (
        "BUG 1: unguarded `realpath` call(s) in init.sh — these abort every "
        "hook under set -e on macOS/BSD where realpath is absent. Add a "
        "`|| <fallback>` or remove:\n" + "\n".join(offenders)
    )
