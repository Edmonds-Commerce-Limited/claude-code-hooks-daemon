"""The relay download route selects its release asset by host architecture.

Plan 00572 Task 3.2: releases publish a relay for x86_64 and aarch64, so a
host downloads the asset built for its own machine, and a machine with no
published asset is refused before anything is fetched.
"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Callable
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.install.relay_deploy import (
    PUBLISHED_RELAY_TARGETS,
    deploy_relay_from_download,
    deploy_relay_if_configured,
    provision_relay_for_install,
    relay_asset_name,
    relay_asset_name_for_target,
    resolve_relay_binary_path,
)
from claude_code_hooks_daemon.utils import relay_host
from claude_code_hooks_daemon.utils.relay_host import relay_target_for_machine

X86_64_TRIPLE = "x86_64-unknown-linux-musl"
AARCH64_TRIPLE = "aarch64-unknown-linux-musl"
ELF_X86_64 = 62
ELF_AARCH64 = 183


def _elf(machine: int) -> bytes:
    ident = b"\x7fELF" + bytes([2, 1, 1]) + b"\x00" * 9
    return ident + struct.pack("<HH", 2, machine) + b"\x00" * 200


def _host(monkeypatch: pytest.MonkeyPatch, machine: str) -> None:
    monkeypatch.setattr(relay_host.sys, "platform", "linux")
    monkeypatch.setattr(relay_host.platform, "machine", lambda: machine)


def _release(asset: str, payload: bytes, fetched: list[str]) -> Callable[[str], bytes]:
    sums = f"{hashlib.sha256(payload).hexdigest()}  {asset}\n".encode()

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return sums if url.endswith("/SHA256SUMS") else payload

    return fetch


class TestRelayTargetForMachine:
    @pytest.mark.parametrize("machine", ["x86_64", "amd64", "AMD64"])
    def test_x86_64_spellings(self, machine: str) -> None:
        assert relay_target_for_machine(machine) == X86_64_TRIPLE

    @pytest.mark.parametrize("machine", ["aarch64", "arm64", "ARM64"])
    def test_aarch64_spellings(self, machine: str) -> None:
        assert relay_target_for_machine(machine) == AARCH64_TRIPLE

    @pytest.mark.parametrize("machine", ["riscv64", "armv7l", "i686", ""])
    def test_other_machines_have_no_target(self, machine: str) -> None:
        assert relay_target_for_machine(machine) is None


class TestRelayAssetName:
    def test_both_architectures_are_published(self) -> None:
        assert set(PUBLISHED_RELAY_TARGETS) == {X86_64_TRIPLE, AARCH64_TRIPLE}

    def test_asset_name_for_target(self) -> None:
        assert relay_asset_name_for_target(AARCH64_TRIPLE) == f"hooks-relay-{AARCH64_TRIPLE}"

    @pytest.mark.parametrize(
        ("machine", "asset"),
        [
            ("x86_64", f"hooks-relay-{X86_64_TRIPLE}"),
            ("amd64", f"hooks-relay-{X86_64_TRIPLE}"),
            ("aarch64", f"hooks-relay-{AARCH64_TRIPLE}"),
            ("arm64", f"hooks-relay-{AARCH64_TRIPLE}"),
        ],
    )
    def test_named_machine(self, machine: str, asset: str) -> None:
        assert relay_asset_name(machine) == asset

    def test_unsupported_machine_has_no_asset(self) -> None:
        assert relay_asset_name("riscv64") is None

    def test_defaults_to_the_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _host(monkeypatch, "aarch64")
        assert relay_asset_name() == f"hooks-relay-{AARCH64_TRIPLE}"

    def test_non_linux_host_has_no_asset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(relay_host.sys, "platform", "darwin")
        monkeypatch.setattr(relay_host.platform, "machine", lambda: "arm64")
        assert relay_asset_name() is None


class TestDownloadSelectsByArchitecture:
    @pytest.mark.parametrize(
        ("machine", "triple", "elf"),
        [("aarch64", AARCH64_TRIPLE, ELF_AARCH64), ("x86_64", X86_64_TRIPLE, ELF_X86_64)],
    )
    def test_fetches_and_deploys_the_host_asset(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        machine: str,
        triple: str,
        elf: int,
    ) -> None:
        _host(monkeypatch, machine)
        fetched: list[str] = []
        asset = f"hooks-relay-{triple}"
        result = deploy_relay_from_download(
            tmp_path,
            TransportConfig(),
            version_tag="v9.9.9",
            fetch_fn=_release(asset, _elf(elf), fetched),
        )
        assert result.deployed is True, result.messages
        assert fetched[-1].endswith(f"/v9.9.9/{asset}")
        deployed = resolve_relay_binary_path(tmp_path, TransportConfig())
        assert deployed.read_bytes() == _elf(elf)

    def test_an_aarch64_host_never_fetches_the_x86_64_asset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _host(monkeypatch, "aarch64")
        fetched: list[str] = []
        result = deploy_relay_from_download(
            tmp_path,
            TransportConfig(),
            version_tag="v9.9.9",
            fetch_fn=_release(f"hooks-relay-{X86_64_TRIPLE}", _elf(ELF_X86_64), fetched),
        )
        assert result.deployed is False
        assert not any(X86_64_TRIPLE in url for url in fetched)
        assert any(f"hooks-relay-{AARCH64_TRIPLE}" in m for m in result.messages)

    def test_an_unsupported_machine_is_refused_before_any_fetch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _host(monkeypatch, "riscv64")
        fetched: list[str] = []
        result = deploy_relay_from_download(
            tmp_path,
            TransportConfig(),
            version_tag="v9.9.9",
            fetch_fn=_release("x", b"", fetched),
        )
        assert result.deployed is False
        assert fetched == []
        assert any("riscv64" in m for m in result.messages)

    def test_auto_on_aarch64_without_a_toolchain_downloads_the_aarch64_asset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _host(monkeypatch, "aarch64")
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setenv("HOME", str(tmp_path / "no-cargo-here"))
        fetched: list[str] = []
        asset = f"hooks-relay-{AARCH64_TRIPLE}"
        result = deploy_relay_if_configured(
            tmp_path,
            tmp_path,
            TransportConfig.model_validate({"relay_source": "auto"}),
            version_tag="v9.9.9",
            fetch_fn=_release(asset, _elf(ELF_AARCH64), fetched),
        )
        assert result.deployed is True, result.messages
        assert result.route == "download"
        assert fetched[-1].endswith(f"/{asset}")


class TestBannerOnAarch64:
    def test_offers_the_download_fix(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _host(monkeypatch, "aarch64")
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setenv("HOME", str(tmp_path / "no-cargo-here"))

        def fail(url: str) -> bytes:
            raise OSError("offline")

        result = provision_relay_for_install(
            tmp_path,
            tmp_path,
            TransportConfig.model_validate({"relay_enabled": True, "relay_source": "auto"}),
            version_tag="v9.9.9",
            fetch_fn=fail,
        )
        assert result.status == "failed"
        assert "network access to the GitHub release" in "\n".join(result.lines)
