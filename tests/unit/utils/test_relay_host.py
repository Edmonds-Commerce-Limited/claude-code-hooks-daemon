"""Tests for the host OS/architecture facts the relay binary must match."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils import relay_host


@pytest.mark.parametrize(
    ("platform_name", "machine", "target", "e_machine"),
    [
        ("linux", "x86_64", "x86_64-unknown-linux-musl", 62),
        ("linux", "amd64", "x86_64-unknown-linux-musl", 62),
        ("linux", "aarch64", "aarch64-unknown-linux-musl", 183),
        ("linux", "arm64", "aarch64-unknown-linux-musl", 183),
    ],
)
def test_supported_linux_hosts(
    monkeypatch: pytest.MonkeyPatch,
    platform_name: str,
    machine: str,
    target: str,
    e_machine: int,
) -> None:
    monkeypatch.setattr(relay_host.sys, "platform", platform_name)
    monkeypatch.setattr(relay_host.platform, "machine", lambda: machine)
    assert relay_host.host_relay_target() == target
    assert relay_host.host_elf_machine() == e_machine
    assert relay_host.relay_supported_by_host() is True


@pytest.mark.parametrize(
    ("platform_name", "machine"),
    [("darwin", "arm64"), ("darwin", "x86_64"), ("linux", "riscv64"), ("win32", "AMD64")],
)
def test_unsupported_hosts(
    monkeypatch: pytest.MonkeyPatch, platform_name: str, machine: str
) -> None:
    monkeypatch.setattr(relay_host.sys, "platform", platform_name)
    monkeypatch.setattr(relay_host.platform, "machine", lambda: machine)
    assert relay_host.host_relay_target() is None
    assert relay_host.host_elf_machine() is None
    assert relay_host.relay_supported_by_host() is False


def test_fix_command_names_transport_off_on_an_unsupported_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(relay_host.sys, "platform", "darwin")
    assert relay_host.relay_fix_subcommand() == "off"


def test_fix_command_names_transport_on_on_a_supported_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(relay_host.sys, "platform", "linux")
    monkeypatch.setattr(relay_host.platform, "machine", lambda: "x86_64")
    assert relay_host.relay_fix_subcommand() == "on"
