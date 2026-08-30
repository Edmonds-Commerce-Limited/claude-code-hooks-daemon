"""Relay binary provisioning: build-from-source and download routes.

Plan 00290 Phase 5's owner ruling (recorded verbatim in the plan) is binding:
build-from-source is the FIRST-CLASS route — preferred whenever a musl-capable
``rustc`` is present, needs nothing but the plain compiler invocation
documented in ``relay/build.sh`` (no cargo, no crates) — and the precompiled
GitHub-release download is the convenience option. Source ships in the
package either way. Both routes are explicit, deliberate config choices
(``daemon.transport.relay_source: build|download``); with the default
``null`` neither route ever runs, so relaying stays opt-in on top of an
explicit distribution choice rather than a side effect of ``relay_enabled``.

See ``CLAUDE/Plan/00290-rust-socket-relay-forwarder/DESIGN-socket-relay.md``
§3.2/§6 for the distribution design this module implements.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from claude_code_hooks_daemon.config.models import TransportConfig
from claude_code_hooks_daemon.daemon.paths import get_event_socket_dir

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
    untracked_dir = get_event_socket_dir(project_root).parent
    return untracked_dir / "bin" / "hooks-relay"


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


def check_musl_toolchain(*, run_fn: RunFn = subprocess.run) -> bool:
    """True when a musl-capable ``rustc`` is available (Task 5.2).

    Checked via ``rustc --print target-list`` naming :data:`RELAY_TARGET` —
    the same signal ``rustup target list`` itself derives from, and cheap
    enough to run on every install/upgrade. Does not attempt an actual
    compile (that is the build route's own job, and its own failure mode).
    """
    rustc = shutil.which("rustc") or str(Path.home() / ".cargo" / "bin" / "rustc")
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
            env={**os.environ, "RELAY_TARGET": RELAY_TARGET},
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
    """The real network fetch — never exercised in unit tests (always mocked)."""
    with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT_SECONDS) as response:
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
