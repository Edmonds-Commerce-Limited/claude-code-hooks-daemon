"""Plan 00104 Phase 2 Task 2.3 — Task 5.1 stray-uv.lock cleanup (closed).

The 2026-05-01 field report (problem #3) showed that an untracked ``uv.lock``
in the daemon directory blocks ``git checkout`` during version-switching
upgrades:

    error: The following untracked working tree files would be overwritten
    by checkout: uv.lock
    Please move or remove them before you switch branches.
    Aborting

Decision 5 of Plan 00104 fixed this in two steps:

  (a) The daemon repo's own ``.gitignore`` lists ``uv.lock``.
  (b) The skill ``upgrade.sh`` actively removes any stray ``uv.lock`` it
      finds in the daemon directory before delegating to the Layer 1
      upgrader (which runs ``git checkout``).

Both shipped. This test is a **static-source check** rather than a full
integration run because the field-report failure is binary at the source
level: either the cleanup line exists in the skill ``upgrade.sh`` script
before the delegate-to-Layer-1 call, or it does not. A behaviour-level
test would need a real git fixture with tracked-vs-untracked tag
boundaries plus a mocked Layer 1, which adds a lot of moving parts for
the same binary outcome.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_UPGRADE_SCRIPT = (
    REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "skills"
    / "hooks-daemon"
    / "scripts"
    / "upgrade.sh"
)

CLEANUP_PATTERNS = [
    re.compile(r"\brm\s+(-[A-Za-z]*f[A-Za-z]*\s+)?[\"']?\$\{?DAEMON_DIR\}?/uv\.lock"),
    re.compile(r"\bgit\s+-C\s+\"?\$\{?DAEMON_DIR\}?\"?\s+restore\b.*\buv\.lock\b"),
    re.compile(r"\bgit\s+-C\s+\"?\$\{?DAEMON_DIR\}?\"?\s+clean\b.*\buv\.lock\b"),
]

DELEGATE_PATTERN = re.compile(r"^\s*bash\s+\"?\$\{?UPGRADE_SCRIPT\}?\"?", re.MULTILINE)


def test_skill_upgrade_cleans_stale_uv_lock_before_delegate() -> None:
    """The skill ``upgrade.sh`` must remove any stray ``uv.lock`` in the
    daemon directory before delegating to the Layer 1 upgrade script
    (which performs ``git checkout``)."""
    source = SKILL_UPGRADE_SCRIPT.read_text()
    assert source, SKILL_UPGRADE_SCRIPT

    delegate_match = DELEGATE_PATTERN.search(source)
    assert delegate_match, (
        'Could not locate the Layer 1 delegate call (bash "$UPGRADE_SCRIPT" ...) '
        f"in {SKILL_UPGRADE_SCRIPT}. The skill upgrade flow has changed shape; "
        "update this test before flipping the xfail."
    )
    pre_delegate = source[: delegate_match.start()]

    found_cleanups = [pat.pattern for pat in CLEANUP_PATTERNS if pat.search(pre_delegate)]
    assert found_cleanups, (
        "skill upgrade.sh must clean any stray uv.lock from $DAEMON_DIR "
        "BEFORE delegating to Layer 1 (which runs `git checkout`). "
        "None of the expected cleanup patterns matched. "
        f"Inspect {SKILL_UPGRADE_SCRIPT} and add either:\n"
        '  rm -f "$DAEMON_DIR/uv.lock"\n'
        '  git -C "$DAEMON_DIR" restore -- uv.lock\n'
        '  git -C "$DAEMON_DIR" clean -f -- uv.lock\n'
        'before the line: bash "$UPGRADE_SCRIPT" ...'
    )
