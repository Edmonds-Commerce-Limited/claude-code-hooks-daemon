"""Name -> definition-type record of dispatched sub-agents.

A sub-agent's tool events carry ``agent_type``, but the value is the agent's
dispatch NAME when the Agent tool call set ``name`` and the definition type
(``subagent_type``) when it did not (measured on live payloads, Plan 00518
Task 0.1). A guard keying on the definition type must therefore translate: the
daemon records ``name -> subagent_type`` when it sees the dispatch, and
:func:`effective_agent_type` reads it back for the teammate's own events.

The payload ``agent_id`` tells the two apart: an unnamed agent's id has a fixed
shape, and only an agent whose id does not have it is looked up as a name.
Residual limit: an UNNAMED agent's ``agent_type`` is trusted as its type; the
payload offers nothing to check it against.

Every write is atomic and keyed by ``(session_id, name)`` -- one file per pair
-- so concurrent dispatches in one session never clobber each other and a
reader never sees a half-written file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

logger = logging.getLogger(__name__)

#: Subdirectory of the daemon untracked dir holding the records.
REGISTRY_SUBDIR = "agent-dispatch-registry"

#: Shape of an UNNAMED sub-agent's ``agent_id``: ``a`` + 16 lowercase hex
#: (measured live, Plan 00518 Task 0.1: ``a57801934993f0485``). A named teammate's
#: id is ``a`` + name + ``-`` + suffix, which this does not match.
UNNAMED_AGENT_ID = re.compile(r"a[0-9a-f]{16}")

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9_.-]")
_NAME_DIGEST_LENGTH = 16
_KEY_NAME = "name"
_KEY_SUBAGENT_TYPE = "subagent_type"


def _session_dir(untracked_dir: Path, session_id: str) -> Path:
    """The per-session directory; the id is sanitised, never trusted as a path."""
    return untracked_dir / REGISTRY_SUBDIR / (_UNSAFE_CHARS.sub("_", session_id) or "unknown")


def _record_path(untracked_dir: Path, session_id: str, name: str) -> Path:
    """One file per (session, name); the digest keeps distinct names distinct."""
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:_NAME_DIGEST_LENGTH]
    return _session_dir(untracked_dir, session_id) / f"{digest}.json"


def record_dispatch(
    untracked_dir: Path, session_id: str, name: str, subagent_type: str | None
) -> None:
    """Record that ``name`` was dispatched as definition type ``subagent_type``.

    A dispatch that names no type is recorded with an empty one, so the name
    still resolves (to nothing) rather than being trusted as a type.
    """
    path = _record_path(untracked_dir, session_id, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {_KEY_NAME: name, _KEY_SUBAGENT_TYPE: subagent_type or ""}
    tmp_path = unique_temp_path(path)
    tmp_path.write_text(json.dumps(entry), encoding="utf-8")
    tmp_path.replace(path)


def effective_agent_type(
    untracked_dir: Path, session_id: str, agent_type: str, agent_id: str = ""
) -> str:
    """The definition type of the agent whose payload carried ``agent_type``.

    ``agent_id`` tells named from unnamed. An unnamed-shape id means
    ``agent_type`` is the definition type and no record is consulted (a stale
    record of an earlier teammate named like that type must not override it).
    Any other non-empty id is a named teammate: its type is the recorded one,
    and no record resolves to empty, so an unknown id format fails closed. With
    no id at all the payload is not a sub-agent's; a record is honoured and
    otherwise ``agent_type`` stands. A record that exists but cannot be read
    resolves to empty: fail closed.
    """
    if UNNAMED_AGENT_ID.fullmatch(agent_id):
        return agent_type
    path = _record_path(untracked_dir, session_id, agent_type)
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return agent_type if not agent_id else ""
    except (OSError, ValueError) as exc:
        log_and_continue(
            logger,
            exc,
            reason="a record that exists but cannot be read proves the name was dispatched, so it resolves to no type rather than being trusted as one",
            level=logging.WARNING,
        )
        return ""
    if not isinstance(entry, dict) or entry.get(_KEY_NAME) != agent_type:
        return ""
    recorded = entry.get(_KEY_SUBAGENT_TYPE)
    return recorded if isinstance(recorded, str) else ""
