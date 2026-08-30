"""Tests for relay binary provisioning (Plan 00290 Phase 5, Tasks 5.1/5.2).

Both routes must be fully testable without a real toolchain or real network
access — every subprocess/fetch touchpoint is dependency-injected.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.install.relay_deploy import (
    RELAY_ASSET_NAME,
    SHA256SUMS_ASSET_NAME,
    RelayDeployResult,
    check_musl_toolchain,
    deploy_relay_from_build,
    deploy_relay_from_download,
    deploy_relay_if_configured,
    read_deployed_route,
    resolve_relay_binary_path,
)


def _fake_process(
    returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_resolve_relay_binary_path_default(tmp_path: Path) -> None:
    path = resolve_relay_binary_path(tmp_path, TransportConfig())
    assert path.name == "hooks-relay"
    assert path.parent.name == "bin"


def test_resolve_relay_binary_path_override(tmp_path: Path) -> None:
    override = tmp_path / "custom" / "relay-bin"
    path = resolve_relay_binary_path(tmp_path, TransportConfig(relay_binary=str(override)))
    assert path == override


class TestRouteMarker:
    def test_absent_marker_returns_none(self, tmp_path: Path) -> None:
        assert read_deployed_route(tmp_path / "hooks-relay") is None

    def test_marker_round_trips(self, tmp_path: Path) -> None:
        binary = tmp_path / "hooks-relay"
        binary.write_bytes(b"x")
        (tmp_path / "hooks-relay.route").write_text("build\n")
        assert read_deployed_route(binary) == "build"


class TestCheckMuslToolchain:
    def test_false_when_rustc_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setenv("HOME", str(tmp_path / "no-cargo-here"))
        assert check_musl_toolchain(run_fn=lambda *a, **k: _fake_process(0)) is False

    def test_true_when_target_listed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rustc")

        def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            return _fake_process(0, stdout="x86_64-unknown-linux-musl\nother-target\n")

        assert check_musl_toolchain(run_fn=fake_run) is True

    def test_false_when_target_not_listed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rustc")

        def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            return _fake_process(0, stdout="aarch64-unknown-linux-musl\n")

        assert check_musl_toolchain(run_fn=fake_run) is False

    def test_false_on_subprocess_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rustc")

        def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            raise OSError("no such file")

        assert check_musl_toolchain(run_fn=fake_run) is False


class TestDeployRelayFromBuild:
    def test_missing_build_script(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = deploy_relay_from_build(daemon_dir, project_root, TransportConfig())

        assert result.deployed is False
        assert result.route == "build"
        assert "not found" in result.messages[0]

    def test_build_script_nonzero_exit(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        (daemon_dir / "relay").mkdir(parents=True)
        (daemon_dir / "relay" / "build.sh").write_text("#!/bin/bash\nexit 1\n")
        project_root = tmp_path / "project"
        project_root.mkdir()

        def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            return _fake_process(1, stderr="rustc: error: something broke")

        result = deploy_relay_from_build(
            daemon_dir, project_root, TransportConfig(), run_fn=fake_run
        )

        assert result.deployed is False
        assert "exited 1" in result.messages[0]

    def test_build_output_missing_after_success(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        (daemon_dir / "relay").mkdir(parents=True)
        (daemon_dir / "relay" / "build.sh").write_text("#!/bin/bash\n")
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = deploy_relay_from_build(
            daemon_dir,
            project_root,
            TransportConfig(),
            run_fn=lambda *a, **k: _fake_process(0),
        )

        assert result.deployed is False
        assert "missing" in result.messages[0]

    def test_successful_build_deploys_and_marks_route(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        (daemon_dir / "relay").mkdir(parents=True)
        (daemon_dir / "relay" / "build.sh").write_text("#!/bin/bash\n")
        built_dir = daemon_dir / "untracked" / "relay-build"
        built_dir.mkdir(parents=True)
        (built_dir / RELAY_ASSET_NAME).write_bytes(b"pretend-static-binary")
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = deploy_relay_from_build(
            daemon_dir,
            project_root,
            TransportConfig(),
            run_fn=lambda *a, **k: _fake_process(0),
        )

        assert result.deployed is True
        assert result.route == "build"
        target = resolve_relay_binary_path(project_root, TransportConfig())
        assert target.is_file()
        assert target.read_bytes() == b"pretend-static-binary"
        assert target.stat().st_mode & 0o111  # executable
        assert read_deployed_route(target) == "build"


class TestDeployRelayFromDownload:
    def _sums(self, digest: str, name: str = RELAY_ASSET_NAME) -> bytes:
        return f"{digest}  {name}\n".encode()

    def test_fetch_failure_on_sums(self, tmp_path: Path) -> None:
        def fetch_fn(url: str) -> bytes:
            raise OSError("DNS failure")

        result = deploy_relay_from_download(
            tmp_path, TransportConfig(), version_tag="v3.57.0", fetch_fn=fetch_fn
        )

        assert result.deployed is False
        assert "DNS failure" in result.messages[0]

    def test_sums_missing_entry(self, tmp_path: Path) -> None:
        def fetch_fn(url: str) -> bytes:
            if url.endswith(SHA256SUMS_ASSET_NAME):
                return b"deadbeef  some-other-asset\n"
            raise AssertionError("binary should not be fetched")

        result = deploy_relay_from_download(
            tmp_path, TransportConfig(), version_tag="v3.57.0", fetch_fn=fetch_fn
        )

        assert result.deployed is False
        assert "no entry" in result.messages[0]

    def test_fetch_failure_on_binary(self, tmp_path: Path) -> None:
        import hashlib

        digest = hashlib.sha256(b"irrelevant").hexdigest()

        def fetch_fn(url: str) -> bytes:
            if url.endswith(SHA256SUMS_ASSET_NAME):
                return self._sums(digest)
            raise OSError("connection reset")

        result = deploy_relay_from_download(
            tmp_path, TransportConfig(), version_tag="v3.57.0", fetch_fn=fetch_fn
        )

        assert result.deployed is False
        assert "connection reset" in result.messages[0]

    def test_digest_mismatch_refuses_to_deploy(self, tmp_path: Path) -> None:
        def fetch_fn(url: str) -> bytes:
            if url.endswith(SHA256SUMS_ASSET_NAME):
                return self._sums("0" * 64)
            return b"actual-binary-bytes"

        result = deploy_relay_from_download(
            tmp_path, TransportConfig(), version_tag="v3.57.0", fetch_fn=fetch_fn
        )

        assert result.deployed is False
        assert "mismatch" in result.messages[0]
        target = resolve_relay_binary_path(tmp_path, TransportConfig())
        assert not target.exists()

    def test_digest_match_deploys_and_marks_route(self, tmp_path: Path) -> None:
        import hashlib

        content = b"a-real-static-binary"
        digest = hashlib.sha256(content).hexdigest()

        def fetch_fn(url: str) -> bytes:
            if url.endswith(SHA256SUMS_ASSET_NAME):
                return self._sums(digest)
            return content

        result = deploy_relay_from_download(
            tmp_path, TransportConfig(), version_tag="v3.57.0", fetch_fn=fetch_fn
        )

        assert result.deployed is True
        assert result.route == "download"
        target = resolve_relay_binary_path(tmp_path, TransportConfig())
        assert target.read_bytes() == content
        assert target.stat().st_mode & 0o111
        assert read_deployed_route(target) == "download"

    def test_url_targets_installed_version_tag(self, tmp_path: Path) -> None:
        seen_urls: list[str] = []

        def fetch_fn(url: str) -> bytes:
            seen_urls.append(url)
            raise OSError("stop after recording URL")

        deploy_relay_from_download(
            tmp_path, TransportConfig(), version_tag="v9.9.9", fetch_fn=fetch_fn
        )

        assert seen_urls == [
            "https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/"
            "releases/download/v9.9.9/SHA256SUMS"
        ]


class TestDeployRelayIfConfigured:
    def test_none_source_is_a_true_no_op(self, tmp_path: Path) -> None:
        result = deploy_relay_if_configured(
            tmp_path, tmp_path, TransportConfig(relay_source=None), version_tag="v1.0.0"
        )
        assert result == RelayDeployResult(False, None, ())

    def test_build_source_without_toolchain_advises_both_remedies(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setenv("HOME", str(tmp_path / "no-cargo-here"))

        result = deploy_relay_if_configured(
            tmp_path,
            tmp_path,
            TransportConfig(relay_source="build"),
            version_tag="v1.0.0",
        )

        assert result.deployed is False
        assert "rustup target add" in result.messages[0]
        assert "relay_source: download" in result.messages[0]

    def test_build_source_with_toolchain_runs_build_route(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rustc")
        daemon_dir = tmp_path / "daemon"
        (daemon_dir / "relay").mkdir(parents=True)
        (daemon_dir / "relay" / "build.sh").write_text("#!/bin/bash\n")
        built_dir = daemon_dir / "untracked" / "relay-build"
        built_dir.mkdir(parents=True)
        (built_dir / RELAY_ASSET_NAME).write_bytes(b"binary")
        project_root = tmp_path / "project"
        project_root.mkdir()

        def fake_run(*args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            call_args = args[0] if args else []
            # The toolchain probe calls rustc directly; the build step calls
            # bash relay/build.sh. Distinguish by inspecting argv[0].
            if call_args and "rustc" in str(call_args[0]):
                return _fake_process(0, stdout="x86_64-unknown-linux-musl\n")
            return _fake_process(0)

        result = deploy_relay_if_configured(
            daemon_dir,
            project_root,
            TransportConfig(relay_source="build"),
            version_tag="v1.0.0",
            run_fn=fake_run,
        )

        assert result.deployed is True
        assert result.route == "build"

    def test_download_source_uses_provided_fetch_fn(self, tmp_path: Path) -> None:
        import hashlib

        content = b"binary-bytes"
        digest = hashlib.sha256(content).hexdigest()

        def fetch_fn(url: str) -> bytes:
            if url.endswith(SHA256SUMS_ASSET_NAME):
                return f"{digest}  {RELAY_ASSET_NAME}\n".encode()
            return content

        result = deploy_relay_if_configured(
            tmp_path,
            tmp_path,
            TransportConfig(relay_source="download"),
            version_tag="v2.0.0",
            fetch_fn=fetch_fn,
        )

        assert result.deployed is True
        assert result.route == "download"

    def test_download_source_never_touches_real_network_when_mocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression guard: real urlopen must never be reachable in this test file."""

        def _fail_if_called(*args: object, **kwargs: object) -> object:
            raise AssertionError("real network fetch must never be called in unit tests")

        monkeypatch.setattr("urllib.request.urlopen", _fail_if_called)

        def fetch_fn(url: str) -> bytes:
            return b"never actually used for sums parse failure path"

        result = deploy_relay_if_configured(
            tmp_path,
            tmp_path,
            TransportConfig(relay_source="download"),
            version_tag="v1.0.0",
            fetch_fn=fetch_fn,
        )
        # Sums parse will fail (no valid entry) — deployed False, but the
        # point is real urlopen was never invoked.
        assert result.deployed is False
