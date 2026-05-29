r"""Plan 00114 Phase 1 (F1) — Layer 1 legacy bootstrap-flag tolerance.

Field report ``untracked/hooks-daemon-upgrade-broken.md`` (2026-05-29): a client
on a pre-v3.15 ``upgrade.sh`` skill shim self-bootstraps by re-exec'ing the
release artifact (the Layer 1 ``scripts/upgrade.sh``) with a trailing
``--already-bootstrapped`` flag. Layer 1's arg parser rejected ALL unknown
``-*`` flags, so it aborted with ``ERR Unknown option: --already-bootstrapped``
— a bootstrap deadlock (the fix is delivered BY the upgrade the broken shim
blocks).

This regression test pins the fix: Layer 1 must ACCEPT-AND-IGNORE an allowlist
of historical bootstrap flags (``--already-bootstrapped``) — in any position —
while still REJECTING genuinely-unknown flags (typo protection).

We do not run the full upgrade; we only need to prove arg-parse no longer
aborts on the legacy flag. We point ``--project-root`` at a non-existent dir so
the script proceeds PAST arg-parse and fails LATER (at project-root validation),
never with the "Unknown option" message. A genuinely-bogus flag must still
trip the "Unknown option" guard.

Static + behavioural test — invokes ``scripts/upgrade.sh`` as a subprocess.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade.sh"
BASH = shutil.which("bash") or "/bin/bash"

_UNKNOWN_OPTION_MARKER = "Unknown option"
_TIMEOUT_SECONDS = 30


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, str(UPGRADE_SH), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )


def test_already_bootstrapped_flag_trailing_is_accepted() -> None:
    """``--already-bootstrapped`` after the project-root must not abort arg-parse.

    This is the exact shape an old skill shim produces:
    ``upgrade.sh --project-root PATH --already-bootstrapped``.
    """
    bogus_root = REPO_ROOT / "does-not-exist-aaaaa"
    result = _run("--project-root", str(bogus_root), "--already-bootstrapped")

    combined = result.stdout + result.stderr
    assert _UNKNOWN_OPTION_MARKER not in combined, (
        "Layer 1 upgrade.sh still rejects --already-bootstrapped as an unknown "
        "option — the bootstrap deadlock (F1) is NOT fixed.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_already_bootstrapped_flag_leading_is_accepted() -> None:
    """The legacy flag must be tolerated in ANY position (leading too)."""
    bogus_root = REPO_ROOT / "does-not-exist-bbbbb"
    result = _run("--already-bootstrapped", "--project-root", str(bogus_root))

    combined = result.stdout + result.stderr
    assert _UNKNOWN_OPTION_MARKER not in combined, (
        "Layer 1 upgrade.sh rejects a leading --already-bootstrapped flag.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_already_bootstrapped_with_version_positional() -> None:
    """Legacy flag interleaved with the VERSION positional must still parse.

    Shape: ``upgrade.sh --project-root PATH --already-bootstrapped v9.9.9``.
    The version positional must survive — proven by reaching project-root
    validation rather than "Unknown option".
    """
    bogus_root = REPO_ROOT / "does-not-exist-ccccc"
    result = _run("--project-root", str(bogus_root), "--already-bootstrapped", "v9.9.9")

    combined = result.stdout + result.stderr
    assert _UNKNOWN_OPTION_MARKER not in combined, (
        "Legacy flag + version positional combination broke arg-parse.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_genuinely_unknown_flag_still_rejected() -> None:
    """Typo protection: a non-allowlisted unknown flag must STILL abort.

    Loosening the parser to swallow ALL unknown flags would hide real typos
    (Risk row in the plan). Only the historical bootstrap allowlist is exempt.
    """
    bogus_root = REPO_ROOT / "does-not-exist-ddddd"
    result = _run("--project-root", str(bogus_root), "--totally-bogus-flag")

    combined = result.stdout + result.stderr
    assert result.returncode != 0, "A genuinely-unknown flag must cause a non-zero exit."
    assert _UNKNOWN_OPTION_MARKER in combined, (
        "A genuinely-unknown flag (--totally-bogus-flag) must still be rejected "
        "with 'Unknown option' — the allowlist must not swallow real typos.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
