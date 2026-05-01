"""Plan 00104 Task 5.2 — upgrade_version.sh bootstrap fallback (Issue #2).

Field issue (2026-05-01): a project on a v2.x stamp (no
``.daemon-metadata.json``, no fingerprint-keyed venv on disk) cannot be
upgraded to v3.x because ``upgrade_version.sh`` calls
``resolve_existing_venv_python`` very early (before Step 7 ``ensure_venv``).

Under ``set -euo pipefail`` (line 24), a non-zero exit from
``resolve_existing_venv_python`` (rc 5 = "no usable venv found") inside the
``VENV_PYTHON="$(...)"`` command substitution at line 86 aborts the upgrade
BEFORE the bootstrap path that would have created the new venv runs.

The fix: tolerate the early no-venv case. Either (a) the assignment must NOT
abort under set -e, or (b) the script must explicitly fall through to a
bootstrap branch that calls ``ensure_venv`` to create the venv before any
codepath that needs ``$VENV_PYTHON`` runs.

This test is a static check against ``scripts/upgrade_version.sh``. It pins
the contract so a future refactor cannot regress to the early-abort shape.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade_version.sh"


def _read_upgrade_sh() -> str:
    return UPGRADE_SH.read_text()


def test_upgrade_version_does_not_early_abort_on_missing_venv() -> None:
    """The early ``VENV_PYTHON=$(resolve_existing_venv_python ...)`` call
    must NOT cause script abort under ``set -e`` when no venv exists yet.

    Acceptable shapes:
      - The assignment uses ``|| true`` / ``|| VENV_PYTHON=""`` so a rc 5
        from the resolver does not propagate to set -e.
      - The assignment is wrapped in an ``if`` / explicit conditional that
        captures the failure and continues with VENV_PYTHON unset.
      - The resolver is called with the ``--fallback-target`` flag (which
        never fails on a fresh clone — it returns the creation target).
    """
    content = _read_upgrade_sh()

    # The historical (bad) shape: bare command substitution that aborts under set -e.
    bad_shape = re.search(
        r'^\s*VENV_PYTHON="?\$\(\s*resolve_existing_venv_python[^)]*\)"?\s*$',
        content,
        re.MULTILINE,
    )
    if bad_shape is not None:
        # If the bare shape is present, look for an immediately-following
        # tolerance pattern (`|| true`, `|| VENV_PYTHON=`, `|| :`).
        line = bad_shape.group(0)
        tolerated = bool(
            re.search(
                r"\|\|\s*(true|:|VENV_PYTHON=)",
                line,
            ),
        )
        assert tolerated, (
            "scripts/upgrade_version.sh has a bare "
            '`VENV_PYTHON="$(resolve_existing_venv_python ...)"` assignment '
            "that aborts under set -e when no venv exists. Add `|| true` (or "
            "an explicit `if !` capture) so the script can fall through to "
            "the bootstrap branch in Step 7. See Plan 00104 Task 5.2."
        )


def test_upgrade_version_has_bootstrap_fallback_path() -> None:
    """If no venv was found early, the script must call ``ensure_venv`` to
    create one BEFORE any codepath uses ``$VENV_PYTHON``.

    Looks for either:
      - An explicit guard ``if [ -z "$VENV_PYTHON" ]`` followed by an
        ``ensure_venv`` call (early bootstrap branch).
      - A comment / verbose marker explaining the bootstrap fallback so the
        reader knows the intent.

    This is a structure check — it does not pin the exact branch shape.
    """
    content = _read_upgrade_sh()

    has_empty_check = bool(
        re.search(
            r'\[\s*-z\s*"?\$\{?VENV_PYTHON\}?"?\s*\]',
            content,
        ),
    )
    has_bootstrap_marker = bool(
        re.search(
            r"bootstrap[^\n]*ensure_venv|ensure_venv[^\n]*bootstrap",
            content,
            re.IGNORECASE,
        ),
    )

    assert has_empty_check or has_bootstrap_marker, (
        "scripts/upgrade_version.sh must explicitly handle the case where "
        "`resolve_existing_venv_python` returned no venv path on a fresh "
        'clone / v2.x-stamp upgrade. Add an `if [ -z "$VENV_PYTHON" ]` '
        "guard that calls `ensure_venv` (with bootstrap-resolved Python) "
        "before any codepath consumes $VENV_PYTHON. "
        "See Plan 00104 Task 5.2 / field Issue #2."
    )
