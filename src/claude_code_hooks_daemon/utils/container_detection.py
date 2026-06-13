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
   markers (the ``container`` env var, ``/.dockerenv``, ``/run/.containerenv``,
   ``/proc/1/cgroup``), mirroring the ``_uv_in_container`` bash helper in
   ``scripts/install/venv.sh``.

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
# Values the `container` env var may carry, mapped to a runtime label.
_CONTAINER_ENV_RUNTIMES: dict[str, str] = {
    "podman": _RUNTIME_PODMAN,
    "docker": _RUNTIME_DOCKER,
    "oci": _RUNTIME_GENERIC,
    "crio": _RUNTIME_GENERIC,
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

# cgroup substring tokens → runtime label, checked in this order (most specific
# first). ``docker`` before the podman tokens before the generic tokens.
_CGROUP_TOKENS: tuple[tuple[str, str], ...] = (
    ("docker", _RUNTIME_DOCKER),
    ("libpod", _RUNTIME_PODMAN),
    ("podman", _RUNTIME_PODMAN),
    ("containerd", _RUNTIME_GENERIC),
    ("lxc", _RUNTIME_GENERIC),
    ("kubepods", _RUNTIME_GENERIC),
)

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
        logger.debug("cgroup probe failed for %s: %s", cgroup_path, exc)
        return None
    for token, runtime in _CGROUP_TOKENS:
        if token in content:
            return runtime
    return None


def detect_container_runtime() -> str | None:
    """Return the container runtime this process runs in, or None on the host.

    Returns one of ``"docker"``, ``"podman"``, ``"generic"`` (an unrecognised
    OCI/containerd/LXC runtime), or ``None`` (not in a container). Uses ONLY
    honest container markers, checked in order:

    1. the ``container`` env var (Podman/systemd set ``container=podman``),
    2. the Docker marker file ``/.dockerenv``,
    3. the Podman marker file ``/run/.containerenv``,
    4. a container token in ``/proc/1/cgroup``.

    Never raises — any filesystem error degrades to "no signal" for that check.
    """
    env_value = os.environ.get(_ENV_CONTAINER, "").strip().lower()
    if env_value in _CONTAINER_ENV_RUNTIMES:
        return _CONTAINER_ENV_RUNTIMES[env_value]

    if _marker_exists(os.environ.get(_ENV_DOCKERENV_PATH, _DEFAULT_DOCKERENV_PATH)):
        return _RUNTIME_DOCKER

    if _marker_exists(os.environ.get(_ENV_CONTAINERENV_PATH, _DEFAULT_CONTAINERENV_PATH)):
        return _RUNTIME_PODMAN

    return _runtime_from_cgroup()


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
