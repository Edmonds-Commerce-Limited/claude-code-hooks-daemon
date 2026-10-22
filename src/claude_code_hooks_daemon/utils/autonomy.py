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

A third fact can pause it for one session: a work-halting session mode (focus,
awaiting-human, goal-blocked; Plan 00501), read from the daemon's registry for
the payload's ``session_id``. With no mode the verdict is the environment's alone.

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
from claude_code_hooks_daemon.constants.protocol import HookInputField
from claude_code_hooks_daemon.core import ProjectContext
from claude_code_hooks_daemon.core.data_layer import get_data_layer
from claude_code_hooks_daemon.utils.config_cache import default_config, load_config_cached
from claude_code_hooks_daemon.utils.container_detection import detect_container_runtime
from claude_code_hooks_daemon.utils.cron_hosts import effective_hostname
from claude_code_hooks_daemon.utils.session_modes import SessionPolicy

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
    """The environment label for this process's container runtime.

    The runtime ``ProjectContext`` cached at startup is used when the context is
    initialised, so the markers are not probed on every event. A process with no
    initialised context (a CLI command) detects it.
    """
    try:
        runtime = ProjectContext.container_runtime()
    except RuntimeError as exc:
        logger.debug("autonomy: no initialised project context, detecting the runtime: %s", exc)
        runtime = detect_container_runtime()
    return environment_label(runtime)


def _project_config() -> Config:
    """The project's daemon config; the defaults when it cannot be loaded."""
    try:
        return load_config_cached(ProjectContext.config_path())
    except (RuntimeError, OSError, ValueError) as exc:
        logger.debug("autonomy: project config unavailable, using defaults: %s", exc)
        return default_config()


#: What a paused session is spared; shared by both explanations.
_SPARED: Final = (
    "no crons, failsafe-recovery advice, goal injection, goal-ledger stop challenges or "
    "stand-in crons run"
)


@dataclass(frozen=True, slots=True)
class AutonomyVerdict:
    """Whether autonomy runs here, and the facts that decided it.

    Attributes:
        environment_allowed: True when the project's ``autonomy:`` config allows
            this environment or hostname (what the status line's "no autonomy" means).
        environment: ``host``, ``docker``, ``podman``, ``lxc`` or ``generic``.
        hostname: The effective hostname the ``hosts:`` list was matched against.
        session: The policy of this session's active modes (Plan 00501).
    """

    environment_allowed: bool
    environment: str
    hostname: str
    session: SessionPolicy

    @property
    def allowed(self) -> bool:
        """True when the work-driving machinery may run: the environment and the session agree."""
        return self.environment_allowed and self.session.drives_work

    def explain(self) -> str:
        """Plain sentences saying why autonomy does not run, and how to change it.

        With no work-halting mode this is the environment explanation alone, as
        it read before session modes existed.
        """
        clause = self.session.explain_clause()
        if not clause:
            return self._environment_text()
        exit_text = f"To resume, {self.session.exit_clause()}."
        if not self.environment_allowed:
            return f"{self._environment_text()} This session is also in {clause}. {exit_text}"
        return (
            f"AUTONOMY PAUSED FOR THIS SESSION: {clause}, so {_SPARED} in this session. "
            f"Guards are unaffected. {exit_text}"
        )

    def _environment_text(self) -> str:
        """The environment explanation: this environment is not listed, and the remedy."""
        return (
            f"AUTONOMY OFF: this session runs in the '{self.environment}' environment "
            f"(hostname '{self.hostname}'), which this project's `autonomy:` config does not "
            f"list, so {_SPARED} here. Do only what you were asked in this "
            "conversation, and stop when it is done. Guards are unaffected. To change it, "
            "list this environment under `autonomy.environments` in "
            ".claude/hooks-daemon.yaml, or name a role alias under `autonomy.hosts`."
        )


def autonomy_verdict(
    hook_input: Mapping[str, Any] | None = None,
    *,
    config: Config | None = None,
    environment: str | None = None,
    session: SessionPolicy | None = None,
) -> AutonomyVerdict:
    """Decide whether autonomy runs here, keeping the facts for the explanation.

    Args:
        hook_input: The hook payload; its stamped session hostname wins, and its
            ``session_id`` names the session whose modes are read.
        config: The config to judge by; the project's when omitted.
        environment: A known environment label; detected when omitted.
        session: The session's mode policy; read from the registry when omitted.

    Raises:
        RuntimeError: the payload names a session but no ProjectContext is
            initialised, so its modes cannot be read (see :func:`session_policy`).
    """
    judged = config if config is not None else _project_config()
    where = environment if environment is not None else current_environment()
    hostname = effective_hostname(hook_input)
    return AutonomyVerdict(
        environment_allowed=judged.autonomy.allows(where, hostname),
        environment=where,
        hostname=hostname,
        session=session if session is not None else session_policy(hook_input),
    )


def session_policy(hook_input: Mapping[str, Any] | None) -> SessionPolicy:
    """The mode policy of the payload's session, read from the daemon's registry.

    A payload that names no session (no ``session_id``, or a blank one) has no
    session to hold a mode, so its policy is empty; no registry is read. A
    payload that DOES name one is always judged by the registry: every verdict
    is computed inside the daemon, which initialises ``ProjectContext`` before
    it registers a handler, so a missing context is a defect and is raised, never
    read as "no modes".

    Raises:
        RuntimeError: no ProjectContext is initialised.
        OSError: the registry's state could not be read on first use.
    """
    session_id = (hook_input or {}).get(HookInputField.SESSION_ID)
    if not isinstance(session_id, str) or not session_id.strip():
        return SessionPolicy.from_entries(())
    return get_data_layer().session_modes.policy(session_id)


def autonomy_allowed(hook_input: Mapping[str, Any] | None = None) -> bool:
    """Whether the work-driving machinery may run for this session."""
    return autonomy_verdict(hook_input).allowed
