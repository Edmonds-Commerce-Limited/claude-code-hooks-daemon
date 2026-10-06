"""Where the work-DRIVING machinery may run (Plan 00498).

A session that was asked for one task should not be pushed towards general work
by the daemon's own machinery: declared crons, the failsafe-recovery advice, goal
injection, goal-ledger stop challenges and the awaiting-human stand-in. The
``autonomy:`` config block names the environments where that machinery runs, and
this module answers the one question every gate asks: is autonomy allowed HERE.

"Here" is two facts: the environment (``detect_container_runtime()``, the same
detection the status line shows, with ``None`` meaning the bare host, a desktop
session) and the session's effective hostname, so a role alias such as
``HOOKS_DAEMON_HOSTNAME=cchd-sdlc-runner`` can opt a session in anywhere.

Guards are never gated. Only handlers that DRIVE work consult this (see
``Handler.drives_autonomy`` and the inventory in the plan's subagent-reports).

A project config that cannot be read keeps the default (autonomy on): the
default is the behaviour every client had before this existed, and a broken
config is reported by its own advisory.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core import ProjectContext
from claude_code_hooks_daemon.utils.config_cache import default_config, load_config_cached
from claude_code_hooks_daemon.utils.container_detection import detect_container_runtime
from claude_code_hooks_daemon.utils.cron_hosts import effective_hostname

logger = logging.getLogger(__name__)

#: The environment label for a bare host (``detect_container_runtime()`` is None).
HOST_ENVIRONMENT: Final = "host"

#: The label for a container runtime this module does not recognise.
GENERIC_ENVIRONMENT: Final = "generic"

#: The container labels ``detect_container_runtime()`` returns.
_KNOWN_RUNTIMES: Final = frozenset({"docker", "podman", "lxc", GENERIC_ENVIRONMENT})


def environment_label(runtime: str | None) -> str:
    """The environment label for an already-detected runtime (None is the bare host).

    The status line passes the runtime ``ProjectContext`` cached at startup. A
    runtime label this module does not know is an unrecognised container, so it
    is ``generic``: a container is never mistaken for the bare host.
    """
    if runtime is None:
        return HOST_ENVIRONMENT
    return runtime if runtime in _KNOWN_RUNTIMES else GENERIC_ENVIRONMENT


def current_environment() -> str:
    """The environment label for what ``detect_container_runtime()`` finds now."""
    return environment_label(detect_container_runtime())


def _project_config() -> Config:
    """The project's daemon config; the defaults when it cannot be loaded."""
    try:
        return load_config_cached(ProjectContext.config_path())
    except (RuntimeError, OSError, ValueError) as exc:
        logger.debug("autonomy: project config unavailable, using defaults: %s", exc)
        return default_config()


@dataclass(frozen=True, slots=True)
class AutonomyVerdict:
    """Whether autonomy runs here, and the facts that decided it.

    Attributes:
        allowed: True when the work-driving machinery may run.
        environment: ``host``, ``docker``, ``podman``, ``lxc`` or ``generic``.
        hostname: The effective hostname the ``hosts:`` list was matched against.
    """

    allowed: bool
    environment: str
    hostname: str

    def explain(self) -> str:
        """One plain sentence saying autonomy is off here, why, and how to change it."""
        return (
            f"AUTONOMY OFF: this session runs in the '{self.environment}' environment "
            f"(hostname '{self.hostname}'), which this project's `autonomy:` config does not "
            "list, so no crons, failsafe-recovery advice, goal injection, goal-ledger stop "
            "challenges or stand-in crons run here. Do only what you were asked in this "
            "conversation, and stop when it is done. Guards are unaffected. To change it, "
            "list this environment under `autonomy.environments` in "
            ".claude/hooks-daemon.yaml, or name a role alias under `autonomy.hosts`."
        )


def autonomy_verdict(
    hook_input: Mapping[str, Any] | None = None,
    *,
    config: Config | None = None,
    environment: str | None = None,
) -> AutonomyVerdict:
    """Decide whether autonomy runs here, keeping the facts for the explanation.

    Args:
        hook_input: The hook payload; its stamped session hostname wins.
        config: The config to judge by; the project's when omitted.
        environment: A known environment label; detected when omitted.
    """
    judged = config if config is not None else _project_config()
    where = environment if environment is not None else current_environment()
    hostname = effective_hostname(hook_input)
    return AutonomyVerdict(
        allowed=judged.autonomy.allows(where, hostname), environment=where, hostname=hostname
    )


def autonomy_allowed(hook_input: Mapping[str, Any] | None = None) -> bool:
    """Whether the work-driving machinery may run for this session."""
    return autonomy_verdict(hook_input).allowed
