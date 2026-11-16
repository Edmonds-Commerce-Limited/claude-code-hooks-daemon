"""Generated forwarders are byte-identical on every machine and in every root (Plan 00609).

A project that TRACKS its ``.claude/hooks/*`` gets a dirty checkout whenever
another machine regenerates them, if the generator wrote a machine-specific
value into the file. Everything such a value could be is resolved at run time
instead: the checkout root from ``BASH_SOURCE``, the per-event socket directory
from the untracked dir (or the location file the daemon publishes when the
natural path overflows the AF_UNIX limit).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.daemon import paths
from claude_code_hooks_daemon.install.forwarder_generator import (
    generate_forwarder_content,
    regenerate_deployed_hooks,
    surviving_absolute_paths,
)

_REPO_HOOKS = Path(__file__).resolve().parents[3] / ".claude" / "hooks"

#: One root far below the AF_UNIX limit, one far above it (the shape-changing branch).
_SHORT_ROOT = Path("/a")
_LONG_ROOT = Path("/" + "/".join(["deeply-nested-checkout-directory"] * 4))

_TRANSPORTS = {
    "relay": TransportConfig(relay_enabled=True),
    "nc": TransportConfig(relay_enabled=False, nc_enabled=True),
    "both": TransportConfig(relay_enabled=True, nc_enabled=True),
}


def _sources() -> dict[str, str]:
    return {p.name: p.read_text() for p in sorted(_REPO_HOOKS.iterdir()) if p.is_file()}


def _generate_everywhere(
    monkeypatch: pytest.MonkeyPatch, root: Path, transport: TransportConfig, host: str, xdg: str
) -> dict[str, str]:
    monkeypatch.setenv("XDG_RUNTIME_DIR", xdg)
    monkeypatch.setattr(paths, "_get_hostname_suffix", lambda: f"-{host}")
    return {
        name: generate_forwarder_content(src, name, transport, root / "untracked", root)
        for name, src in _sources().items()
    }


@pytest.mark.parametrize("transport_name", sorted(_TRANSPORTS))
def test_two_roots_two_hosts_generate_identical_bytes(
    monkeypatch: pytest.MonkeyPatch, transport_name: str
) -> None:
    transport = _TRANSPORTS[transport_name]
    first = _generate_everywhere(monkeypatch, _SHORT_ROOT, transport, "host-one", "/run/user/1000")
    second = _generate_everywhere(monkeypatch, _LONG_ROOT, transport, "Host-Two", "/run/user/2000")

    assert first.keys() == second.keys()
    differing = sorted(name for name in first if first[name] != second[name])
    assert differing == []


@pytest.mark.parametrize("transport_name", sorted(_TRANSPORTS))
def test_no_machine_specific_absolute_path_survives(
    monkeypatch: pytest.MonkeyPatch, transport_name: str
) -> None:
    generated = _generate_everywhere(
        monkeypatch, _LONG_ROOT, _TRANSPORTS[transport_name], "host-one", "/run/user/1000"
    )
    leaked = {n: surviving_absolute_paths(c) for n, c in generated.items()}
    assert {n: v for n, v in leaked.items() if v} == {}
    assert all("/run/user" not in c and str(_LONG_ROOT) not in c for c in generated.values())


def test_regeneration_rewrites_an_old_embedded_block_once(tmp_path: Path) -> None:
    """An old forwarder with baked literals converges, and the next pass is a no-op."""
    project = tmp_path / "proj"
    hooks = project / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    old_block = (
        "# --- relay hot path (generated; Plan 00290) ---\n"
        f'if [[ "${{BASH_SOURCE[0]}}" == "{project}/.claude/hooks/"* ]]; then\n'
        f'    _rl_dir="{project}/untracked"\n'
        f'    _rl_bin="${{HOOKS_DAEMON_RELAY_BINARY:-{project}/untracked/bin/hooks-relay}}"\n'
        "fi\n"
        "# --- end relay hot path ---\n"
    )
    old = _SOURCE.replace("source ", old_block + "source ", 1)
    (hooks / "pre-tool-use").write_text(old)

    first = regenerate_deployed_hooks(project, hooks)
    second = regenerate_deployed_hooks(project, hooks)

    assert first == ["pre-tool-use"]
    assert str(project) not in (hooks / "pre-tool-use").read_text()
    assert second == []


# -- the generated bash resolves the same values at run time ------------------

_SOURCE = """#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../init.sh"
"""
_STUB_INIT_SH = 'printf "FELL-THROUGH\\n"\n'
_FAKE_RELAY = """#!/bin/sh
printf 'RELAY sock=%s root=%s\\n' "$1" "$HOOKS_DAEMON_RELAY_DAEMON_ROOT"
"""


@pytest.fixture
def short_tmp() -> Iterator[Path]:
    """A short directory, so a socket path stays under the AF_UNIX limit."""
    path = Path(tempfile.mkdtemp(prefix="mi-"))
    yield path
    shutil.rmtree(path)


def _install(project: Path, *, relay: bool = True) -> Path:
    """Generate the forwarder in a throwaway root and deploy it (and a fake relay)."""
    transport = TransportConfig(relay_enabled=True)
    content = generate_forwarder_content(
        _SOURCE, "pre-tool-use", transport, project / "untracked", project
    )
    hooks = project / ".claude" / "hooks"
    hooks.mkdir(parents=True)
    (project / ".claude" / "init.sh").write_text(_STUB_INIT_SH)
    forwarder = hooks / "pre-tool-use"
    forwarder.write_text(content)
    if relay:
        binary = project / "untracked" / "bin" / "hooks-relay"
        binary.parent.mkdir(parents=True)
        binary.write_text(_FAKE_RELAY)
        binary.chmod(0o755)
    return forwarder


def _run(forwarder: Path, **extra_env: str) -> subprocess.CompletedProcess[str]:
    env = {"PATH": "/usr/bin:/bin", "HOSTNAME": "testhost", **extra_env}
    return subprocess.run(
        ["bash", str(forwarder)],
        input="{}",
        capture_output=True,
        text=True,
        env=env,
        timeout=Timeout.VALIDATION_CHECK,
    )


def _listen(sock_path: Path) -> socket.socket:
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(sock_path))
    listener.listen(1)
    return listener


def test_the_same_bytes_serve_whichever_root_they_are_copied_to(short_tmp: Path) -> None:
    """One generation, two checkouts: each dials ITS OWN socket and daemon root."""
    forwarder = _install(short_tmp / "one")
    other = short_tmp / "two"
    shutil.copytree(short_tmp / "one", other, symlinks=True)

    for root in (short_tmp / "one", short_tmp / "two"):
        listener = _listen(root / "untracked" / "events-testhost" / "pre-tool-use.sock")
        try:
            result = _run(root / ".claude" / "hooks" / "pre-tool-use")
        finally:
            listener.close()
        assert result.returncode == 0, result.stderr
        assert (
            f"RELAY sock={root}/untracked/events-testhost/pre-tool-use.sock root={root}\n"
            in result.stdout
        ), result.stdout
    assert forwarder.read_text() == (other / ".claude/hooks/pre-tool-use").read_text()


def test_a_relative_invocation_falls_through(short_tmp: Path) -> None:
    """A path bash cannot anchor to a checkout skips the hot path, as the literal test did."""
    _install(short_tmp / "p")
    listener = _listen(short_tmp / "p" / "untracked" / "events-testhost" / "pre-tool-use.sock")
    try:
        result = subprocess.run(
            ["bash", ".claude/hooks/pre-tool-use"],
            input="{}",
            capture_output=True,
            text=True,
            cwd=short_tmp / "p",
            env={"PATH": "/usr/bin:/bin", "HOSTNAME": "testhost"},
            timeout=Timeout.VALIDATION_CHECK,
        )
    finally:
        listener.close()
    assert "FELL-THROUGH" in result.stdout
    assert "RELAY" not in result.stdout


def test_the_published_location_serves_an_overflowing_root(short_tmp: Path) -> None:
    """When the natural events dir is absent, the daemon's location file names the real one."""
    project = short_tmp / "p"
    forwarder = _install(project)
    real_events = short_tmp / "ev"
    listener = _listen(real_events / "pre-tool-use.sock")
    location = project / "untracked" / "events-testhost.location"
    try:
        location.write_text(f"{project}/untracked\n{real_events}\n")
        result = _run(forwarder)
        assert f"RELAY sock={real_events}/pre-tool-use.sock" in result.stdout

        # A location recorded for another checkout is not trusted.
        location.write_text(f"/elsewhere/untracked\n{real_events}\n")
        result = _run(forwarder)
        assert "FELL-THROUGH" in result.stdout
        assert "RELAY" not in result.stdout
    finally:
        listener.close()


def test_the_hot_path_still_spawns_nothing() -> None:
    content = generate_forwarder_content(
        _SOURCE,
        "pre-tool-use",
        TransportConfig(relay_enabled=True),
        Path("/p/untracked"),
        Path("/p"),
    )
    start = content.index("# --- relay hot path")
    end = content.index("# --- end relay hot path ---")
    block = content[start:end]
    assert "$(" not in block
    assert "`" not in block
    assert os.sep + "p" + os.sep not in block
