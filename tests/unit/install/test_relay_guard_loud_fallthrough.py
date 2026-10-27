"""The relay guard falls through LOUDLY and never fails open (Plan 00529 Task 2c).

When the per-event socket exists (a daemon is listening) but the relay binary
cannot run, the guard must reach ``source init.sh`` with stdin unread and the
unused-relay marker set, so the bash path judges the call and every answer
names the binary. Three ways the binary cannot run, each verified by hand
before these tests were written:

- missing (or not executable): the ``-x`` test fails;
- a text file at the path: bash's ``exec`` gets ENOEXEC and RUNS THE FILE AS A
  SHELL SCRIPT, so the guard refuses anything the kernel would not run itself
  (an ELF file or a ``#!`` script);
- a corrupt ELF: ``exec`` fails, and under ``set -e`` bash exits 1 even inside
  an ``if`` and even with ``shopt -s execfail``, so errexit is lifted around it.

No socket means no daemon: the bash path is the start-up path and reports
loudly on its own, so no marker is set there.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.install.forwarder_generator import (
    RELAY_UNUSED_ENV,
    build_relay_guard_block,
    generate_forwarder_content,
)

#: A forwarder of the deployed shape; the init.sh it sources is a stub.
_SOURCE = """#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../init.sh"
"""

#: Stands in for init.sh: reports the marker and proves stdin arrived whole.
_STUB_INIT_SH = f"""
printf 'MARKER=%s\\n' "${{{RELAY_UNUSED_ENV}-<unset>}}"
printf 'STDIN=%s\\n' "$(cat)"
printf 'ERREXIT=%s\\n' "${{-//[^e]/}}"
"""

_PAYLOAD = '{"tool_name":"Bash","tool_input":{"command":"ls"}}'

#: The ELF magic, then bytes no loader accepts.
_CORRUPT_ELF = b"\x7fELF\x02\x01\x01" + b"\x00" * 9 + b"garbage"

#: A shell script with no shebang: bash would run it if handed to exec.
_TEXT_GARBAGE = b"echo RAN-AS-A-SCRIPT\nexit 0\n"

#: A script whose interpreter does not exist: the kernel refuses it, so exec fails.
_BROKEN_SHEBANG = b"#!/nonexistent/interpreter\necho RAN-AS-A-SCRIPT\n"


@pytest.fixture
def events_dir() -> Iterator[Path]:
    """A short directory, so a socket path stays under the AF_UNIX limit."""
    path = Path(tempfile.mkdtemp(prefix="rlg-"))
    yield path
    shutil.rmtree(path)


def _forwarder(project: Path, relay_binary: Path) -> Path:
    transport = TransportConfig(relay_enabled=True, relay_binary=str(relay_binary))
    content = generate_forwarder_content(
        _SOURCE, "pre-tool-use", transport, project / "untracked", project
    )
    hooks = project / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (project / ".claude" / "init.sh").write_text(_STUB_INIT_SH)
    forwarder = hooks / "pre-tool-use"
    forwarder.write_text(content)
    forwarder.chmod(0o755)
    return forwarder


def _run(forwarder: Path, events: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(forwarder)],
        input=_PAYLOAD,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOOKS_DAEMON_EVENTS_DIR": str(events)},
        timeout=Timeout.VALIDATION_CHECK,
    )


def _with_listening_socket(events: Path) -> socket.socket:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(events / "pre-tool-use.sock"))
    listener.listen(1)
    return listener


def _binary(tmp_path: Path, content: bytes | None) -> Path:
    binary = tmp_path / "bin" / "hooks-relay"
    if content is not None:
        binary.parent.mkdir()
        binary.write_bytes(content)
        binary.chmod(0o755)
    return binary


@pytest.mark.parametrize(
    "content",
    [None, _TEXT_GARBAGE, _CORRUPT_ELF, b"", b"\x7fEL", _BROKEN_SHEBANG],
    ids=["missing", "text-garbage", "corrupt-elf", "empty", "short", "broken-shebang"],
)
def test_an_unrunnable_relay_falls_through_with_the_marker(
    tmp_path: Path, events_dir: Path, content: bytes | None
) -> None:
    binary = _binary(tmp_path, content)
    forwarder = _forwarder(tmp_path / "proj", binary)
    listener = _with_listening_socket(events_dir)
    try:
        result = _run(forwarder, events_dir)
    finally:
        listener.close()

    assert result.returncode == 0, result.stderr
    assert "RAN-AS-A-SCRIPT" not in result.stdout
    assert f"MARKER={binary}\n" in result.stdout
    assert f"STDIN={_PAYLOAD}\n" in result.stdout
    # The guard lifts errexit around the exec only; init.sh gets it back.
    assert "ERREXIT=e\n" in result.stdout


def test_a_non_executable_relay_falls_through_with_the_marker(
    tmp_path: Path, events_dir: Path
) -> None:
    binary = _binary(tmp_path, _CORRUPT_ELF)
    binary.chmod(0o644)
    forwarder = _forwarder(tmp_path / "proj", binary)
    listener = _with_listening_socket(events_dir)
    try:
        result = _run(forwarder, events_dir)
    finally:
        listener.close()

    assert result.returncode == 0, result.stderr
    assert f"MARKER={binary}\n" in result.stdout


def test_no_socket_means_no_marker(tmp_path: Path, events_dir: Path) -> None:
    """No daemon is listening: the start-up path below reports on its own."""
    forwarder = _forwarder(tmp_path / "proj", _binary(tmp_path, None))

    result = _run(forwarder, events_dir)

    assert result.returncode == 0, result.stderr
    assert "MARKER=<unset>\n" in result.stdout
    assert f"STDIN={_PAYLOAD}\n" in result.stdout


def test_a_worktree_copy_sets_no_marker(tmp_path: Path, events_dir: Path) -> None:
    """A copy outside its own checkout skips the guard before any binary test."""
    forwarder = _forwarder(tmp_path / "proj", _binary(tmp_path, _TEXT_GARBAGE))
    copy_root = tmp_path / "worktree"
    (copy_root / ".claude" / "hooks").mkdir(parents=True)
    shutil.copy(tmp_path / "proj" / ".claude" / "init.sh", copy_root / ".claude" / "init.sh")
    copy = copy_root / ".claude" / "hooks" / "pre-tool-use"
    shutil.copy(forwarder, copy)
    listener = _with_listening_socket(events_dir)
    try:
        result = _run(copy, events_dir)
    finally:
        listener.close()

    assert result.returncode == 0, result.stderr
    assert "RAN-AS-A-SCRIPT" not in result.stdout
    assert "MARKER=<unset>\n" in result.stdout


def test_the_guard_turns_on_execfail_and_names_the_marker() -> None:
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), Path("/p/u"), Path("/p")
    )
    assert "shopt -s execfail" in block
    assert f'{RELAY_UNUSED_ENV}="$_rl_bin"' in block


def test_the_elf_check_spawns_nothing() -> None:
    """The magic is read with the ``read`` builtin: no subshell, no command."""
    block = build_relay_guard_block(
        "pre-tool-use", TransportConfig(relay_enabled=True), Path("/p/u"), Path("/p")
    )
    assert 'IFS= read -r -n 4 _rl_magic < "$_rl_bin"' in block
    assert "$(" not in block
    assert "`" not in block
