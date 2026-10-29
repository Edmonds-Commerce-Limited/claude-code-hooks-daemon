"""A relay binary built for another OS or architecture is never provisioned or accepted."""

from __future__ import annotations

import hashlib
import struct
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.install import relay_deploy
from claude_code_hooks_daemon.install.relay_deploy import (
    RELAY_DEFECT_WRONG_PLATFORM,
    check_musl_toolchain,
    deploy_relay_if_configured,
    provision_relay_for_install,
    relay_binary_defect,
)
from claude_code_hooks_daemon.utils import relay_host

X86_64 = 62
AARCH64 = 183


def _elf(machine: int, *, big_endian: bool = False) -> bytes:
    """A minimal 64-bit ELF header carrying ``machine`` in e_machine."""
    data = 2 if big_endian else 1
    ident = b"\x7fELF" + bytes([2, data, 1]) + b"\x00" * 9
    fmt = ">HH" if big_endian else "<HH"
    return ident + struct.pack(fmt, 2, machine) + b"\x00" * 200


def _write(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    path.chmod(0o755)
    return path


def _host(monkeypatch: pytest.MonkeyPatch, platform_name: str, machine: str) -> None:
    monkeypatch.setattr(relay_host.sys, "platform", platform_name)
    monkeypatch.setattr(relay_host.platform, "machine", lambda: machine)


def _transport(source: str) -> TransportConfig:
    return TransportConfig.model_validate({"relay_source": source})


class TestRelayBinaryDefectPlatform:
    def test_matching_elf_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _host(monkeypatch, "linux", "x86_64")
        assert relay_binary_defect(_write(tmp_path / "r", _elf(X86_64))) is None

    def test_wrong_arch_elf_is_a_defect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _host(monkeypatch, "linux", "aarch64")
        defect = relay_binary_defect(_write(tmp_path / "r", _elf(X86_64)))
        assert defect == RELAY_DEFECT_WRONG_PLATFORM

    def test_aarch64_elf_on_x86_64_is_a_defect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _host(monkeypatch, "linux", "x86_64")
        assert relay_binary_defect(_write(tmp_path / "r", _elf(AARCH64))) == (
            RELAY_DEFECT_WRONG_PLATFORM
        )

    def test_big_endian_header_is_read_with_its_own_endianness(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _host(monkeypatch, "linux", "x86_64")
        assert relay_binary_defect(_write(tmp_path / "r", _elf(X86_64, big_endian=True))) is None

    def test_any_elf_is_a_defect_on_a_non_linux_host(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _host(monkeypatch, "darwin", "arm64")
        assert relay_binary_defect(_write(tmp_path / "r", _elf(X86_64))) == (
            RELAY_DEFECT_WRONG_PLATFORM
        )

    def test_script_is_accepted_on_a_non_linux_host(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _host(monkeypatch, "darwin", "arm64")
        assert relay_binary_defect(_write(tmp_path / "r", b"#!/bin/sh\nexit 0\n")) is None

    def test_zero_filled_elf_stub_is_still_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _host(monkeypatch, "linux", "aarch64")
        assert relay_binary_defect(_write(tmp_path / "r", b"\x7fELF" + b"\x00" * 64)) is None

    def test_defect_text_names_the_cause(self) -> None:
        assert "another OS or architecture" in RELAY_DEFECT_WRONG_PLATFORM


def _toolchain_run(target_listed: str) -> relay_deploy.RunFn:
    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, stdout=target_listed, stderr="")

    return run


class TestCheckMuslToolchainTarget:
    def test_probes_the_requested_target(self) -> None:
        run = _toolchain_run("aarch64-unknown-linux-musl\n")
        assert check_musl_toolchain(run_fn=run, target="aarch64-unknown-linux-musl") is True
        assert check_musl_toolchain(run_fn=run) is False


class TestDeployOnUnsupportedHost:
    def test_auto_neither_builds_nor_downloads(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _host(monkeypatch, "darwin", "arm64")
        fetched: list[str] = []

        def fetch(url: str) -> bytes:
            fetched.append(url)
            return b""

        result = deploy_relay_if_configured(
            tmp_path,
            tmp_path,
            _transport("auto"),
            version_tag="v1.0.0",
            fetch_fn=fetch,
            run_fn=_toolchain_run("x86_64-unknown-linux-musl\n"),
        )
        assert result.deployed is False
        assert fetched == []
        assert any("transport off" in m for m in result.messages)

    @pytest.mark.parametrize("source", ["build", "download"])
    def test_explicit_sources_are_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
    ) -> None:
        _host(monkeypatch, "darwin", "x86_64")
        result = deploy_relay_if_configured(
            tmp_path,
            tmp_path,
            _transport(source),
            version_tag="v1.0.0",
            fetch_fn=lambda url: b"",
        )
        assert result.deployed is False
        assert not (tmp_path / "untracked" / "bin" / "hooks-relay").exists()


class TestDeployOnAarch64:
    def test_auto_never_downloads_the_x86_64_asset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _host(monkeypatch, "linux", "aarch64")
        fetched: list[str] = []

        def fetch(url: str) -> bytes:
            fetched.append(url)
            return b""

        result = deploy_relay_if_configured(
            tmp_path,
            tmp_path,
            _transport("auto"),
            version_tag="v1.0.0",
            fetch_fn=fetch,
            run_fn=_toolchain_run("x86_64-unknown-linux-musl\n"),
        )
        assert result.deployed is False
        assert fetched == []
        assert any("aarch64-unknown-linux-musl" in m for m in result.messages)

    def test_build_passes_the_host_target_and_reads_its_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _host(monkeypatch, "linux", "aarch64")
        daemon = tmp_path / "daemon"
        (daemon / "relay").mkdir(parents=True)
        (daemon / "relay" / "build.sh").write_text("#!/bin/bash\n")
        out = daemon / "untracked" / "relay-build"
        out.mkdir(parents=True)
        _write(out / "hooks-relay-aarch64-unknown-linux-musl", _elf(AARCH64))
        seen: list[str] = []

        def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            env = kwargs.get("env")
            if isinstance(env, dict) and "RELAY_TARGET" in env:
                seen.append(env["RELAY_TARGET"])
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(
                cmd, 0, stdout="aarch64-unknown-linux-musl\n", stderr=""
            )

        project = tmp_path / "project"
        project.mkdir()
        result = deploy_relay_if_configured(
            daemon,
            project,
            _transport("auto"),
            version_tag="v1.0.0",
            fetch_fn=lambda url: b"",
            run_fn=run,
        )
        assert result.deployed is True
        assert seen == ["aarch64-unknown-linux-musl"]


class TestWrongArchNeverLands:
    def test_downloaded_wrong_arch_binary_is_removed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _host(monkeypatch, "linux", "x86_64")
        payload = _elf(AARCH64)
        sums = f"{hashlib.sha256(payload).hexdigest()}  {relay_deploy.RELAY_ASSET_NAME}\n"

        def fetch(url: str) -> bytes:
            return sums.encode() if url.endswith("SHA256SUMS") else payload

        result = deploy_relay_if_configured(
            tmp_path,
            tmp_path,
            _transport("download"),
            version_tag="v1.0.0",
            fetch_fn=fetch,
        )
        assert result.deployed is False
        assert any("another OS or architecture" in m for m in result.messages)
        assert not (tmp_path / "untracked" / "bin" / "hooks-relay").exists()


class TestProvisionBannerOnUnsupportedHost:
    def test_banner_points_at_transport_off(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _host(monkeypatch, "darwin", "arm64")
        result = provision_relay_for_install(
            tmp_path,
            tmp_path,
            TransportConfig.model_validate({"relay_enabled": True, "relay_source": "auto"}),
            version_tag="v1.0.0",
            fetch_fn=lambda url: b"",
        )
        assert result.status == "failed"
        text = "\n".join(result.lines)
        assert "transport off" in text
        assert "rustup target add" not in text
