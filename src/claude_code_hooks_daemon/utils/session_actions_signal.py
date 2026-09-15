"""The session-actions directive signal: SessionStart -> supervisor (Plan 00416).

Plan 00416's diagnosis is that SessionStart output is delivered correctly and
simply not ACTED ON: injected context is scenery, not a turn. Its layer 2
answer is that the ccy supervisor types ONE turn-level directive after session
start, telling the agent to action every ``ACTION_REQUIRED`` item. That works
because of CHANNEL rather than volume -- the owner proved it on another
machine with a single typed line, after which the agent worked through the
whole start-up block unprompted.

This is the SENSOR half: one small JSON file per session, dropped into the
same context-sidecar directory the supervisor already watches, mirroring
``operator_signal`` and ``model_downgrade_signal``. The ACTUATOR half
(``load_session_actions_signal`` / ``_render_session_actions_message`` in the
standalone ``.claude/ccy/claude-supervise.py``) is a separate module by
necessity: the supervisor is a stdlib-only script that cannot import this
package. Path and field names live here and are pinned to the supervisor's own
copies by ``tests/unit/supervise/test_session_actions_signal.py``, so the two
cannot drift apart.

**The payload carries no text at all, and that is the design.** It is a
positive integer COUNT and nothing else; every word the agent ever reads is
composed by the supervisor from a fixed template, with the count as the only
interpolated value. ``operator_signal`` adopted that shape because it is the
one channel reachable from OUTSIDE the container. This one adopts it for a
different reason: a nudge whose entire message is "go read what you were
already told" never needed to carry prose, and a channel that cannot carry
prose cannot later be widened into one by accident. Contrast ``goal-intent``,
which does carry operator-composed text and therefore needs a header
constant, a length cap and a line cap to keep it honest.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Final

from claude_code_hooks_daemon.utils.temp_names import unique_temp_path

logger = logging.getLogger(__name__)

#: Written beside the context sidecar and every other supervisor signal -- the
#: supervisor already watches this directory, so no new transport is needed.
SIGNAL_SUBDIR: Final[str] = "context-sidecar"

#: Deliberately NOT ``.json``: the supervisor's sidecar reader globs that
#: extension and would otherwise take this for a context sidecar.
SIGNAL_SUFFIX: Final[str] = ".session-actions"

_SESSION_ID_FALLBACK: Final[str] = "unknown"
_UNSAFE_SESSION_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9_.-]")

FIELD_TS: Final[str] = "ts"
FIELD_SESSION_ID: Final[str] = "session_id"
FIELD_COUNT: Final[str] = "count"


def _session_stem(session_id: str) -> str:
    """A filesystem-safe stem for ``session_id``.

    The id arrives in a hook payload, so it is untrusted: separators and
    traversal dots are collapsed rather than allowed to steer the write out
    of the signal directory.
    """
    stem = _UNSAFE_SESSION_CHARS.sub("_", session_id.strip())
    return stem or _SESSION_ID_FALLBACK


def signal_path(daemon_untracked_dir: Path, session_id: str) -> Path:
    """The signal file path for ``session_id``."""
    return daemon_untracked_dir / SIGNAL_SUBDIR / f"{_session_stem(session_id)}{SIGNAL_SUFFIX}"


def write_session_actions_signal(
    daemon_untracked_dir: Path,
    *,
    session_id: str,
    count: int,
    now: float,
) -> Path:
    """Atomically write a ``<session>.session-actions`` signal file.

    ``count`` must be a positive ``int``. Zero is refused rather than written:
    "nothing to action" is not a directive worth typing, and the caller is
    expected to :func:`clear_session_actions_signal` instead -- so a zero here
    is a caller bug and should surface as one. ``bool`` is rejected too (see
    the check below), so ``True`` cannot silently become a one-item directive.

    This function never composes the sentence the agent will see; it only
    carries a number. Rendering is entirely the supervisor's job (see the
    module docstring), and that split is what keeps this channel unable to
    carry arbitrary text.

    Raises:
        ValueError: ``count`` is not a positive integer.
        OSError: the write itself failed -- propagated, so a caller that
            cares can report it. The SessionStart sensor deliberately
            swallows it; a best-effort signal must never cost the agent the
            rest of the session-start block.
    """
    # `type(...) is not int` rather than `isinstance`, deliberately: `bool` is
    # an `int` SUBCLASS in Python, so `isinstance(True, int)` is True and an
    # isinstance check cannot reject `True` -- which would silently become a
    # one-item directive. This one expression rejects a bool, a float and a
    # string together.
    if type(count) is not int or count <= 0:
        raise ValueError(f"count must be a positive integer, got {count!r}")

    final_path = signal_path(daemon_untracked_dir, session_id)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        FIELD_TS: now,
        FIELD_SESSION_ID: session_id,
        FIELD_COUNT: count,
    }
    tmp_path = unique_temp_path(final_path)
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    tmp_path.replace(final_path)
    return final_path


def clear_session_actions_signal(daemon_untracked_dir: Path, *, session_id: str) -> None:
    """Drop any pending directive for ``session_id``.

    Called whenever a session start finds nothing ``ACTION_REQUIRED``. A
    resumed session whose problem was fixed in between must not be nudged
    about it, and declining to REWRITE the file is not the same as retracting
    it -- the supervisor would still find the old one and type the old count.

    Never raises: a missing file is the common case (most sessions are
    healthy), and an unreadable directory is not worth failing a session
    start over.
    """
    try:
        signal_path(daemon_untracked_dir, session_id).unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("session_actions_signal: could not clear signal: %s", exc)
