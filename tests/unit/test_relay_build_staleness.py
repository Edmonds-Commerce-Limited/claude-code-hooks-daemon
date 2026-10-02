"""The relay build's content stamp decides whether a built binary is stale (N319)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from tests.relay_gate_guard import (
    relay_build_staleness_message,
    relay_build_stamp_path,
)


def _source(tmp_path: Path, text: str = "fn main() {}\n") -> Path:
    source = tmp_path / "hooks_relay.rs"
    source.write_text(text)
    return source


def _binary(tmp_path: Path) -> Path:
    binary = tmp_path / "hooks-relay-x86_64-unknown-linux-musl"
    binary.write_bytes(b"\x7fELF")
    return binary


def _stamp(binary: Path, text: str) -> None:
    relay_build_stamp_path(binary).write_text(hashlib.sha256(text.encode()).hexdigest() + "\n")


def test_stamp_path_is_a_sidecar_named_source_sha256(tmp_path: Path) -> None:
    binary = tmp_path / "hooks-relay-x"
    assert relay_build_stamp_path(binary) == tmp_path / "hooks-relay-x.source-sha256"


def test_fresh_build_has_no_message(tmp_path: Path) -> None:
    source, binary = _source(tmp_path), _binary(tmp_path)
    _stamp(binary, source.read_text())
    assert relay_build_staleness_message(binary, source) is None


def test_stale_build_names_binary_and_rebuild_command(tmp_path: Path) -> None:
    source, binary = _source(tmp_path), _binary(tmp_path)
    _stamp(binary, "an older source\n")
    message = relay_build_staleness_message(binary, source)
    assert message is not None
    assert f"the relay build at {binary} is older than relay/hooks_relay.rs" in message
    assert "rebuild with `bash relay/build.sh`" in message


def test_binary_without_sidecar_is_stale(tmp_path: Path) -> None:
    source, binary = _source(tmp_path), _binary(tmp_path)
    assert relay_build_staleness_message(binary, source) is not None


def test_absent_binary_is_not_stale(tmp_path: Path) -> None:
    source = _source(tmp_path)
    assert relay_build_staleness_message(tmp_path / "absent", source) is None
