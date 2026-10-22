"""Pin where a test "runs" for the autonomy gate (Plan 00498).

``autonomy_allowed()`` reads two facts: the detected environment and the project's
``autonomy:`` config. A test that exercises a gated handler pins both, so its
result never depends on whether the suite happens to run in a container or on the
repository's own config.
"""

from __future__ import annotations

import tempfile
import time
import uuid
from pathlib import Path

import pytest

import claude_code_hooks_daemon.core.data_layer as data_layer
from claude_code_hooks_daemon.config.models import AutonomyConfig, Config
from claude_code_hooks_daemon.core import ProjectContext
from claude_code_hooks_daemon.core.session_mode_registry import SessionModeRegistry
from claude_code_hooks_daemon.utils import autonomy
from claude_code_hooks_daemon.utils.cron_hosts import HOSTNAME_OVERRIDE_ENV_VARS
from claude_code_hooks_daemon.utils.session_modes import (
    FOCUS_TTL_SECONDS,
    BlockReason,
    ModeSource,
    SessionMode,
    SessionModeEntry,
)

#: What this repository's own config declares: autonomy in containers only.
CONTAINERS_ONLY = AutonomyConfig(environments=["docker", "podman", "lxc", "generic"])


def pin_autonomy(
    monkeypatch: pytest.MonkeyPatch,
    *,
    runtime: str | None,
    autonomy_config: AutonomyConfig | None = None,
) -> None:
    """Run the gate as if in ``runtime`` (None is the bare host) under ``autonomy_config``.

    Args:
        monkeypatch: The test's monkeypatch.
        runtime: ``docker``, ``podman``, ``lxc``, ``generic`` or None for a desktop.
        autonomy_config: The project's ``autonomy:`` block; the default (every
            environment) when omitted.
    """
    for name in HOSTNAME_OVERRIDE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    config = Config(autonomy=autonomy_config or AutonomyConfig())
    monkeypatch.setattr(autonomy, "detect_container_runtime", lambda: runtime)
    monkeypatch.setattr(autonomy, "_project_config", lambda: config)
    pin_no_session_modes(monkeypatch)


def pin_no_session_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give the gate a loaded, empty session-modes registry, as a daemon with no mode has.

    A payload naming a session is judged by the registry, which needs the
    daemon's ProjectContext; these tests have none. The registry's directory is
    never created: a test that enters a mode uses :func:`pin_session_modes`.
    """
    registry = SessionModeRegistry(Path(tempfile.gettempdir()) / f"no-modes-{uuid.uuid4().hex}")
    registry.load()
    layer = data_layer.DaemonDataLayer()
    monkeypatch.setattr(layer, "_session_modes", registry)
    monkeypatch.setattr(data_layer, "_data_layer", layer)


def pin_session_modes(
    monkeypatch: pytest.MonkeyPatch, untracked: Path, *entries: SessionModeEntry
) -> SessionModeRegistry:
    """Give the gate a real session-modes registry under ``untracked`` holding ``entries``.

    The verdict reads modes through ``get_data_layer().session_modes``, the same
    lookup the daemon makes, so the data-layer singleton is swapped for a fresh
    one (restored after the test) and ``ProjectContext.daemon_untracked_dir`` is
    pointed at ``untracked``. With no ``entries`` the session has no mode.

    Returns:
        The registry the gate will read.
    """
    monkeypatch.setattr(ProjectContext, "daemon_untracked_dir", classmethod(lambda cls: untracked))
    monkeypatch.setattr(data_layer, "_data_layer", data_layer.DaemonDataLayer())
    registry = data_layer.get_data_layer().session_modes
    for entry in entries:
        registry.enter(entry)
    return registry


def focus_entry(session_id: str, task: str = "the one task") -> SessionModeEntry:
    """A live focus mode for ``session_id``."""
    now = time.time()
    return SessionModeEntry(
        mode=SessionMode.FOCUS,
        session_id=session_id,
        entered_at=now,
        expires_at=now + FOCUS_TTL_SECONDS,
        source=ModeSource.HUMAN,
        detail=task,
    )


def awaiting_human_entry(session_id: str) -> SessionModeEntry:
    """A live declared awaiting-human mode for ``session_id``."""
    now = time.time()
    return SessionModeEntry(
        mode=SessionMode.BLOCKED,
        session_id=session_id,
        entered_at=now,
        expires_at=now + 3600.0,
        source=ModeSource.AGENT,
        reason=BlockReason.DECLARED,
    )


def pin_desktop_containers_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A desktop session of a project that allows autonomy in containers only."""
    pin_autonomy(monkeypatch, runtime=None, autonomy_config=CONTAINERS_ONLY)


def pin_container_containers_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A docker session of a project that allows autonomy in containers only."""
    pin_autonomy(monkeypatch, runtime="docker", autonomy_config=CONTAINERS_ONLY)
