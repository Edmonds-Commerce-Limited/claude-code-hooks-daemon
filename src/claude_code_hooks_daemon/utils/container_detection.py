"""Environment detection utilities.

This module separates THREE orthogonal facts that an earlier "container
confidence score" wrongly conflated under a single label:

1. **Running under Claude Code** (:func:`running_under_claude_code`) — signalled
   by ``CLAUDECODE`` / ``CLAUDE_CODE_ENTRYPOINT``. This daemon ONLY ever runs as
   a Claude Code hook, so these are ~always true in production. They are NOT
   evidence of a container and must never be scored as such.

2. **YOLO / sandbox mode** (:func:`is_yolo_sandbox`) — an auto-approve sandbox
   (``IS_SANDBOX`` / ``DEVCONTAINER`` / ``/workspace`` + ``.claude/``). Distinct
   from "container".

3. **Actually inside a container** (:func:`detect_container_runtime` /
   :func:`in_container`) — determined ONLY from honest OS-level container
   markers (the ``container`` env var, ``/run/systemd/container``,
   ``/.dockerenv``, ``/run/.containerenv``, ``/proc/1/cgroup``, and the LXD/LXC
   dev markers ``/dev/lxd/sock`` / ``/dev/.lxc``), mirroring the
   ``_uv_in_container`` bash helper in ``scripts/install/venv.sh``.

The previous confidence scorer awarded ``CLAUDECODE=1`` three points against a
threshold of three, so every Claude Code session — desktop included — was
mis-classified as a container. That conflation is removed here.
"""

import logging
import os
from pathlib import Path

from claude_code_hooks_daemon.core import ProjectContext

logger = logging.getLogger(__name__)

# --- "Running under Claude Code" signals (NOT container evidence) -----------
_ENV_CLAUDECODE = "CLAUDECODE"
_CLAUDECODE_TRUE = "1"
_ENV_CLAUDE_ENTRYPOINT = "CLAUDE_CODE_ENTRYPOINT"
_CLAUDE_ENTRYPOINT_CLI = "cli"

# --- Honest container-runtime signals ---------------------------------------
_ENV_CONTAINER = "container"
_RUNTIME_DOCKER = "docker"
_RUNTIME_PODMAN = "podman"
_RUNTIME_GENERIC = "generic"
_RUNTIME_LXC = "lxc"
# Values the `container` env var may carry, mapped to a runtime label.
# systemd-nspawn-style LXC setups set ``container=lxc`` / ``lxc-libvirt``.
_CONTAINER_ENV_RUNTIMES: dict[str, str] = {
    "podman": _RUNTIME_PODMAN,
    "docker": _RUNTIME_DOCKER,
    "oci": _RUNTIME_GENERIC,
    "crio": _RUNTIME_GENERIC,
    "lxc": _RUNTIME_LXC,
    "lxc-libvirt": _RUNTIME_LXC,
}

# Marker-file paths. Defaults match Docker (`/.dockerenv`) and Podman
# (`/run/.containerenv`); overridable via env vars (same names as the
# Plan 00125 `_uv_in_container` bash helper) so tests can run hermetically from
# inside a real container.
_ENV_DOCKERENV_PATH = "HOOKS_DAEMON_DOCKERENV_PATH"
_DEFAULT_DOCKERENV_PATH = "/.dockerenv"
_ENV_CONTAINERENV_PATH = "HOOKS_DAEMON_CONTAINERENV_PATH"
_DEFAULT_CONTAINERENV_PATH = "/run/.containerenv"
_ENV_CGROUP_PATH = "HOOKS_DAEMON_CGROUP_PATH"
_DEFAULT_CGROUP_PATH = "/proc/1/cgroup"

# /run/systemd/container — the PRIMARY confirmed signal for a systemd-based LXC
# container (the host-a unprivileged-LXC capture had `container` unset, no
# marker files, cgroup v2 with no token, but this file contained "lxc"). It is
# world-readable and one cheap read. Overridable for hermetic tests.
_ENV_SYSTEMD_CONTAINER_PATH = "HOOKS_DAEMON_SYSTEMD_CONTAINER_PATH"
_DEFAULT_SYSTEMD_CONTAINER_PATH = "/run/systemd/container"
# File-content values (already stripped+lowercased) that mean LXC.
_SYSTEMD_CONTAINER_LXC_VALUES: tuple[str, ...] = ("lxc", "lxc-libvirt")

# LXD/LXC dev markers — present in privileged LXD where the socket is exposed.
# Checked LAST (cheap existence probes); absent in the confirmed unprivileged
# LXC capture, kept as forward-compatible signals.
_ENV_LXD_SOCK_PATH = "HOOKS_DAEMON_LXD_SOCK_PATH"
_DEFAULT_LXD_SOCK_PATH = "/dev/lxd/sock"
_ENV_LXC_DEV_PATH = "HOOKS_DAEMON_LXC_DEV_PATH"
_DEFAULT_LXC_DEV_PATH = "/dev/.lxc"

# cgroup substring tokens → runtime label, checked in this order (most specific
# first). ``docker`` before the podman tokens before the lxc/generic tokens.
# The cgroup-v1 ``lxc`` token now maps to the lxc runtime (cgroup v2 carries no
# token and is caught by the /run/systemd/container reader above).
_CGROUP_TOKENS: tuple[tuple[str, str], ...] = (
    ("docker", _RUNTIME_DOCKER),
    ("libpod", _RUNTIME_PODMAN),
    ("podman", _RUNTIME_PODMAN),
    ("containerd", _RUNTIME_GENERIC),
    ("lxc", _RUNTIME_LXC),
    ("kubepods", _RUNTIME_GENERIC),
)

# KNOWN LIMITATION: a NON-systemd LXC container (no /run/systemd/container, no
# cgroup-v1 lxc token, no /dev/lxd/sock or /dev/.lxc, and `container` unset) is
# NOT detectable from file/env signals alone. We deliberately do NOT shell out
# to `systemd-detect-virt` to avoid the bandit B603/B607 subprocess gate;
# /run/systemd/container already covers the confirmed systemd-based LXC case
# (the host-a capture).

# --- YOLO / sandbox signals -------------------------------------------------
_ENV_IS_SANDBOX = "IS_SANDBOX"
_IS_SANDBOX_TRUE = "1"
_ENV_DEVCONTAINER = "DEVCONTAINER"
_DEVCONTAINER_TRUE = "true"
_WORKSPACE_ROOT = Path("/workspace")


def running_under_claude_code() -> bool:
    """Return True when executing under the Claude Code CLI.

    Signalled by ``CLAUDECODE=1`` or ``CLAUDE_CODE_ENTRYPOINT=cli``.

    NOTE: this daemon only ever runs as a Claude Code hook, so this is ~always
    True in production. It is exposed for observability/honesty and must NEVER
    be treated as evidence of a container or a sandbox.
    """
    return (
        os.environ.get(_ENV_CLAUDECODE) == _CLAUDECODE_TRUE
        or os.environ.get(_ENV_CLAUDE_ENTRYPOINT) == _CLAUDE_ENTRYPOINT_CLI
    )


def _marker_exists(path: str) -> bool:
    """Return whether a container marker file exists, treating a probe error as
    "absent" with an explicit debug log (never silently swallowed)."""
    try:
        return Path(path).exists()
    except OSError as exc:
        logger.debug("container marker probe failed for %s: %s", path, exc)
        return False


def _runtime_from_cgroup() -> str | None:
    """Parse the cgroup file for a container-runtime token.

    A missing/unreadable cgroup file (e.g. on macOS) is a legitimate "no signal"
    outcome on the host — logged at debug level and reported as None, not hidden.
    """
    cgroup_path = os.environ.get(_ENV_CGROUP_PATH, _DEFAULT_CGROUP_PATH)
    try:
        content = Path(cgroup_path).read_text(encoding="utf-8", errors="replace").lower()
    except OSError as exc:
        # A missing/unreadable cgroup file (e.g. on macOS) is a legitimate
        # "no signal" outcome: log it and treat content as empty so the loop
        # below finds no token and the function reports None via its normal path.
        logger.debug("cgroup probe failed for %s: %s", cgroup_path, exc)
        content = ""
    for token, runtime in _CGROUP_TOKENS:
        if token in content:
            return runtime
    return None


def _runtime_from_systemd_container() -> str | None:
    """Return ``"lxc"`` iff /run/systemd/container marks a systemd-based LXC.

    Reads the env-overridable ``/run/systemd/container`` (default), strips and
    lowercases it, and returns :data:`_RUNTIME_LXC` only when the content is in
    :data:`_SYSTEMD_CONTAINER_LXC_VALUES`. This helper is deliberately LXC-only:
    a future systemd ``docker``/``podman`` value is NOT remapped here — those
    already have dedicated markers/branches.

    A missing/unreadable file (the host case — systemd only creates it inside a
    container) is a legitimate "no signal" outcome: logged at debug level and
    reported as None, never hidden.
    """
    path = os.environ.get(_ENV_SYSTEMD_CONTAINER_PATH, _DEFAULT_SYSTEMD_CONTAINER_PATH)
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace").strip().lower()
    except OSError as exc:
        # A missing/unreadable file (the host case — systemd only creates it
        # inside a container) is a legitimate "no signal" outcome: log it and
        # treat content as empty so the check below finds no LXC value and the
        # function reports None via its normal return path.
        logger.debug("systemd-container probe failed for %s: %s", path, exc)
        content = ""
    if content in _SYSTEMD_CONTAINER_LXC_VALUES:
        return _RUNTIME_LXC
    return None


def detect_container_runtime() -> str | None:
    """Return the container runtime this process runs in, or None on the host.

    Returns one of ``"docker"``, ``"podman"``, ``"generic"`` (an unrecognised
    OCI/containerd runtime), ``"lxc"`` (LXC/LXD), or ``None`` (not in a
    container). Uses ONLY honest container markers, checked cheapest-first:

    1. the ``container`` env var (Podman/systemd set ``container=podman``;
       LXC may set ``container=lxc`` / ``lxc-libvirt``),
    2. ``/run/systemd/container`` content ``lxc``/``lxc-libvirt`` (the primary
       confirmed signal for systemd-based LXC),
    3. the Docker marker file ``/.dockerenv``,
    4. the Podman marker file ``/run/.containerenv``,
    5. a container token in ``/proc/1/cgroup`` (cgroup-v1 ``lxc`` → ``lxc``),
    6. the LXD/LXC dev markers ``/dev/lxd/sock`` / ``/dev/.lxc``.

    Never raises — any filesystem error degrades to "no signal" for that check.
    """
    env_value = os.environ.get(_ENV_CONTAINER, "").strip().lower()
    if env_value in _CONTAINER_ENV_RUNTIMES:
        return _CONTAINER_ENV_RUNTIMES[env_value]

    runtime = _runtime_from_systemd_container()
    if runtime is not None:
        return runtime

    if _marker_exists(os.environ.get(_ENV_DOCKERENV_PATH, _DEFAULT_DOCKERENV_PATH)):
        return _RUNTIME_DOCKER

    if _marker_exists(os.environ.get(_ENV_CONTAINERENV_PATH, _DEFAULT_CONTAINERENV_PATH)):
        return _RUNTIME_PODMAN

    runtime = _runtime_from_cgroup()
    if runtime is not None:
        return runtime

    if _marker_exists(os.environ.get(_ENV_LXD_SOCK_PATH, _DEFAULT_LXD_SOCK_PATH)) or _marker_exists(
        os.environ.get(_ENV_LXC_DEV_PATH, _DEFAULT_LXC_DEV_PATH)
    ):
        return _RUNTIME_LXC

    return None


def in_container() -> bool:
    """Return True iff a container runtime is detected (honest markers only)."""
    return detect_container_runtime() is not None


def is_container_environment() -> bool:
    """Precise container check — alias for :func:`in_container`.

    Retained under its historical name because ``daemon/enforcement.py`` and
    ``daemon/init_config.py`` import it and genuinely want "are we in a real
    container". It no longer uses the tautological confidence score.
    """
    return in_container()


def is_yolo_sandbox() -> bool:
    """Return True in a YOLO / auto-approve sandbox environment.

    Signals: ``IS_SANDBOX=1``, ``DEVCONTAINER=true``, or project root
    ``/workspace`` with a ``.claude/`` directory present. This is orthogonal to
    both "running under Claude Code" and "in a container" — notably it is NOT
    triggered by ``CLAUDECODE`` / ``CLAUDE_CODE_ENTRYPOINT``. Fail-safe (False).
    """
    if os.environ.get(_ENV_IS_SANDBOX) == _IS_SANDBOX_TRUE:
        return True
    if os.environ.get(_ENV_DEVCONTAINER) == _DEVCONTAINER_TRUE:
        return True
    try:
        in_workspace = ProjectContext.project_root() == _WORKSPACE_ROOT
        if in_workspace and ProjectContext.config_dir().exists():
            return True
    except (OSError, RuntimeError) as exc:
        logger.debug("is_yolo_sandbox ProjectContext probe failed: %s", exc)
        return False
    return False
