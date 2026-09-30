"""The upgrade stops the daemon through the CLI's proof alone (ledger 00466 N245).

Layer 1 (``scripts/upgrade.sh``) runs with no venv, before the checkout, so it
kept a shell matcher of its own and signalled what that matched: a
``ps``-then-``kill`` with no uid check and no pin on the identity it read, a
project root taken from the interpreter's venv path (which the Python proof
dropped in round 6, Sh-1), and a command line split at every space, so a root
holding one could not be matched.

Layer 1 now signals nothing. The daemon is stopped by Layer 2's Step 4, which
runs straight after the checkout and calls ``daemon_control.sh``'s
``stop_daemon_safe``: the CLI's ``stop``, with its uid check, pidfd pin,
start-time check and every spelling of the root. That stop, on a daemon an
older version started and on a root holding a space, is exercised end to end
by ``test_a_daemon_of_a_symlinked_project_is_stoppable.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade.sh"
UPGRADE_VERSION_SH = REPO_ROOT / "scripts" / "upgrade_version.sh"

#: A command that sends a signal, where a shell would run it.
_SIGNALLING_COMMAND = re.compile(r"(^|[\s;&|(`$])(kill|pkill|killall)(\s|$)")


def _commands(script: Path) -> list[str]:
    """The lines of ``script`` that are not comments."""
    return [line for line in script.read_text().splitlines() if not line.lstrip().startswith("#")]


def test_layer_1_signals_no_process() -> None:
    signalling = [line for line in _commands(UPGRADE_SH) if _SIGNALLING_COMMAND.search(line)]

    assert signalling == []


def test_layer_1_keeps_no_daemon_matcher_of_its_own() -> None:
    text = UPGRADE_SH.read_text()

    assert "_is_project_daemon_pid" not in text
    assert "_stop_running_daemons" not in text


def test_layer_2_stops_the_daemon_through_the_cli_before_it_changes_the_install() -> None:
    """Step 4 stops it; Step 5 is the first to touch the install's files."""
    text = UPGRADE_VERSION_SH.read_text()

    stop = text.index('stop_daemon_safe "$VENV_PYTHON"')

    assert text.index("# Step 4: Stop daemon") < stop < text.index("# Step 5:")
