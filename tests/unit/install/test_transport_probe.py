"""Tests for the Plan 00290 transport probe (DESIGN-socket-relay.md §6.3).

Read-only and cheap: reports rung availability facts without mutating
anything or requiring a live daemon.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from claude_code_hooks_daemon.install.transport_probe import (
    TransportProbeResult,
    probe_transport,
    render_env_lines,
)


def test_relay_binary_absent(tmp_path: Path) -> None:
    result = probe_transport(project_root=tmp_path, relay_binary=tmp_path / "no-such-binary")
    assert result.relay_binary_present is False
    assert result.relay_binary_executable is False
    assert result.relay_digest_verified is None


def test_relay_binary_present_not_executable(tmp_path: Path) -> None:
    binary = tmp_path / "hooks-relay"
    binary.write_bytes(b"not-really-elf")
    binary.chmod(0o644)

    result = probe_transport(project_root=tmp_path, relay_binary=binary)

    assert result.relay_binary_present is True
    assert result.relay_binary_executable is False


def test_relay_binary_present_and_executable(tmp_path: Path) -> None:
    binary = tmp_path / "hooks-relay"
    binary.write_bytes(b"pretend-binary")
    binary.chmod(0o755)

    result = probe_transport(project_root=tmp_path, relay_binary=binary)

    assert result.relay_binary_present is True
    assert result.relay_binary_executable is True


def test_digest_verification_no_manifest_is_unknown(tmp_path: Path) -> None:
    binary = tmp_path / "hooks-relay"
    binary.write_bytes(b"pretend-binary")
    binary.chmod(0o755)

    result = probe_transport(
        project_root=tmp_path, relay_binary=binary, sha256sums_path=tmp_path / "missing.sums"
    )

    assert result.relay_digest_verified is None


def test_digest_verification_matches(tmp_path: Path) -> None:
    binary = tmp_path / "hooks-relay-x86_64-unknown-linux-musl"
    content = b"pretend-binary-bytes"
    binary.write_bytes(content)
    binary.chmod(0o755)
    digest = hashlib.sha256(content).hexdigest()
    sums = tmp_path / "SHA256SUMS.released"
    sums.write_text(f"{digest}  {binary.name}\n")

    result = probe_transport(project_root=tmp_path, relay_binary=binary, sha256sums_path=sums)

    assert result.relay_digest_verified is True


def test_digest_verification_mismatches(tmp_path: Path) -> None:
    binary = tmp_path / "hooks-relay-x86_64-unknown-linux-musl"
    binary.write_bytes(b"actual-bytes")
    binary.chmod(0o755)
    sums = tmp_path / "SHA256SUMS.released"
    sums.write_text("0" * 64 + f"  {binary.name}\n")

    result = probe_transport(project_root=tmp_path, relay_binary=binary, sha256sums_path=sums)

    assert result.relay_digest_verified is False


def test_nc_absent_from_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))  # empty dir, no nc

    result = probe_transport(project_root=tmp_path, relay_binary=tmp_path / "x")

    assert result.nc_present is False
    assert result.nc_unix_capable is False


def test_nc_present_without_dash_u_flag(tmp_path: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    nc = bin_dir / "nc"
    nc.write_text("#!/bin/sh\necho 'usage: nc [options]'\n")
    nc.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    result = probe_transport(project_root=tmp_path, relay_binary=tmp_path / "x")

    assert result.nc_present is True
    assert result.nc_unix_capable is False


def test_nc_present_with_dash_u_flag(tmp_path: Path, monkeypatch) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    nc = bin_dir / "nc"
    nc.write_text("#!/bin/sh\necho 'usage: nc [-46CDdFhklNnrStUuvz] ... -U'\n")
    nc.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))

    result = probe_transport(project_root=tmp_path, relay_binary=tmp_path / "x")

    assert result.nc_present is True
    assert result.nc_unix_capable is True


def test_event_socket_dir_presence(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    absent = probe_transport(project_root=project_root, relay_binary=tmp_path / "x")
    assert absent.event_socket_dir_present is False

    from claude_code_hooks_daemon.daemon.paths import get_event_socket_dir

    get_event_socket_dir(project_root).mkdir(parents=True)
    present = probe_transport(project_root=project_root, relay_binary=tmp_path / "x")
    assert present.event_socket_dir_present is True


def test_render_env_lines_both_rungs_off() -> None:
    result = TransportProbeResult(
        relay_binary_present=False,
        relay_binary_executable=False,
        relay_digest_verified=None,
        nc_present=False,
        nc_unix_capable=False,
        event_socket_dir_present=False,
    )
    lines = render_env_lines(result, relay_enabled=False, nc_enabled=False)
    assert lines == []


def test_render_env_lines_nc_capable() -> None:
    result = TransportProbeResult(
        relay_binary_present=False,
        relay_binary_executable=False,
        relay_digest_verified=None,
        nc_present=True,
        nc_unix_capable=True,
        event_socket_dir_present=False,
    )
    lines = render_env_lines(result, relay_enabled=False, nc_enabled=True)
    assert 'HOOKS_DAEMON_NC_UNIX_CAPABLE="1"' in lines


def test_render_env_lines_nc_enabled_but_not_capable() -> None:
    result = TransportProbeResult(
        relay_binary_present=False,
        relay_binary_executable=False,
        relay_digest_verified=None,
        nc_present=True,
        nc_unix_capable=False,
        event_socket_dir_present=False,
    )
    lines = render_env_lines(result, relay_enabled=False, nc_enabled=True)
    assert 'HOOKS_DAEMON_NC_UNIX_CAPABLE="0"' in lines
