"""A forwarder must not relay from a checkout it was not generated for.

The relay guard bakes absolute literals on purpose: it is a zero-spawn hot
path, so nothing in it may be computed at hook-run time. A git worktree
inherits the tracked `.claude/hooks/*` VERBATIM, literals included, so its
`pre-tool-use` dialled the MAIN checkout's relay socket and was answered by
the MAIN checkout's daemon. Every hook event in a worktree agent's session
was then judged by another checkout's config, handlers and project handlers,
silently and with no error anywhere (Plan 00363's acceptance harness measured
the wrong checkout for exactly this reason; Plan 00364 Task 5.1).

These probes run the generated file for real, with a relay binary and a live
socket present for checkout A, and assert on which side answers:

- run from A: the relay is exec'd (the hot path still works);
- run from B, byte-identical file: the relay is NOT exec'd, and B's own
  `init.sh` answers instead — the fall-through that computes B's socket.

The relay binary here is a stub, deliberately. What is under test is the
guard's decision, and a stub makes "the relay ran" observable on stdout
without needing the Rust binary built on the machine running the suite.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.install.forwarder_generator import generate_forwarder_content

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_FORWARDER = _REPO_ROOT / ".claude" / "hooks" / "pre-tool-use"

_RELAY_MARKER = "RELAY-EXECD"
_FALLBACK_MARKER = "ANSWERED-BY-INIT-SH"

#: Stands in for the real init.sh: the fall-through path must be observable,
#: and must report WHICH checkout answered.
_STUB_INIT_SH = f"""#!/bin/bash
ensure_daemon() {{ return 0; }}
emit_hook_error() {{ echo "HOOKS DAEMON ERROR: $*"; }}
send_request_stdin() {{ echo "{_FALLBACK_MARKER} $SCRIPT_DIR"; }}
forward_stop_event() {{ echo "{_FALLBACK_MARKER} $SCRIPT_DIR"; }}
"""

_STUB_RELAY = f"""#!/bin/bash
echo "{_RELAY_MARKER} $*"
exit 0
"""


def _make_checkout(root: Path, content: str) -> Path:
    """A checkout holding `content` as its deployed pre-tool-use forwarder."""
    hooks_dir = root / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    (root / ".claude" / "init.sh").write_text(_STUB_INIT_SH)
    forwarder = hooks_dir / "pre-tool-use"
    forwarder.write_text(content)
    forwarder.chmod(0o755)
    return forwarder


def _make_relay_binary(root: Path) -> Path:
    relay = root / "untracked" / "bin" / "hooks-relay"
    relay.parent.mkdir(parents=True)
    relay.write_text(_STUB_RELAY)
    relay.chmod(0o755)
    return relay


@pytest.fixture
def events_dir(tmp_path: Path) -> Iterator[Path]:
    """A live per-event socket, so the guard's own `-S` test is satisfied."""
    directory = tmp_path / "events"
    directory.mkdir()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(directory / "pre-tool-use.sock"))
    server.listen(1)
    yield directory
    server.close()


@pytest.fixture
def checkouts(tmp_path: Path, events_dir: Path) -> tuple[Path, Path]:
    """`(generated_for_a, verbatim_copy_under_b)`.

    B receives the same bytes A does, which is precisely what `git worktree
    add` produces for a tracked file.
    """
    root_a = tmp_path / "checkout-a"
    root_b = tmp_path / "checkout-b"
    content = generate_forwarder_content(
        _REAL_FORWARDER.read_text(),
        "pre-tool-use",
        TransportConfig(relay_enabled=True),
        root_a / "untracked",
        root_a,
    )
    assert "relay hot path" in content, "the fixture must carry a guard to be worth running"
    forwarder_a = _make_checkout(root_a, content)
    forwarder_b = _make_checkout(root_b, content)
    _make_relay_binary(root_a)
    return forwarder_a, forwarder_b


def _run(forwarder: Path, events_dir: Path, *, cwd: Path | None = None) -> str:
    env = os.environ.copy()
    env["HOOKS_DAEMON_EVENTS_DIR"] = str(events_dir)
    completed = subprocess.run(
        ["bash", str(forwarder)],
        input=b'{"tool_name":"Bash","hook_event_name":"PreToolUse"}',
        capture_output=True,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        timeout=Timeout.REQUEST_DEFAULT,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode()
    return completed.stdout.decode()


class TestTheCheckoutTheGuardWasGeneratedFor:
    def test_the_relay_is_execd(self, checkouts: tuple[Path, Path], events_dir: Path) -> None:
        """The control: without this, the test below could pass vacuously."""
        forwarder_a, _ = checkouts
        assert _RELAY_MARKER in _run(forwarder_a, events_dir)

    def test_the_relay_receives_the_event_socket(
        self, checkouts: tuple[Path, Path], events_dir: Path
    ) -> None:
        forwarder_a, _ = checkouts
        assert str(events_dir / "pre-tool-use.sock") in _run(forwarder_a, events_dir)


class TestAVerbatimCopyUnderAnotherCheckout:
    def test_the_relay_is_not_execd(self, checkouts: tuple[Path, Path], events_dir: Path) -> None:
        """The defect, reproduced: same bytes, same live socket, other root."""
        _, forwarder_b = checkouts
        assert _RELAY_MARKER not in _run(forwarder_b, events_dir)

    def test_its_own_init_sh_answers_instead(
        self, checkouts: tuple[Path, Path], events_dir: Path
    ) -> None:
        """Falling through is only useful if it lands in B's own transport."""
        _, forwarder_b = checkouts
        output = _run(forwarder_b, events_dir)
        assert _FALLBACK_MARKER in output
        assert str(forwarder_b.parent) in output

    def test_the_working_directory_does_not_change_the_verdict(
        self, checkouts: tuple[Path, Path], events_dir: Path, tmp_path: Path
    ) -> None:
        """The guard judges the FILE, not the cwd — a hook's cwd is the user's.

        Claude Code invokes the hook by absolute path from whatever directory
        the session is in, so a cwd-based test would answer differently for
        the same file depending on where the agent happened to be standing.
        """
        forwarder_a, forwarder_b = checkouts
        assert _RELAY_MARKER in _run(forwarder_a, events_dir, cwd=forwarder_b.parent)
        assert _RELAY_MARKER not in _run(forwarder_b, events_dir, cwd=forwarder_a.parent)


class TestAnInvocationByRelativePath:
    """A conservative miss: falls back, never relays to the wrong checkout.

    Claude Code's own settings.json invokes every hook as
    `bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/<event>`, so `BASH_SOURCE[0]` is
    absolute in the case that matters. A relative invocation (a person testing
    by hand from the checkout root) does not match the baked prefix and takes
    the legacy transport: one slower round trip, and the answer still comes
    from the right checkout. Pinned so the cost of the trade is visible rather
    than discovered.
    """

    def test_it_falls_through_rather_than_relaying(
        self, checkouts: tuple[Path, Path], events_dir: Path
    ) -> None:
        forwarder_a, _ = checkouts
        root_a = forwarder_a.parents[2]
        env = os.environ.copy()
        env["HOOKS_DAEMON_EVENTS_DIR"] = str(events_dir)
        completed = subprocess.run(
            ["bash", ".claude/hooks/pre-tool-use"],
            input=b"{}",
            capture_output=True,
            cwd=str(root_a),
            env=env,
            timeout=Timeout.REQUEST_DEFAULT,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr.decode()
        assert _RELAY_MARKER not in completed.stdout.decode()
        assert _FALLBACK_MARKER in completed.stdout.decode()


class TestTheStubsAreNotHidingAMissingDependency:
    def test_bash_is_available(self) -> None:
        """Every probe above is a bash subprocess; say so if bash is absent."""
        assert shutil.which("bash"), "these probes need bash on PATH"
