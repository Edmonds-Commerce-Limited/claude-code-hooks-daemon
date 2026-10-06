"""Pin where a test "runs" for the autonomy gate (Plan 00498).

``autonomy_allowed()`` reads two facts: the detected environment and the project's
``autonomy:`` config. A test that exercises a gated handler pins both, so its
result never depends on whether the suite happens to run in a container or on the
repository's own config.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.config.models import AutonomyConfig, Config
from claude_code_hooks_daemon.utils import autonomy
from claude_code_hooks_daemon.utils.cron_hosts import HOSTNAME_OVERRIDE_ENV_VARS

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


def pin_desktop_containers_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A desktop session of a project that allows autonomy in containers only."""
    pin_autonomy(monkeypatch, runtime=None, autonomy_config=CONTAINERS_ONLY)


def pin_container_containers_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """A docker session of a project that allows autonomy in containers only."""
    pin_autonomy(monkeypatch, runtime="docker", autonomy_config=CONTAINERS_ONLY)
