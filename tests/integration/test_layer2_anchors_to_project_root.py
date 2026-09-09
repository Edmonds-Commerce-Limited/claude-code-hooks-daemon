"""Plan 00291 canary finding — Layer 2 must run AT the project root it was given.

Both Layer 2 orchestrators take ``PROJECT_ROOT`` as an argument, but the
daemon-control helpers they source (``scripts/install/daemon_control.sh``)
invoke ``daemon.cli start|stop|status`` with no ``--project-root``, and the
CLI resolves the project it manages from the CURRENT WORKING DIRECTORY.
Run from anywhere else, an upgrade therefore starts and "verifies" a daemon
for whatever project the shell happened to be standing in, writes that
daemon's socket and PID file into THAT project's untracked dir, and reports
a clean success for the client it never touched. The php-qa-ci canary re-run
did exactly this when driven from the daemon repository's own checkout.

The fix is one anchor: each orchestrator resolves its two path arguments to
absolute form and then ``cd``s to ``PROJECT_ROOT`` before its first step, so
every cwd-bound call downstream sees the right project. These tests pin the
anchor structurally; ``tests/acceptance/test_guarded_branch_install.py``
proves it behaviourally by driving the upgrade from a foreign cwd.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYER2_SCRIPTS = (
    REPO_ROOT / "scripts" / "upgrade_version.sh",
    REPO_ROOT / "scripts" / "install_version.sh",
)

_ANCHOR = re.compile(r'^cd "\$PROJECT_ROOT"', re.MULTILINE)
_FIRST_STEP = re.compile(r'^log_step "1"', re.MULTILINE)


@pytest.mark.parametrize("script", LAYER2_SCRIPTS, ids=lambda p: p.name)
def test_layer2_cds_to_the_project_root_before_its_first_step(script: Path) -> None:
    content = script.read_text(encoding="utf-8")
    anchor = _ANCHOR.search(content)
    first_step = _FIRST_STEP.search(content)
    assert anchor is not None, (
        f'{script.name} never `cd "$PROJECT_ROOT"`: every daemon.cli call it makes '
        "resolves the project from the caller's cwd and can start a daemon for the "
        "wrong project while reporting success."
    )
    assert first_step is not None, f'{script.name} has no `log_step "1"` to anchor before'
    assert anchor.start() < first_step.start(), (
        f"{script.name} anchors to PROJECT_ROOT only after its first step; a daemon "
        "started before the anchor still belongs to the caller's cwd."
    )


@pytest.mark.parametrize("script", LAYER2_SCRIPTS, ids=lambda p: p.name)
def test_layer2_resolves_relative_path_arguments_before_anchoring(script: Path) -> None:
    """A relative DAEMON_DIR would point somewhere else once the cwd changes."""
    content = script.read_text(encoding="utf-8")
    anchor = _ANCHOR.search(content)
    assert anchor is not None
    before_anchor = content[: anchor.start()]
    assert 'DAEMON_DIR="$(cd "$DAEMON_DIR" && pwd)"' in before_anchor, (
        f"{script.name} must resolve DAEMON_DIR to an absolute path before it cds, "
        "or a relative argument silently points at a different directory."
    )
    assert (
        'PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"' in before_anchor
    ), f"{script.name} must resolve PROJECT_ROOT to an absolute path before it cds"
