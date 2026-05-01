"""Plan 00104 Task 5.3.A — silent-fallback removal at venv.sh:490 (C-6).

The line ``sync -f "$venv_path" 2>/dev/null || sync`` hides real failures.
The pattern is the same one project memory ``feedback_silent_fallback_antipattern.md``
flagged for the v3.9.0 field-bug: ``2>/dev/null`` plus a default-path
fallback silently masquerades as success.

The replacement must:

  1. NOT redirect stderr to /dev/null. Capture it instead so unexpected
     failures can be surfaced via ``print_verbose``.
  2. Treat *expected* platform/fs limitations (macOS ``sync`` lacks ``-f``;
     overlay-fs returns ``Operation not supported``) as silent fallbacks
     — these are the documented reasons we have a fallback at all.
  3. Treat any *other* failure as a real signal — log it through
     ``print_verbose`` so ``HOOKS_DAEMON_VERBOSE_INSTALL=1`` exposes the
     stderr to the operator.

This is a static-check test — it inspects ``scripts/install/venv.sh``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_SH = REPO_ROOT / "scripts" / "install" / "venv.sh"


def _read_venv_sh() -> str:
    return VENV_SH.read_text()


def _create_venv_at_path_body() -> str:
    content = _read_venv_sh()
    match = re.search(
        r"create_venv_at_path\(\)\s*\{.*?\n\}",
        content,
        re.DOTALL,
    )
    assert match is not None, "create_venv_at_path() function not found in venv.sh"
    return match.group(0)


def test_no_silent_2_dev_null_redirect_on_sync_call() -> None:
    """``sync -f`` must NOT redirect stderr to ``/dev/null``.

    ``2>/dev/null`` plus a fallback hides every reason the call might
    fail (overlay-fs, permissions, ENOSPC, kernel bugs, ...). Capture
    stderr and decide what to do with it instead.
    """
    body = _create_venv_at_path_body()

    pattern = re.compile(r"sync\s+-f\s+[^|&\n]*2>\s*/dev/null")
    assert not pattern.search(body), (
        "venv.sh:create_venv_at_path() still uses the silent-fallback "
        "antipattern `sync -f <path> 2>/dev/null || sync`. Replace it with "
        "stderr-capturing logic that surfaces unexpected failures via "
        "print_verbose. See Plan 00104 Task 5.3 / hostile review C-6 "
        "and the feedback memory `silent fallback hides regressions`."
    )


def test_sync_call_has_visible_diagnostic_path() -> None:
    """The replacement must capture and surface unexpected ``sync -f`` failures.

    Look for either:
      - ``print_verbose`` referencing ``sync`` so stderr-capture-and-log is
        a likely shape, or
      - an explicit ``sync_stderr=`` style capture variable.

    Either signal is enough — the test does not pin the exact replacement
    shape, only that the silent-fallback pattern is gone *and* a visible
    diagnostic path exists.
    """
    body = _create_venv_at_path_body()

    sync_referenced_in_verbose = bool(
        re.search(r"print_verbose[^\n]*sync", body, re.IGNORECASE),
    )
    captures_sync_stderr = bool(
        re.search(r"\b(sync_stderr|_sync_err|sync_output)\s*=", body),
    )

    assert sync_referenced_in_verbose or captures_sync_stderr, (
        "venv.sh:create_venv_at_path() must surface unexpected sync -f "
        "failures via print_verbose (or capture them into a named "
        "variable) so the operator running with "
        "HOOKS_DAEMON_VERBOSE_INSTALL=1 can see real failures. "
        "Plan 00104 Task 5.3 / hostile review C-6."
    )
