"""The env an acceptance test hands to a spawned production wrapper (Plan 00445).

Every acceptance suite that dispatches a real hook event does it by spawning
``.claude/hooks/<wrapper>`` as a subprocess. The wrapper resolves the daemon
socket ITSELF, from ``init.sh``, using the environment it inherits — so the
socket the test fixtures resolved and the socket the wrapper talks to are two
independent answers that nothing forced to agree.

They disagree whenever ``CLAUDE_HOOKS_SOCKET_PATH`` is in play, because
``tests/conftest.py``'s ``isolate_daemon_path_overrides`` is ``autouse`` and
deletes it for every test. That fixture is correct and stays: an ambient
override makes the path tests assert against a path they never chose. But its
unset is inherited by every subprocess a test spawns, and the wrapper then
resolves the DEFAULT path, finds no live socket, and lets ``ensure_daemon``
spend ``DAEMON_STARTUP_TIMEOUT`` before giving up — per probe, silently.

That is ledger 00422 N6 fault 2: measured at 13.91s for the playbook harness
when the paths happen to agree, and an unbounded hang when they do not.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.acceptance.conftest import wrapper_subprocess_env

_ECHO_SOCKET = 'printf "%s" "${CLAUDE_HOOKS_SOCKET_PATH:-<unset>}"'


def _spawn(env: dict[str, str] | None) -> str:
    """What a child sees for the socket override, spawned as a dispatcher does."""
    result = subprocess.run(  # nosec B603 B607 - trusted system tool, list form
        ["bash", "-c", _ECHO_SOCKET],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return result.stdout.strip()


class TestASpawnedWrapperIsToldWhichDaemonToTalkTo:
    def test_the_child_sees_the_socket_the_fixtures_resolved(self, daemon_socket: Path) -> None:
        """The gate: the two independent answers are forced to agree."""
        assert _spawn(wrapper_subprocess_env(daemon_socket)) == str(daemon_socket)

    def test_plain_inheritance_does_not_carry_it(self) -> None:
        """The control, and the reason the fixture above has to exist.

        Without it this file could pass while changing nothing: if the
        variable happened to reach a child by inheritance, the test above
        would be satisfied by the very leak it is meant to replace. So pin
        the defect itself — under the autouse isolation fixture, an inherited
        environment carries no override, whatever the calling shell exported.
        """
        assert os.environ.get("CLAUDE_HOOKS_SOCKET_PATH") is None
        assert _spawn(None) == "<unset>"

    def test_the_env_is_the_caller_s_environment_plus_the_override(
        self, daemon_socket: Path
    ) -> None:
        """Everything else a wrapper needs (PATH, HOME) must survive.

        Building the env from scratch would strip the interpreter discovery
        and hostname suffix ``init.sh`` depends on, trading one silent
        misroute for another.
        """
        env = wrapper_subprocess_env(daemon_socket)
        assert env["PATH"] == os.environ["PATH"]
        assert env["CLAUDE_HOOKS_SOCKET_PATH"] == str(daemon_socket)

    def test_it_does_not_mutate_the_calling_process_environment(self, daemon_socket: Path) -> None:
        """A helper that exported the value would defeat the autouse fixture.

        The isolation fixture removes the variable precisely so no test can
        see an ambient one; a helper that put it back in ``os.environ`` would
        reintroduce it for every test that ran afterwards in the same process.
        """
        wrapper_subprocess_env(daemon_socket)
        assert os.environ.get("CLAUDE_HOOKS_SOCKET_PATH") is None
