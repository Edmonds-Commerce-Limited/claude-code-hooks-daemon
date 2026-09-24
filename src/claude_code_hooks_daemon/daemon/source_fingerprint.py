"""Content fingerprint of the code a running daemon actually loaded (Plan 00371).

A ``DaemonController`` imports every handler module -- built-in and
project-level -- exactly once, at ``initialise()`` time, and never
hot-reloads them: a source edit on disk after that point has no effect on
the running process until it is restarted. Plan 00371's field incident was
exactly this -- the acceptance harness dispatched a probe through the live
daemon socket, the running daemon still held pre-merge code, and the probe
failed for a reason nothing in the harness could name, because nothing
compared what the daemon had loaded against what was on disk.

This module is the mechanical half of the fix: a deterministic content hash
of the ``.py`` files a daemon process would import, given the same roots. It
knows nothing about sockets or config loading -- callers gather the roots
(``daemon/controller.py`` already has them resolved from its own startup
parameters; a QA-side caller resolves them independently) and pass them in.

A daemon also binds its CONFIG once, at startup (Plan 00415), so freshness is
two fingerprints: the code (``compute_source_fingerprint``, ``.py`` files
only) and the resolved config model (``compute_config_fingerprint``). Every
consumer judges them together through ``describe_daemon_staleness``, which
takes the whole health payload -- reading one key alone is the defect the
``freshness-verdict-read-piecemeal`` semgrep rule exists to catch.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from claude_code_hooks_daemon.config.models import Config

logger = logging.getLogger(__name__)

#: Health-payload keys (``DaemonController.get_health``). Read only here.
HEALTH_KEY_SOURCE_FINGERPRINT: Final[str] = "source_fingerprint"
HEALTH_KEY_CONFIG_FINGERPRINT: Final[str] = "config_fingerprint"

#: The config half of an on-disk config that does not load. Never a sha256
#: hex digest, so it can equal no running daemon's fingerprint -- a daemon
#: refuses to start on such a config -- and it is distinct from "no config
#: file", which the daemon runs on happily with defaults.
CONFIG_PARSE_FAILED_FINGERPRINT: Final[str] = "config-parse-failed"

_FINGERPRINT_DISPLAY_CHARS: Final[int] = 12
_RESTART_ADVICE: Final[str] = "Restart it with `bin/hooks-daemon restart` and retry."


@dataclass(frozen=True)
class DaemonFingerprints:
    """Both halves of what a daemon binds at startup: code and config."""

    source: str
    config: str


#: Two levels up from this file (``daemon/source_fingerprint.py``) is the
#: package root (``claude_code_hooks_daemon/``) -- wherever the running
#: interpreter actually resolved this module from. Correct in both
#: self-install mode (this repository's own ``src/``) and a client install
#: (the deployed copy under ``.claude/hooks-daemon/src/``), because it names
#: the location THIS import came from rather than guessing a layout.
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def daemon_package_root() -> Path:
    """Return the directory the running interpreter imported this package from."""
    return _PACKAGE_ROOT


def compute_source_fingerprint(*roots: Path) -> str:
    """Return a sha256 hex digest summarising every ``.py`` file under ``roots``.

    Deterministic regardless of filesystem iteration order (files are
    visited in sorted path order) and sensitive to both a content change and
    a rename (each file's path relative to its root is mixed in alongside
    its bytes, so moving a handler to a different event-type directory
    changes the digest even though the bytes did not).

    A root that does not exist is skipped rather than raising -- matching
    the project convention that an optional directory's absence (e.g. no
    project-handlers tree yet) is a normal state, not a fatal one. Only
    ``.py`` files are hashed: the fingerprint's contract is "the code a
    running Python process imported", not "everything under this path".
    """
    hasher = hashlib.sha256(usedforsecurity=False)
    for root in roots:
        if not root.is_dir():
            continue
        for py_file in sorted(root.rglob("*.py")):
            if not py_file.is_file():
                continue
            hasher.update(str(py_file.relative_to(root)).encode("utf-8"))
            hasher.update(py_file.read_bytes())
    return hasher.hexdigest()


def compute_daemon_identity_fingerprint(*extra_roots: Path) -> str:
    """Fingerprint of the daemon's own package plus any caller-supplied extra roots.

    ``extra_roots`` is typically a single resolved project-handlers
    directory (only when project handlers are enabled -- the caller decides
    that; this function has no config awareness). Passing none reduces to
    the fingerprint of the daemon package alone.
    """
    return compute_source_fingerprint(daemon_package_root(), *extra_roots)


def compute_config_fingerprint(config: Config) -> str:
    """Return a sha256 hex digest of the RESOLVED config model (Plan 00415).

    Hashes what a daemon binds, not the file's bytes: a comment or a
    reformat is not drift, while every value the model resolves -- handler
    options, defaults, validator migrations -- is. ``mode="json"`` renders
    every value as a JSON primitive and ``sort_keys`` fixes the order, so the
    same config hashes identically across processes, hash seeds and working
    directories; an unstable serialisation would make the guard cry stale at
    random.
    """
    canonical = json.dumps(
        config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8"), usedforsecurity=False).hexdigest()


def compute_current_project_fingerprints(project_root: Path | str) -> DaemonFingerprints:
    """Both fingerprints a daemon freshly started against ``project_root`` would report.

    Loads the project's config exactly the way daemon startup does
    (``Config.find_and_load``), so a caller with no live controller -- a CLI
    verb, an acceptance test -- computes the SAME values a running daemon
    reports. The config also resolves ``project_handlers`` for the code half,
    mirroring ``DaemonController.initialise()``.

    Never raises on a broken config: a freshness CHECK must produce a
    verdict, not a crash. A config that does not load hashes to
    :data:`CONFIG_PARSE_FAILED_FINGERPRINT` -- distinct from "no config",
    which the daemon runs on with defaults -- and the code half falls back to
    the default ``project_handlers`` layout.
    """
    from claude_code_hooks_daemon.config.models import Config
    from claude_code_hooks_daemon.utils.repo_relative_path import (
        resolve_repo_relative_path,
    )

    project_root = Path(project_root)
    try:
        config = Config.find_and_load(project_root)
        config_fingerprint = compute_config_fingerprint(config)
    except FileNotFoundError:
        # Found, then gone before it was read: the daemon would now start
        # on defaults, so that is what is hashed.
        config = Config()
        config_fingerprint = compute_config_fingerprint(config)
    except (OSError, ValueError) as exc:
        # ValueError covers a YAML syntax error and pydantic's
        # ValidationError alike; OSError an unreadable file.
        logger.warning("Config at %s does not load, for freshness check: %s", project_root, exc)
        config = Config()
        config_fingerprint = CONFIG_PARSE_FAILED_FINGERPRINT

    extra_roots: list[Path] = []
    if config.project_handlers.enabled:
        extra_roots.append(resolve_repo_relative_path(config.project_handlers.path, project_root))
    return DaemonFingerprints(
        source=compute_daemon_identity_fingerprint(*extra_roots), config=config_fingerprint
    )


def compute_current_project_fingerprint(project_root: Path | str) -> str:
    """The CODE half of :func:`compute_current_project_fingerprints`.

    A freshness verdict needs both halves; judge one with
    :func:`describe_daemon_staleness`, never with this alone.
    """
    return compute_current_project_fingerprints(project_root).source


def _reported(health: Mapping[str, Any], key: str) -> str | None:
    """A fingerprint the daemon reported under ``key``, or None if none usable."""
    value = health.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _describe_config_drift(running: str, current: str) -> str:
    if current == CONFIG_PARSE_FAILED_FINGERPRINT:
        return (
            f"the config it bound at startup ({HEALTH_KEY_CONFIG_FINGERPRINT} "
            f"{running[:_FINGERPRINT_DISPLAY_CHARS]}) has since been edited, and the "
            f"config on disk now does not parse -- fix it first "
            f"(`bin/hooks-daemon config-validate`), because a daemon will not start on it"
        )
    return (
        f"the config it bound at startup ({HEALTH_KEY_CONFIG_FINGERPRINT} "
        f"{running[:_FINGERPRINT_DISPLAY_CHARS]}) does not match the config on disk "
        f"as it resolves now ({current[:_FINGERPRINT_DISPLAY_CHARS]}) -- "
        f"`.claude/hooks-daemon.yaml` was edited without a restart"
    )


def describe_daemon_staleness(
    health: Mapping[str, Any] | None, current: DaemonFingerprints
) -> str | None:
    """The single freshness verdict: a diagnostic if the daemon looks stale, else ``None``.

    ``health`` is the WHOLE ``result`` of a live daemon's ``_system``/``health``
    socket action -- never a key pulled out of it, so no consumer can check
    one half and skip the other. ``current`` is freshly computed from disk.

    Anything short of both fingerprints reported and matching is a staleness
    RISK rather than "cannot tell": no response, a payload missing either key
    (a daemon predating Plan 00371 or 00415), or a malformed value. A caller
    that cannot verify freshness must not silently trust a live-dispatch
    result either. A drift message names which input moved -- code, config
    or both -- because each sends a reader somewhere different to find out
    what changed, even though the remedy is the same.
    """
    if not isinstance(health, Mapping):
        return (
            "Could not verify the running daemon matches the working tree (no "
            "health response -- the daemon may be down or unreachable). "
            f"{_RESTART_ADVICE}"
        )
    running_source = _reported(health, HEALTH_KEY_SOURCE_FINGERPRINT)
    running_config = _reported(health, HEALTH_KEY_CONFIG_FINGERPRINT)
    if running_source is None or running_config is None:
        missing = [
            key
            for key, value in (
                (HEALTH_KEY_SOURCE_FINGERPRINT, running_source),
                (HEALTH_KEY_CONFIG_FINGERPRINT, running_config),
            )
            if value is None
        ]
        return (
            "Could not verify the running daemon matches the working tree (no "
            f"{' or '.join(missing)} in its health response -- the daemon may "
            f"predate Plan 00371/00415). {_RESTART_ADVICE}"
        )

    drifted: list[str] = []
    if running_source != current.source:
        drifted.append(
            f"its loaded code ({HEALTH_KEY_SOURCE_FINGERPRINT} "
            f"{running_source[:_FINGERPRINT_DISPLAY_CHARS]}) does not match the "
            f"working tree ({current.source[:_FINGERPRINT_DISPLAY_CHARS]})"
        )
    if running_config != current.config:
        drifted.append(_describe_config_drift(running_config, current.config))
    if not drifted:
        return None
    return (
        f"STALE DAEMON: {'; and '.join(drifted)}. A live-dispatch result graded "
        f"against it would be judging what it bound at startup, not what is on "
        f"disk. {_RESTART_ADVICE}"
    )
