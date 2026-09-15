"""The operator-signal channel: host -> idle session, closed by design (Plan 00417).

Sessions run in a container on a machine the operator, or an automated patch
cycle, sometimes reboots. Nothing told the agent before this: work in flight
was cut off mid-step, uncommitted changes lost. This is the SENSOR half — a
CLI-driven writer, mirroring `write_goal_signal` and
`model_downgrade_signal.write_downgrade_signal` — that drops one small JSON
file per targeted session into the same shared, session-scoped
context-sidecar directory the supervisor already watches. The ACTUATOR half
(`load_operator_signal` / `_render_operator_message` in the standalone
`.claude/ccy/claude-supervise.py`) is a separate module by necessity: the
supervisor is a stdlib-only script that cannot import this package. Path and
field names live here, and the `kind` string constants are pinned to the
supervisor's own copies by `tests/unit/supervise/test_operator_signal.py`, so
the two cannot drift apart.

**The security shape is the whole point.** This is the one signal family
reachable from OUTSIDE the container, so unlike the goal signal (which
carries operator-composed free text, validated only for SHAPE) this one
carries a `kind` drawn from a closed set and, for the two kinds that need
one, a bare positive integer — never a reason field, never a body of text.
`write_operator_signal` enforces that shape at the point of writing so a
CLI caller fails fast; `load_operator_signal` on the supervisor side
enforces it again independently against the untyped bytes actually on disk,
because a forged or corrupted file is a real possibility for a channel
written from outside the container. The WORDING the agent ever sees is
composed entirely by the supervisor's `_render_operator_message` from fixed
templates — this module never renders a message, it only ever carries a
`kind` and a number.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

logger = logging.getLogger(__name__)

#: Written beside the context sidecar and the goal-intent signal -- the
#: supervisor already watches this directory, so no new transport is needed.
SIGNAL_SUBDIR: Final[str] = "context-sidecar"

#: Deliberately NOT ``.json``: the supervisor's sidecar reader globs that
#: extension and would otherwise mistake an operator signal for a context
#: sidecar.
SIGNAL_SUFFIX: Final[str] = ".operator-signal"

_SESSION_ID_FALLBACK: Final[str] = "unknown"
_UNSAFE_SESSION_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_.-]")

FIELD_TS: Final[str] = "ts"
FIELD_SESSION_ID: Final[str] = "session_id"
FIELD_KIND: Final[str] = "kind"
FIELD_MINUTES: Final[str] = "minutes"
FIELD_SOURCE: Final[str] = "source"

#: The closed set of signal kinds. Anything else is refused at write time
#: (here) and, independently, at read time (the supervisor). See the module
#: docstring on why both sides validate.
KIND_REBOOT_WARNING: Final[str] = "reboot-warning"
KIND_SHUTDOWN_WARNING: Final[str] = "shutdown-warning"
KIND_REBOOT_CANCELLED: Final[str] = "reboot-cancelled"
KINDS_WITH_MINUTES: Final[frozenset[str]] = frozenset({KIND_REBOOT_WARNING, KIND_SHUTDOWN_WARNING})
KINDS: Final[frozenset[str]] = KINDS_WITH_MINUTES | {KIND_REBOOT_CANCELLED}

SOURCE_CLI: Final[str] = "cli"


def _session_stem(session_id: str) -> str:
    """A filesystem-safe stem for ``session_id``.

    The id may arrive from a CLI argument or environment variable, so it is
    untrusted: separators and traversal dots are collapsed rather than
    allowed to steer the write out of the signal directory.
    """
    stem = _UNSAFE_SESSION_CHARS.sub("_", session_id.strip())
    return stem or _SESSION_ID_FALLBACK


def signal_path(daemon_untracked_dir: Path, session_id: str) -> Path:
    """The signal file path for ``session_id``."""
    return daemon_untracked_dir / SIGNAL_SUBDIR / f"{_session_stem(session_id)}{SIGNAL_SUFFIX}"


def write_operator_signal(
    daemon_untracked_dir: Path,
    *,
    session_id: str,
    kind: str,
    minutes: int | None,
    now: float,
    source: str = SOURCE_CLI,
) -> Path:
    """Atomically write a ``<session>.operator-signal`` file.

    ``kind`` must be one of :data:`KINDS`. ``minutes`` must be a positive
    ``int`` when ``kind`` is in :data:`KINDS_WITH_MINUTES`, and must be
    ``None`` for every other kind — raises ``ValueError`` otherwise, so a
    CLI caller fails fast rather than writing a signal the supervisor's
    reader would only reject later (mirroring
    ``claude-supervise.write_model_switch_signal``'s contract). ``bool`` is
    rejected explicitly even though it is an ``int`` subclass in Python, so
    a caller cannot silently coerce ``True`` into a 1-minute warning.

    This function never composes the sentence the agent will see — it only
    ever carries a closed-set ``kind`` and a bare integer. Rendering is
    entirely the supervisor's job (see the module docstring); that split is
    what keeps this channel unable to carry arbitrary text.

    Raises:
        ValueError: ``kind`` is unrecognised, or ``minutes`` does not match
            what ``kind`` requires.
        OSError: the write itself failed (propagates uncaught — unlike the
            best-effort sensor handlers, a CLI command should report a
            write failure rather than silently doing nothing).
    """
    if kind not in KINDS:
        raise ValueError(f"unknown operator signal kind {kind!r}; expected one of {sorted(KINDS)}")
    needs_minutes = kind in KINDS_WITH_MINUTES
    if needs_minutes:
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
            raise ValueError(
                f"kind {kind!r} requires a positive integer minutes value, got {minutes!r}"
            )
    elif minutes is not None:
        raise ValueError(f"kind {kind!r} takes no minutes payload, got {minutes!r}")

    target_dir = daemon_untracked_dir / SIGNAL_SUBDIR
    target_dir.mkdir(parents=True, exist_ok=True)
    final_path = signal_path(daemon_untracked_dir, session_id)
    payload: dict[str, object] = {
        FIELD_TS: now,
        FIELD_SESSION_ID: session_id,
        FIELD_KIND: kind,
        FIELD_SOURCE: source,
    }
    if needs_minutes:
        payload[FIELD_MINUTES] = minutes
    tmp_path = unique_temp_path(final_path)
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    tmp_path.replace(final_path)
    return final_path


def discover_session_ids(daemon_untracked_dir: Path) -> list[str]:
    """Every session id with a live context sidecar in THIS project.

    Backs ``--all-sessions``: each live ``ccy`` session writes its own
    ``<session>.json`` context sidecar into this same shared,
    project-scoped directory (Plan 00166's "two terminals share one dir"
    fact — it is a bind-mounted ``untracked/``), so a sidecar's stem names
    a session id this project's supervisor(s) will recognise, and nothing
    outside this project's own untracked tree can appear here. A directory
    that does not exist yet (no session has ever run) yields no ids rather
    than raising. Sorted for deterministic output; a dotfile (an
    in-progress atomic-write temp file) is excluded even though it would
    not otherwise match ``*.json`` (those temp names end in ``.tmp``).
    """
    sidecar_dir = daemon_untracked_dir / SIGNAL_SUBDIR
    if not sidecar_dir.is_dir():
        return []
    return sorted(
        path.stem
        for path in sidecar_dir.glob("*.json")
        if path.is_file() and not path.name.startswith(".")
    )
