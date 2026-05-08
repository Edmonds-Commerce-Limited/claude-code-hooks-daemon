"""Plan 00105 Phase 5 Task 5.2 — silent hardlink→copy fallback removal.

When ``uv sync`` emits "Failed to hardlink files" on overlay-fs (the typical
container filesystem), ``create_venv_at_path()`` retries automatically with
``UV_LINK_MODE=copy``. Until v3.10.x the retry was announced via
``print_verbose`` — which is silent unless the operator set
``HOOKS_DAEMON_VERBOSE_INSTALL=1``. That is exactly the silent-fallback
antipattern flagged in project memory ``feedback_silent_fallback_antipattern.md``:
the operator never learns that hardlink failed and copy mode is being used,
so the next time hardlink mode IS expected to work (different fs), they
have no signal that the previous run silently shifted to copy.

This test pins the fix: the hardlink→copy retry must announce itself via
``print_warning`` (or ``print_info``) so it is visible by default, while
preserving the recovery (the retry itself stays — overlay-fs containers
must still install successfully out-of-the-box).

Static-check test — inspects ``scripts/install/venv.sh``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_SH = REPO_ROOT / "scripts" / "install" / "venv.sh"


def _create_venv_at_path_body() -> str:
    content = VENV_SH.read_text()
    match = re.search(
        r"create_venv_at_path\(\)\s*\{.*?\n\}",
        content,
        re.DOTALL,
    )
    assert match is not None, "create_venv_at_path() function not found in venv.sh"
    return match.group(0)


def test_hardlink_failure_branch_uses_loud_helper() -> None:
    """The hardlink→copy retry must announce itself loudly, not silently.

    Locate the ``"Failed to hardlink"`` detection branch and verify that
    the announcement of the retry uses ``print_warning`` or ``print_info``
    — both of which write to stderr unconditionally — rather than
    ``print_verbose`` which is silent unless ``VERBOSE=true``.
    """
    body = _create_venv_at_path_body()

    branch_match = re.search(
        r'grep -q "Failed to hardlink"[^\n]*\n(?P<branch>.*?)\n\s*fi\b',
        body,
        re.DOTALL,
    )
    assert branch_match is not None, (
        "could not locate the 'Failed to hardlink' detection branch in "
        "create_venv_at_path() — the static structure has changed and "
        "this test must be re-pinned."
    )

    branch = branch_match.group("branch")

    uses_print_verbose_for_announcement = bool(
        re.search(
            r'print_verbose\s+"[^"]*(?:hardlink|UV_LINK_MODE=copy|retrying)',
            branch,
            re.IGNORECASE,
        ),
    )
    assert not uses_print_verbose_for_announcement, (
        "venv.sh:create_venv_at_path() still announces the hardlink→copy "
        "retry via print_verbose, which is silent unless "
        "VERBOSE=true. Operators get no signal that hardlink failed and "
        "the retry happened. Replace with print_warning (or print_info) "
        "so the fallback is visible by default. "
        "See Plan 00105 Phase 5 Task 5.2 and the feedback memory "
        "`silent fallback hides regressions`."
    )

    uses_loud_helper = bool(
        re.search(
            r'print_(?:warning|info)\s+"[^"]*(?:hardlink|UV_LINK_MODE=copy|retrying)',
            branch,
            re.IGNORECASE,
        ),
    )
    assert uses_loud_helper, (
        "venv.sh:create_venv_at_path() must announce the hardlink→copy "
        "retry via print_warning or print_info so the operator sees that "
        "the fallback engaged. The announcement must mention either "
        "'hardlink', 'UV_LINK_MODE=copy', or 'retrying' so the message is "
        "diagnostically useful."
    )


def test_hardlink_retry_still_attempted() -> None:
    """The retry behavior MUST be preserved — only the silence is removed.

    Removing the auto-retry would break overlay-fs container installs
    (the most common self-install deployment). This test guards against
    an over-zealous fix that removes the retry along with the silence.
    """
    body = _create_venv_at_path_body()

    has_retry = bool(
        re.search(
            r"UV_LINK_MODE=copy\s+UV_PROJECT_ENVIRONMENT[^\n]*uv sync",
            body,
        ),
    )
    assert has_retry, (
        "venv.sh:create_venv_at_path() no longer retries with "
        "UV_LINK_MODE=copy after a hardlink failure. The retry is "
        "essential for overlay-fs container installs and must NOT "
        "be removed — only the silence around it is the target of "
        "Plan 00105 Phase 5 Task 5.2."
    )
