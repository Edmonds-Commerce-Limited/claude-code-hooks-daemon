"""Relay binary provisioning: build-from-source and download routes.

Plan 00290 Phase 5's owner ruling (recorded verbatim in the plan) is binding:
build-from-source is the FIRST-CLASS route — preferred whenever a musl-capable
``rustc`` is present, needs nothing but the plain compiler invocation
documented in ``relay/build.sh`` (no cargo, no crates) — and the precompiled
GitHub-release download is the convenience option. Source ships in the
package either way. The route is chosen by
``daemon.transport.relay_source: build|download|auto`` (default ``auto``, which
builds when a musl toolchain is present and otherwise downloads); an explicit
``null`` runs neither route, leaving the binary to be supplied by hand.

See ``CLAUDE/Plan/00290-rust-socket-relay-forwarder/DESIGN-socket-relay.md``
§3.2/§6 for the distribution design this module implements.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess  # nosec B404 - subprocess used only for the trusted, hardcoded rustc build invocation (no shell, no user input)
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.daemon.paths import get_untracked_dir
from claude_code_hooks_daemon.install.forwarder_generator import load_transport_config

#: The one relay target this project builds/ships today (design §3.2).
RELAY_TARGET: str = "x86_64-unknown-linux-musl"
RELAY_ASSET_NAME: str = f"hooks-relay-{RELAY_TARGET}"
SHA256SUMS_ASSET_NAME: str = "SHA256SUMS"

#: GitHub release asset base — a version tag (``v3.57.0``) and an asset name
#: joined onto this produce the download URL for that asset.
_GITHUB_RELEASE_BASE: str = (
    "https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/releases/download"
)

#: Sidecar file recording which route deployed the binary currently on disk —
#: read back by the transport probe (design §6.3) so an operator/CI can see
#: whether "build" or "download" produced what is deployed, without having to
#: re-derive it from config (which may have changed since the deploy ran).
_ROUTE_MARKER_SUFFIX: str = ".route"

#: Sidecar file recording the sha256 digest deploy_relay_from_download
#: verified before writing the binary (Plan 00295 Task 2.4) — read back by
#: the transport probe so a downloaded relay reports "verified" without
#: depending on a shipped ``relay/SHA256SUMS.released`` release manifest,
#: which nothing in the release pipeline populates today.
_DIGEST_MARKER_SUFFIX: str = ".sha256"

_TOOLCHAIN_PROBE_TIMEOUT_SECONDS = 10
_BUILD_TIMEOUT_SECONDS = 300
_FETCH_TIMEOUT_SECONDS = 30

#: Injectable fetch signature: given a URL, return the response body bytes.
#: Raises on any failure (network, HTTP status, timeout) — the caller decides
#: how to report that, never a silent empty result.
FetchFn = Callable[[str], bytes]

#: Injectable subprocess-run signature, matching ``subprocess.run``'s shape
#: closely enough for this module's two call sites (toolchain probe, build).
RunFn = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class RelayDeployResult:
    """Outcome of a single relay-provisioning attempt.

    Attributes:
        deployed: True only when a binary was actually written to disk.
        route: ``"build"``/``"download"`` when ``deployed`` is True; the
            attempted route (for a failed attempt) or ``None`` (nothing was
            configured/attempted) otherwise.
        messages: Human-readable advisories — always non-fatal. This module
            never raises for an expected failure mode (missing toolchain,
            fetch error, digest mismatch); every one of those is reported
            here and returned with ``deployed=False``.
    """

    deployed: bool
    route: str | None
    messages: tuple[str, ...]


def resolve_relay_binary_path(project_root: Path, transport: TransportConfig) -> Path:
    """Where the relay binary lives for ``project_root`` (design §4).

    ``transport.relay_binary`` overrides; otherwise ``{untracked}/bin/hooks-relay``.
    """
    if transport.relay_binary:
        return Path(transport.relay_binary)
    # Plan 00290 F3 fix: NOT get_event_socket_dir(...).parent — that dir can
    # now resolve to an AF_UNIX-overflow fallback root (e.g. under
    # /run/user/{uid}), unrelated to where the relay binary actually lives.
    untracked_dir = get_untracked_dir(project_root)
    return untracked_dir / "bin" / "hooks-relay"


#: The leading bytes of a file the generated relay guard will exec: an ELF
#: executable (the musl relay) or a ``#!`` script, which the kernel runs. The
#: guard's bash test (``forwarder_generator.build_relay_guard_block``) checks
#: the same two, pinned by a test.
RELAY_RUNNABLE_MAGIC: tuple[bytes, bytes] = (b"\x7fELF", b"#!")
_MAGIC_READ_BYTES = 4

#: Why the guard will not run the relay binary (:func:`relay_binary_defect`).
RELAY_DEFECT_MISSING = "missing"
RELAY_DEFECT_NOT_A_FILE = "not a regular file"
RELAY_DEFECT_NOT_EXECUTABLE = "not executable"
RELAY_DEFECT_UNREADABLE = "unreadable"
RELAY_DEFECT_NOT_RUNNABLE = "neither an ELF executable nor a #! script"


def relay_binary_defect(binary: Path) -> str | None:
    """Why the generated relay guard would NOT run ``binary``, or None when it would.

    The one check shared by every caller that judges a relay binary: the
    SessionStart checker, ``status`` and ``transport on``'s provisioning, so
    ``transport on`` replaces a defective file instead of keeping it.
    """
    if not binary.exists():
        return RELAY_DEFECT_MISSING
    if not binary.is_file():
        return RELAY_DEFECT_NOT_A_FILE
    if not os.access(binary, os.X_OK):
        return RELAY_DEFECT_NOT_EXECUTABLE
    try:
        with binary.open("rb") as handle:
            head = handle.read(_MAGIC_READ_BYTES)
    except OSError:
        return RELAY_DEFECT_UNREADABLE
    # The guard's `read -N 4` fails on a shorter file, so this requires all four.
    if len(head) == _MAGIC_READ_BYTES and (
        head == RELAY_RUNNABLE_MAGIC[0] or head.startswith(RELAY_RUNNABLE_MAGIC[1])
    ):
        return None
    return RELAY_DEFECT_NOT_RUNNABLE


def missing_configured_relay_binary(project_root: Path, transport: TransportConfig) -> Path | None:
    """The relay binary path when the relay is configured on but unusable.

    Returns None when the relay is disabled or :func:`relay_binary_defect`
    finds nothing wrong with the binary.
    """
    if not transport.relay_enabled:
        return None
    binary = resolve_relay_binary_path(project_root, transport)
    if relay_binary_defect(binary) is None:
        return None
    return binary


def relay_binary_missing_warning(binary: Path, fix_command: str) -> str:
    """One-line warning for a configured relay whose binary is missing or cannot run."""
    return (
        f"relay is enabled but its binary is missing or cannot run: {binary} "
        f"- relay-eligible hooks run on the fallback transport. Fix: {fix_command}"
    )


def _route_marker_path(binary_path: Path) -> Path:
    return binary_path.with_name(binary_path.name + _ROUTE_MARKER_SUFFIX)


def _write_route_marker(binary_path: Path, route: str) -> None:
    _route_marker_path(binary_path).write_text(route + "\n")


def read_deployed_route(binary_path: Path) -> str | None:
    """Return the route ("build"/"download") that deployed ``binary_path``.

    ``None`` when no marker exists — the binary is absent, or predates this
    module (Phase 3/4 dogfood build has no marker; that is reported as
    "unknown", not a failure).
    """
    marker = _route_marker_path(binary_path)
    if not marker.is_file():
        return None
    text = marker.read_text().strip()
    return text or None


def _digest_marker_path(binary_path: Path) -> Path:
    return binary_path.with_name(binary_path.name + _DIGEST_MARKER_SUFFIX)


def _write_digest_marker(binary_path: Path, digest: str) -> None:
    _digest_marker_path(binary_path).write_text(digest + "\n")


def read_deployed_digest(binary_path: Path) -> str | None:
    """Return the sha256 digest verified for ``binary_path`` at deploy time.

    ``None`` when no marker exists — the binary is absent, was deployed by
    the build route (which has no external manifest to verify against), or
    predates this module (Plan 00295 Task 2.4).
    """
    marker = _digest_marker_path(binary_path)
    if not marker.is_file():
        return None
    text = marker.read_text().strip()
    return text or None


def _resolve_rustc() -> str:
    """The ``rustc`` path every relay toolchain touchpoint agrees on.

    ``shutil.which("rustc")`` (PATH) wins when present; the rustup default
    install location (``~/.cargo/bin/rustc``) is the fallback. Single source
    of truth for :func:`check_musl_toolchain`'s pre-flight probe AND
    :func:`deploy_relay_from_build`'s actual build invocation (Plan 00295
    Task 2.3) — before this helper existed the two resolved independently,
    so a ``rustc`` found via PATH could pass the probe while
    ``relay/build.sh``'s own unset-``RUSTC`` default silently built with a
    DIFFERENT (or missing) compiler at ``~/.cargo/bin/rustc``.
    """
    return shutil.which("rustc") or str(Path.home() / ".cargo" / "bin" / "rustc")


def check_musl_toolchain(*, run_fn: RunFn = subprocess.run) -> bool:
    """True when a musl-capable ``rustc`` is available (Task 5.2).

    Checked via ``rustc --print target-list`` naming :data:`RELAY_TARGET` —
    the same signal ``rustup target list`` itself derives from, and cheap
    enough to run on every install/upgrade. Does not attempt an actual
    compile (that is the build route's own job, and its own failure mode).
    """
    rustc = _resolve_rustc()
    if not (shutil.which("rustc") or Path(rustc).is_file()):
        return False
    try:
        result = run_fn(
            [rustc, "--print", "target-list"],
            capture_output=True,
            text=True,
            timeout=_TOOLCHAIN_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and RELAY_TARGET in result.stdout


def deploy_relay_from_build(
    daemon_dir: Path,
    project_root: Path,
    transport: TransportConfig,
    *,
    run_fn: RunFn = subprocess.run,
) -> RelayDeployResult:
    """Build the relay from source via ``relay/build.sh`` and deploy it.

    Args:
        daemon_dir: The daemon clone containing ``relay/build.sh`` and
            ``relay/hooks_relay.rs`` (present in every install — source ships
            in the package regardless of the chosen distribution route).
        project_root: The target project, used to resolve the deploy
            destination (:func:`resolve_relay_binary_path`).
        transport: The resolved ``daemon.transport`` config.
        run_fn: Injectable ``subprocess.run``-shaped callable — a real build
            is never exercised in unit tests.
    """
    build_script = daemon_dir / "relay" / "build.sh"
    if not build_script.is_file():
        return RelayDeployResult(
            False, "build", (f"relay build script not found at {build_script}",)
        )

    try:
        result = run_fn(
            ["bash", str(build_script)],
            env={**os.environ, "RELAY_TARGET": RELAY_TARGET, "RUSTC": _resolve_rustc()},
            capture_output=True,
            text=True,
            timeout=_BUILD_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return RelayDeployResult(False, "build", (f"relay build failed to run: {exc}",))

    if result.returncode != 0:
        stderr_tail = (result.stderr or "").strip()[-500:]
        return RelayDeployResult(
            False,
            "build",
            (f"relay build exited {result.returncode}: {stderr_tail}",),
        )

    built = daemon_dir / "untracked" / "relay-build" / RELAY_ASSET_NAME
    if not built.is_file():
        return RelayDeployResult(
            False,
            "build",
            (f"relay build reported success but output is missing: {built}",),
        )

    target = resolve_relay_binary_path(project_root, transport)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(built, target)
    target.chmod(0o755)
    _write_route_marker(target, "build")
    return RelayDeployResult(True, "build", (f"Built relay from source, deployed to {target}",))


def _release_asset_url(version_tag: str, asset_name: str) -> str:
    return f"{_GITHUB_RELEASE_BASE}/{version_tag}/{asset_name}"


def _parse_sha256sums(text: str, asset_name: str) -> str | None:
    for line in text.splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts
        if name.strip().lstrip("*") == asset_name:
            return digest.strip().lower()
    return None


def _default_fetch(url: str) -> bytes:
    """The real network fetch — never exercised in unit tests (always mocked).

    Only ``https://`` URLs are ever opened: every caller builds ``url`` from
    :data:`_GITHUB_RELEASE_BASE`, which is a hardcoded ``https://`` literal,
    so this is a defence-in-depth scheme check rather than a live code path
    -- it removes the bandit B310 finding (urlopen permitting ``file:``/
    custom schemes) by construction instead of asserting the risk away.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"refusing to fetch non-https URL: {url!r}")
    with urllib.request.urlopen(
        url, timeout=_FETCH_TIMEOUT_SECONDS
    ) as response:  # nosec B310 - scheme validated to https above
        return bytes(response.read())


def deploy_relay_from_download(
    project_root: Path,
    transport: TransportConfig,
    *,
    version_tag: str,
    fetch_fn: FetchFn,
) -> RelayDeployResult:
    """Fetch the digest-verified precompiled relay from the matching release.

    The digest is ALWAYS verified before anything is written to disk. A
    fetch failure or a digest mismatch is reported and returns
    ``deployed=False`` — never a hard failure (Task 5.1: "falling back with a
    clear advisory, never a hard fail").

    Args:
        project_root: The target project, used to resolve the deploy
            destination.
        transport: The resolved ``daemon.transport`` config.
        version_tag: The installed daemon's release tag (e.g. ``"v3.57.0"``)
            — the download always matches the version actually installed,
            never "latest".
        fetch_fn: Given a URL, returns the response body bytes or raises.
            Real network access is injected only outside unit tests.
    """
    sums_url = _release_asset_url(version_tag, SHA256SUMS_ASSET_NAME)
    try:
        sums_bytes = fetch_fn(sums_url)
    except Exception as exc:  # fetch_fn's real implementation may raise any
        # transport-layer exception (URLError, HTTPError, OSError, timeout,
        # ...); every one of them is the same "fetch failed" advisory here.
        return RelayDeployResult(False, "download", (f"failed to fetch {sums_url}: {exc}",))

    expected_digest = _parse_sha256sums(
        sums_bytes.decode("utf-8", errors="replace"), RELAY_ASSET_NAME
    )
    if expected_digest is None:
        return RelayDeployResult(
            False,
            "download",
            (f"{SHA256SUMS_ASSET_NAME} for {version_tag} has no entry for {RELAY_ASSET_NAME}",),
        )

    binary_url = _release_asset_url(version_tag, RELAY_ASSET_NAME)
    try:
        binary_bytes = fetch_fn(binary_url)
    except Exception as exc:  # see comment above — any transport failure
        return RelayDeployResult(False, "download", (f"failed to fetch {binary_url}: {exc}",))

    actual_digest = hashlib.sha256(binary_bytes).hexdigest()
    if actual_digest != expected_digest:
        return RelayDeployResult(
            False,
            "download",
            (
                f"sha256 mismatch for {RELAY_ASSET_NAME} ({version_tag}): "
                f"expected {expected_digest}, got {actual_digest} — refusing to deploy",
            ),
        )

    target = resolve_relay_binary_path(project_root, transport)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(binary_bytes)
    target.chmod(0o755)
    _write_route_marker(target, "download")
    _write_digest_marker(target, actual_digest)
    return RelayDeployResult(
        True, "download", (f"Downloaded and digest-verified relay, deployed to {target}",)
    )


def deploy_relay_if_configured(
    daemon_dir: Path,
    project_root: Path,
    transport: TransportConfig,
    *,
    version_tag: str,
    fetch_fn: FetchFn | None = None,
    run_fn: RunFn = subprocess.run,
) -> RelayDeployResult:
    """Dispatch to the configured relay-provisioning route, or do nothing.

    ``transport.relay_source`` is the single, explicit switch (Phase 5 owner
    ruling — "neither ever happens implicitly"): ``None`` (the default) is a
    genuine no-op regardless of ``relay_enabled``, so enabling the relay rung
    never itself triggers a build or a download.
    """
    if transport.relay_source is None:
        return RelayDeployResult(False, None, ())

    if transport.relay_source == "auto":
        return _deploy_auto(
            daemon_dir,
            project_root,
            transport,
            version_tag=version_tag,
            fetch_fn=fetch_fn,
            run_fn=run_fn,
        )

    if transport.relay_source == "build":
        if not check_musl_toolchain(run_fn=run_fn):
            return RelayDeployResult(
                False,
                "build",
                (
                    "relay_source: build requested but no musl-capable rustc "
                    "toolchain was found — install one "
                    "(`rustup target add x86_64-unknown-linux-musl`), or switch "
                    "to relay_source: download",
                ),
            )
        return deploy_relay_from_build(daemon_dir, project_root, transport, run_fn=run_fn)

    resolved_fetch: FetchFn = fetch_fn if fetch_fn is not None else _default_fetch
    return deploy_relay_from_download(
        project_root, transport, version_tag=version_tag, fetch_fn=resolved_fetch
    )


def _deploy_auto(
    daemon_dir: Path,
    project_root: Path,
    transport: TransportConfig,
    *,
    version_tag: str,
    fetch_fn: FetchFn | None,
    run_fn: RunFn,
) -> RelayDeployResult:
    """``relay_source: auto`` - build when a musl toolchain exists, else download.

    The build is tried first (the first-class route). When it is not possible
    or does not deploy, the digest-verified download is attempted. Messages
    from every attempt are kept, so a failed build followed by a successful
    download is still reported rather than hidden.
    """
    messages: list[str] = []
    if check_musl_toolchain(run_fn=run_fn):
        built = deploy_relay_from_build(daemon_dir, project_root, transport, run_fn=run_fn)
        if built.deployed:
            return built
        messages.extend(built.messages)
    else:
        messages.append(
            "no musl-capable rustc toolchain was found, so the relay was not built "
            "from source (`rustup target add x86_64-unknown-linux-musl` enables it)"
        )

    resolved_fetch: FetchFn = fetch_fn if fetch_fn is not None else _default_fetch
    downloaded = deploy_relay_from_download(
        project_root, transport, version_tag=version_tag, fetch_fn=resolved_fetch
    )
    return RelayDeployResult(
        downloaded.deployed, downloaded.route, (*messages, *downloaded.messages)
    )


#: Exit code of the install/upgrade CLI when the relay is enabled but could not
#: be provisioned. Distinct from 0 (disabled / provisioned) and argparse's 2.
RELAY_PROVISION_FAILED_EXIT_CODE: int = 3

ProvisionStatus = Literal["disabled", "provisioned", "failed"]


@dataclass(frozen=True)
class RelayProvisionResult:
    """Outcome of :func:`provision_relay_for_install`.

    Attributes:
        status: ``disabled`` (relay off, nothing done), ``provisioned`` (the
            binary is in place) or ``failed`` (relay on, binary not usable).
        lines: Human-readable output, ready to print. For ``failed`` it is a
            multi-line banner naming the path, every reason and the fix.
    """

    status: ProvisionStatus
    lines: tuple[str, ...]


def _failure_banner(
    binary: Path, reasons: tuple[str, ...], wrapper: Path, source_hint: bool
) -> tuple[str, ...]:
    """The loud, multi-line failure text for a relay that could not be provisioned."""
    rule = "=" * 72
    defect = relay_binary_defect(binary)
    headline = (
        f"The relay is enabled but its binary is {defect}: {binary}"
        if defect is not None
        else f"The relay is enabled but its binary could not be provisioned: {binary}"
    )
    lines = [rule, "WARNING: RELAY BINARY NOT PROVISIONED", rule, headline]
    lines.extend(f"  - {reason}" for reason in reasons)
    lines.append(
        "Effect: relay-eligible hooks run on the slower bash transport; "
        "every rule is still enforced."
    )
    lines.append("Fix, any one of:")
    if source_hint:
        lines.append("  - set daemon.transport.relay_source: auto in .claude/hooks-daemon.yaml")
    lines.extend(
        [
            "  - install a musl-capable rustc: rustup target add x86_64-unknown-linux-musl",
            "  - or allow network access to the GitHub release (digest-verified asset)",
            f"Then run: {wrapper} transport on",
            rule,
        ]
    )
    return tuple(lines)


def provision_relay_for_install(
    daemon_dir: Path,
    project_root: Path,
    transport: TransportConfig,
    *,
    version_tag: str,
    fetch_fn: FetchFn | None = None,
    run_fn: RunFn = subprocess.run,
) -> RelayProvisionResult:
    """Put the relay binary in place for an install or upgrade, loudly.

    ``relay_enabled`` false does nothing (no build, no download). With it on,
    ``relay_source`` selects the route (see :func:`deploy_relay_if_configured`);
    with no source the binary must already be executable. Any failure returns
    ``failed`` with a banner naming the path, the reasons and the fix - the
    caller decides the exit policy.
    """
    if not transport.relay_enabled:
        return RelayProvisionResult(
            "disabled", ("Relay disabled (daemon.transport.relay_enabled is false); nothing to do",)
        )

    binary = resolve_relay_binary_path(project_root, transport)
    wrapper = daemon_dir / "bin" / "hooks-daemon"

    if transport.relay_source is None:
        if missing_configured_relay_binary(project_root, transport) is None:
            return RelayProvisionResult(
                "provisioned", (f"Relay binary already in place: {binary}",)
            )
        return RelayProvisionResult(
            "failed",
            _failure_banner(
                binary,
                ("daemon.transport.relay_source is not set, so nothing builds or downloads it",),
                wrapper,
                source_hint=True,
            ),
        )

    result = deploy_relay_if_configured(
        daemon_dir,
        project_root,
        transport,
        version_tag=version_tag,
        fetch_fn=fetch_fn,
        run_fn=run_fn,
    )
    if result.deployed:
        return RelayProvisionResult("provisioned", tuple(result.messages))
    return RelayProvisionResult(
        "failed", _failure_banner(binary, result.messages, wrapper, source_hint=False)
    )


def main(argv: list[str] | None = None) -> int:
    """CLI used by the install and upgrade scripts.

    Exit codes: 0 = disabled or provisioned, 2 = bad arguments (argparse),
    :data:`RELAY_PROVISION_FAILED_EXIT_CODE` (3) = relay enabled but not provisioned.
    """
    parser = argparse.ArgumentParser(
        prog="python -m claude_code_hooks_daemon.install.relay_deploy",
        description="Provision the relay binary for an install or upgrade.",
    )
    parser.add_argument("--daemon-dir", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--version-tag", required=True)
    args = parser.parse_args(argv)

    transport = load_transport_config(args.project_root)
    result = provision_relay_for_install(
        args.daemon_dir, args.project_root, transport, version_tag=args.version_tag
    )
    for line in result.lines:
        print(line)
    return RELAY_PROVISION_FAILED_EXIT_CODE if result.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
