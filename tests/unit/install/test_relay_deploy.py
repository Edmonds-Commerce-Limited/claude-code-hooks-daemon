"""Tests for relay binary provisioning (Plan 00290 Phase 5, Tasks 5.1/5.2).

Both routes must be fully testable without a real toolchain or real network
access — every subprocess/fetch touchpoint is dependency-injected.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

import pytest

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.install import relay_deploy
from claude_code_hooks_daemon.install.relay_deploy import (
    RELAY_ASSET_NAME,
    RELAY_PROVISION_FAILED_EXIT_CODE,
    SHA256SUMS_ASSET_NAME,
    RelayDeployResult,
    check_musl_toolchain,
    deploy_relay_from_build,
    deploy_relay_from_download,
    deploy_relay_if_configured,
    main,
    missing_configured_relay_binary,
    provision_relay_for_install,
    read_deployed_digest,
    read_deployed_route,
    relay_binary_missing_warning,
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


class TestDigestMarker:
    """Task 2.4 (Plan 00295): the digest deploy_relay_from_download already
    verifies against the release manifest is recorded alongside the
    `.route` marker, so transport_probe can report "verified" without a
    shipped `relay/SHA256SUMS.released` (which nothing populates today)."""

    def test_absent_marker_returns_none(self, tmp_path: Path) -> None:
        assert read_deployed_digest(tmp_path / "hooks-relay") is None

    def test_marker_round_trips(self, tmp_path: Path) -> None:
        binary = tmp_path / "hooks-relay"
        binary.write_bytes(b"x")
        (tmp_path / "hooks-relay.sha256").write_text("deadbeef" * 8 + "\n")
        assert read_deployed_digest(binary) == "deadbeef" * 8


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

    def test_passes_resolved_rustc_into_build_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Task 2.3 (Plan 00295): deploy_relay_from_build must resolve RUSTC
        the same way check_musl_toolchain does (shutil.which("rustc") first,
        falling back to ~/.cargo/bin/rustc) and pass it into the build
        subprocess's env -- otherwise build.sh's own default
        ($HOME/.cargo/bin/rustc) can silently diverge from the toolchain the
        pre-flight probe actually verified.
        """
        monkeypatch.setattr("shutil.which", lambda name: "/opt/rust/bin/rustc")
        daemon_dir = tmp_path / "daemon"
        (daemon_dir / "relay").mkdir(parents=True)
        (daemon_dir / "relay" / "build.sh").write_text("#!/bin/bash\n")
        built_dir = daemon_dir / "untracked" / "relay-build"
        built_dir.mkdir(parents=True)
        (built_dir / RELAY_ASSET_NAME).write_bytes(b"pretend-static-binary")
        project_root = tmp_path / "project"
        project_root.mkdir()

        captured_env: dict[str, str] = {}

        def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            env = kwargs["env"]
            assert isinstance(env, dict)
            captured_env.update(env)
            return _fake_process(0)

        deploy_relay_from_build(daemon_dir, project_root, TransportConfig(), run_fn=fake_run)

        assert captured_env["RUSTC"] == "/opt/rust/bin/rustc"

    def test_falls_back_to_cargo_home_rustc_when_not_on_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Task 2.3 (Plan 00295): matches check_musl_toolchain's own fallback
        when rustc is not on PATH at all."""
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        daemon_dir = tmp_path / "daemon"
        (daemon_dir / "relay").mkdir(parents=True)
        (daemon_dir / "relay" / "build.sh").write_text("#!/bin/bash\n")
        built_dir = daemon_dir / "untracked" / "relay-build"
        built_dir.mkdir(parents=True)
        (built_dir / RELAY_ASSET_NAME).write_bytes(b"pretend-static-binary")
        project_root = tmp_path / "project"
        project_root.mkdir()

        captured_env: dict[str, str] = {}

        def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            env = kwargs["env"]
            assert isinstance(env, dict)
            captured_env.update(env)
            return _fake_process(0)

        deploy_relay_from_build(daemon_dir, project_root, TransportConfig(), run_fn=fake_run)

        assert captured_env["RUSTC"] == str(tmp_path / "home" / ".cargo" / "bin" / "rustc")


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
        assert read_deployed_digest(target) == digest

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


class TestMissingConfiguredRelayBinary:
    """A configured relay whose binary is absent or not executable is reported."""

    def _config(self, binary: Path, *, enabled: bool = True) -> TransportConfig:
        return TransportConfig(relay_enabled=enabled, relay_binary=str(binary))

    def test_disabled_relay_is_never_reported(self, tmp_path: Path) -> None:
        binary = tmp_path / "hooks-relay"
        assert (
            missing_configured_relay_binary(tmp_path, self._config(binary, enabled=False)) is None
        )

    def test_absent_binary_is_reported_with_its_path(self, tmp_path: Path) -> None:
        binary = tmp_path / "hooks-relay"
        assert missing_configured_relay_binary(tmp_path, self._config(binary)) == binary

    def test_non_executable_binary_is_reported(self, tmp_path: Path) -> None:
        binary = tmp_path / "hooks-relay"
        binary.write_bytes(b"x")
        binary.chmod(0o644)
        assert missing_configured_relay_binary(tmp_path, self._config(binary)) == binary

    def test_directory_at_binary_path_is_reported(self, tmp_path: Path) -> None:
        binary = tmp_path / "hooks-relay"
        binary.mkdir()
        assert missing_configured_relay_binary(tmp_path, self._config(binary)) == binary

    def test_executable_binary_is_silent(self, tmp_path: Path) -> None:
        binary = tmp_path / "hooks-relay"
        binary.write_bytes(b"x")
        binary.chmod(0o755)
        assert missing_configured_relay_binary(tmp_path, self._config(binary)) is None


class TestRelayBinaryMissingWarning:
    def test_names_path_fallback_and_fix(self, tmp_path: Path) -> None:
        binary = tmp_path / "hooks-relay"
        line = relay_binary_missing_warning(binary, "bin/hooks-daemon transport on")
        assert str(binary) in line
        assert "fallback" in line
        assert line.endswith("Fix: bin/hooks-daemon transport on")
        assert "\n" not in line


_MUSL_TARGETS = "x86_64-unknown-linux-musl\n"


def _good_fetch(content: bytes = b"downloaded-binary") -> relay_deploy.FetchFn:
    import hashlib

    digest = hashlib.sha256(content).hexdigest()

    def fetch_fn(url: str) -> bytes:
        if url.endswith(SHA256SUMS_ASSET_NAME):
            return f"{digest}  {RELAY_ASSET_NAME}\n".encode()
        return content

    return fetch_fn


def _failing_fetch(url: str) -> bytes:
    raise OSError("network is unreachable")


def _daemon_dir_with_build_output(tmp_path: Path) -> Path:
    daemon_dir = tmp_path / "daemon"
    (daemon_dir / "relay").mkdir(parents=True)
    (daemon_dir / "relay" / "build.sh").write_text("#!/bin/bash\n")
    built_dir = daemon_dir / "untracked" / "relay-build"
    built_dir.mkdir(parents=True)
    (built_dir / RELAY_ASSET_NAME).write_bytes(b"built-binary")
    return daemon_dir


def _toolchain_run(build_returncode: int = 0) -> relay_deploy.RunFn:
    def fake_run(*args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        argv = args[0] if args else []
        if argv and "rustc" in str(argv[0]):
            return _fake_process(0, stdout=_MUSL_TARGETS)
        return _fake_process(build_returncode, stderr="boom: linker not found")

    return fake_run


class TestAutoRelaySource:
    """relay_source: auto builds when a musl toolchain exists, else downloads."""

    def test_auto_is_a_valid_source(self) -> None:
        assert TransportConfig(relay_source="auto").relay_source == "auto"

    def test_toolchain_present_builds_and_never_fetches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rustc")
        daemon_dir = _daemon_dir_with_build_output(tmp_path)
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = deploy_relay_if_configured(
            daemon_dir,
            project_root,
            TransportConfig(relay_source="auto"),
            version_tag="v1.0.0",
            fetch_fn=_failing_fetch,
            run_fn=_toolchain_run(),
        )

        assert result.deployed is True
        assert result.route == "build"

    def test_no_toolchain_downloads_and_reports_why_build_was_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setenv("HOME", str(tmp_path / "no-cargo-here"))

        result = deploy_relay_if_configured(
            tmp_path,
            tmp_path,
            TransportConfig(relay_source="auto"),
            version_tag="v1.0.0",
            fetch_fn=_good_fetch(),
        )

        assert result.deployed is True
        assert result.route == "download"
        assert any("musl" in message for message in result.messages)

    def test_build_failure_then_download_success_keeps_both_messages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rustc")
        daemon_dir = _daemon_dir_with_build_output(tmp_path)
        project_root = tmp_path / "project"
        project_root.mkdir()

        result = deploy_relay_if_configured(
            daemon_dir,
            project_root,
            TransportConfig(relay_source="auto"),
            version_tag="v1.0.0",
            fetch_fn=_good_fetch(),
            run_fn=_toolchain_run(build_returncode=1),
        )

        assert result.deployed is True
        assert result.route == "download"
        assert any("relay build exited 1" in message for message in result.messages)
        assert any("Downloaded" in message for message in result.messages)

    def test_both_routes_failing_reports_both_reasons(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setenv("HOME", str(tmp_path / "no-cargo-here"))

        result = deploy_relay_if_configured(
            tmp_path,
            tmp_path,
            TransportConfig(relay_source="auto"),
            version_tag="v1.0.0",
            fetch_fn=_failing_fetch,
        )

        assert result.deployed is False
        joined = "\n".join(result.messages)
        assert "musl" in joined
        assert "network is unreachable" in joined


class TestProvisionRelayForInstall:
    """The install/upgrade entry point: loud on failure, silent no-op when disabled."""

    def _transport(
        self,
        tmp_path: Path,
        *,
        relay_enabled: bool,
        relay_source: Literal["build", "download", "auto"] | None,
    ) -> TransportConfig:
        return TransportConfig(
            relay_enabled=relay_enabled,
            relay_source=relay_source,
            relay_binary=str(tmp_path / "bin" / "hooks-relay"),
        )

    def test_disabled_does_nothing(self, tmp_path: Path) -> None:
        calls: list[str] = []

        def fetch_fn(url: str) -> bytes:
            calls.append(url)
            return b""

        def run_fn(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append("run")
            return _fake_process(0)

        result = provision_relay_for_install(
            tmp_path,
            tmp_path,
            self._transport(tmp_path, relay_enabled=False, relay_source="auto"),
            version_tag="v1.0.0",
            fetch_fn=fetch_fn,
            run_fn=run_fn,
        )

        assert result.status == "disabled"
        assert len(result.lines) == 1
        assert calls == []
        assert not (tmp_path / "bin" / "hooks-relay").exists()

    def test_enabled_with_download_provisions(self, tmp_path: Path) -> None:
        result = provision_relay_for_install(
            tmp_path,
            tmp_path,
            self._transport(tmp_path, relay_enabled=True, relay_source="download"),
            version_tag="v1.0.0",
            fetch_fn=_good_fetch(),
        )

        assert result.status == "provisioned"
        assert (tmp_path / "bin" / "hooks-relay").is_file()

    def test_enabled_auto_with_build_present_provisions_by_build(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/rustc")
        daemon_dir = _daemon_dir_with_build_output(tmp_path)

        result = provision_relay_for_install(
            daemon_dir,
            tmp_path,
            self._transport(tmp_path, relay_enabled=True, relay_source="auto"),
            version_tag="v1.0.0",
            fetch_fn=_failing_fetch,
            run_fn=_toolchain_run(),
        )

        assert result.status == "provisioned"
        assert read_deployed_route(tmp_path / "bin" / "hooks-relay") == "build"

    def test_enabled_auto_without_build_downloads(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setenv("HOME", str(tmp_path / "no-cargo-here"))

        result = provision_relay_for_install(
            tmp_path,
            tmp_path,
            self._transport(tmp_path, relay_enabled=True, relay_source="auto"),
            version_tag="v1.0.0",
            fetch_fn=_good_fetch(),
        )

        assert result.status == "provisioned"
        assert read_deployed_route(tmp_path / "bin" / "hooks-relay") == "download"

    def test_both_routes_failing_is_loud_and_names_path_reasons_and_fix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setenv("HOME", str(tmp_path / "no-cargo-here"))

        result = provision_relay_for_install(
            tmp_path,
            tmp_path,
            self._transport(tmp_path, relay_enabled=True, relay_source="auto"),
            version_tag="v1.0.0",
            fetch_fn=_failing_fetch,
        )

        assert result.status == "failed"
        text = "\n".join(result.lines)
        assert str(tmp_path / "bin" / "hooks-relay") in text
        assert "network is unreachable" in text
        assert "musl" in text
        assert "rustup target add x86_64-unknown-linux-musl" in text
        assert str(tmp_path / "bin" / "hooks-daemon") in text
        assert "transport on" in text
        assert "bash" in text

    def test_enabled_without_source_and_without_binary_fails_naming_fix(
        self, tmp_path: Path
    ) -> None:
        result = provision_relay_for_install(
            tmp_path,
            tmp_path,
            self._transport(tmp_path, relay_enabled=True, relay_source=None),
            version_tag="v1.0.0",
            fetch_fn=_failing_fetch,
        )

        assert result.status == "failed"
        text = "\n".join(result.lines)
        assert str(tmp_path / "bin" / "hooks-relay") in text
        assert "relay_source: auto" in text

    def test_enabled_without_source_but_binary_present_is_provisioned(self, tmp_path: Path) -> None:
        binary = tmp_path / "bin" / "hooks-relay"
        binary.parent.mkdir()
        binary.write_bytes(b"x")
        binary.chmod(0o755)

        result = provision_relay_for_install(
            tmp_path,
            tmp_path,
            self._transport(tmp_path, relay_enabled=True, relay_source=None),
            version_tag="v1.0.0",
            fetch_fn=_failing_fetch,
        )

        assert result.status == "provisioned"


class TestProvisionMainCli:
    """``python -m ...relay_deploy``: distinct exit codes per outcome."""

    def _write_config(self, project_root: Path, transport_yaml: str) -> None:
        config_dir = project_root / ".claude"
        config_dir.mkdir(parents=True)
        (config_dir / "hooks-daemon.yaml").write_text(
            f'version: "1.0"\ndaemon:\n  transport:\n{transport_yaml}'
        )

    def _argv(self, daemon_dir: Path, project_root: Path) -> list[str]:
        return [
            "--daemon-dir",
            str(daemon_dir),
            "--project-root",
            str(project_root),
            "--version-tag",
            "v1.0.0",
        ]

    def test_exit_codes_are_distinct(self) -> None:
        assert RELAY_PROVISION_FAILED_EXIT_CODE not in (0, 2)

    def test_disabled_exits_zero(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        self._write_config(tmp_path, "    relay_enabled: false\n    relay_source: auto\n")

        assert main(self._argv(tmp_path, tmp_path)) == 0
        assert "disabled" in capsys.readouterr().out.lower()

    def test_provisioned_exits_zero(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        binary = tmp_path / "hooks-relay"
        self._write_config(
            tmp_path,
            f"    relay_enabled: true\n    relay_source: download\n    relay_binary: {binary}\n",
        )
        monkeypatch.setattr(relay_deploy, "_default_fetch", _good_fetch())

        assert main(self._argv(tmp_path, tmp_path)) == 0
        assert binary.is_file()
        assert "Downloaded" in capsys.readouterr().out

    def test_failure_exits_with_dedicated_code_and_prints_banner(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        binary = tmp_path / "hooks-relay"
        self._write_config(
            tmp_path,
            f"    relay_enabled: true\n    relay_source: download\n    relay_binary: {binary}\n",
        )
        monkeypatch.setattr(relay_deploy, "_default_fetch", _failing_fetch)

        assert main(self._argv(tmp_path, tmp_path)) == RELAY_PROVISION_FAILED_EXIT_CODE
        out = capsys.readouterr().out
        assert str(binary) in out
        assert "network is unreachable" in out

    def test_missing_required_argument_exits_two(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            main(["--daemon-dir", "x"])
        assert excinfo.value.code == 2
