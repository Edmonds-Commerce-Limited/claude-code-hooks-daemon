"""Plan 00164 Phase 1 — truthful upgrade transition messaging.

Root cause of the "already upgraded" confusion (Plan 00164 finding): Layer 1
(``scripts/upgrade.sh``) checks out the target tag BEFORE Layer 2
(``scripts/upgrade_version.sh``) evaluates its idempotency check, so Layer 2's
``git describe --tags --exact-match`` always equals the target and it
unconditionally prints ``Already at version X`` — even when the actually-built
venv (the ``.daemon-version`` stamp) is an OLDER version being refreshed.

The fix routes all upgrade messaging through the source-safe helper
``scripts/install/upgrade_transition.sh`` which describes the TRUE transition
between the INSTALLED (venv-stamp) version and the TARGET version:

  - installed empty            -> "Installing <target>"
  - installed == target        -> "Already at <target>" (true no-op refresh)
  - installed != target        -> "Refreshing <installed> -> <target>"

These tests exercise the helper directly by sourcing it in a bash harness (bats
is not installed and QA runs pytest), mirroring
``tests/integration/test_install_venv_resolver.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TRANSITION_LIB = REPO_ROOT / "scripts" / "install" / "upgrade_transition.sh"
UPGRADE_VERSION_SH = REPO_ROOT / "scripts" / "upgrade_version.sh"

_HARNESS = "set -euo pipefail\nsource \"$1\"\n$2 \"$3\" \"$4\"\n"


def _run(func: str, installed: str, target: str) -> str:
    """Source the lib and invoke ``func installed target``; return stdout."""
    result = subprocess.run(
        ["bash", "-c", _HARNESS, "_", str(TRANSITION_LIB), func, installed, target],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# The lib must exist and be source-safe (defining functions only).
# ---------------------------------------------------------------------------


def test_transition_lib_exists() -> None:
    assert TRANSITION_LIB.is_file(), (
        f"Expected source-safe helper at {TRANSITION_LIB}. Plan 00164 Phase 1 "
        "extracts upgrade transition messaging into this lib so it is testable "
        "and reused by upgrade_version.sh."
    )


# ---------------------------------------------------------------------------
# Headline: what prints at the START of the (idempotent) deploy block.
# ---------------------------------------------------------------------------


def test_headline_true_noop_says_already_at() -> None:
    out = _run("upgrade_transition_headline", "v3.40.0", "v3.40.0")
    assert "Already at" in out
    assert "v3.40.0" in out


def test_headline_real_refresh_names_both_versions_not_already_at() -> None:
    """The bug scenario: venv stamped v3.38.0, target v3.40.0. Must NOT say
    the misleading 'Already at version' — it must name the real transition."""
    out = _run("upgrade_transition_headline", "v3.38.0", "v3.40.0")
    assert "v3.38.0" in out
    assert "v3.40.0" in out
    assert "Already at" not in out
    assert "→" in out or "->" in out


def test_headline_fresh_install_says_installing() -> None:
    out = _run("upgrade_transition_headline", "", "v3.40.0")
    assert "Installing" in out
    assert "v3.40.0" in out
    assert "Already at" not in out


# ---------------------------------------------------------------------------
# Summary: what prints at the END on success.
# ---------------------------------------------------------------------------


def test_summary_true_noop_reverified() -> None:
    out = _run("upgrade_transition_summary", "v3.40.0", "v3.40.0")
    assert "v3.40.0" in out
    assert "Upgraded" not in out


def test_summary_real_refresh_says_upgraded_both() -> None:
    out = _run("upgrade_transition_summary", "v3.38.0", "v3.40.0")
    assert "Upgraded" in out
    assert "v3.38.0" in out
    assert "v3.40.0" in out


# ---------------------------------------------------------------------------
# Version normalisation: a missing leading 'v' must not change the meaning.
# ---------------------------------------------------------------------------


def test_versions_normalised_leading_v() -> None:
    """'3.40.0' and 'v3.40.0' are the SAME version -> true no-op, not a jump."""
    out = _run("upgrade_transition_headline", "3.40.0", "v3.40.0")
    assert "Already at" in out
    assert "→" not in out and "->" not in out


# ---------------------------------------------------------------------------
# Layer 2 must ROUTE through the helper, not print the bare misleading message.
# ---------------------------------------------------------------------------


def test_upgrade_version_sh_no_bare_already_at_version() -> None:
    """upgrade_version.sh must not unconditionally print the misleading
    'Already at version $TARGET_VERSION' — it must use the transition helper."""
    content = UPGRADE_VERSION_SH.read_text()
    assert "Already at version $TARGET_VERSION" not in content, (
        "upgrade_version.sh still prints the unconditional, misleading "
        "'Already at version $TARGET_VERSION'. Route messaging through "
        "upgrade_transition_headline/summary (Plan 00164 Phase 1)."
    )


def test_upgrade_version_sh_sources_transition_lib() -> None:
    content = UPGRADE_VERSION_SH.read_text()
    assert "upgrade_transition.sh" in content, (
        "upgrade_version.sh must source scripts/install/upgrade_transition.sh "
        "so the truthful transition messaging is used (Plan 00164 Phase 1)."
    )
