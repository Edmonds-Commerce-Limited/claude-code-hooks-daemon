"""Reduce a log record to the part of it the daemon wrote itself.

`bin/hooks-daemon bug-report` captures a window of daemon logs into a report
generated to be SHARED, on a tracker that is public and that no later edit
retracts. Scrubbing rewrites the project root, `$HOME`, the git remote and the
hostname — and a real run of the scrubbed command showed that is nowhere near
enough. The window held whole `hook_input` payloads: the verbatim Bash command,
`session_name` (free text a user wrote, so in a client project it can say
anything), `session_id`, `prompt_id` and `tool_use_id`. A path rule touches
none of that.

Scrubbing harder is the wrong response, because what a 100-line window happens
to contain is not predictable — it is whatever the user was doing in the
seconds before they asked for the report. The fix is to capture less.

The split that makes this safe is available by CONSTRUCTION, not by inspection:

``the template is ours, the arguments are the client's``
    `logger.debug("PRE_TOOL_USE hook_input:\\n%s", json.dumps(payload))` is a
    developer-authored format string plus a runtime value. Because the daemon
    logs `%s`-style at the overwhelming majority of its call sites, the two are
    still separable when a record is rendered, and the format string can be
    published unconditionally.

``a payload is a structure; a daemon fact is a short scalar``
    The handler names, event types, counts and durations that make the window
    worth reading are short scalars. A dict or a list is a payload whatever its
    size; an over-long string is a dump whatever its type. Neither test asks
    what a value MEANS, which is the same mistake — judging content by how it
    looks — that shipped three false positives in Plan 00401.

Deliberately NOT covered, because pretending otherwise is worse than saying it:
an exception message reaching the report through `exc_info` is rendered by the
formatter from the exception itself, not from `record.args`, so it is not
elided here. `scrub_report` still passes over it, and the synthetic-repro rule
in Plan 00403 Phase 2 is what keeps client material out of a report in the
first place. This layer narrows the log window; it does not sanitise it.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Final

#: Longest string argument published as-is. A handler name, an event type or a
#: file path sits well inside this; a serialised payload does not. The bound is
#: deliberately generous — a wrongly elided value costs one round trip asking
#: for detail, while a wrongly published one cannot be taken back, and those two
#: costs are not comparable.
MAX_INLINE_ARGUMENT_LENGTH: Final[int] = 120

#: Types published verbatim. Everything else is a structure, and a structure
#: reaching a log call is a payload rather than a fact about the daemon.
#: `bool` and `int` matter here for a second reason: replacing them with text
#: would make a `%d` placeholder fail to resolve.
_SCALAR_TYPES: Final[tuple[type, ...]] = (bool, int, float)


def _elide_value(value: object) -> object:
    """One argument, reduced to what is safe to publish.

    Returns the value itself when it is a short scalar, and a description of
    what was removed otherwise — the reader needs to know detail existed, or
    they cannot ask for it.
    """
    if value is None or isinstance(value, _SCALAR_TYPES):
        return value
    if isinstance(value, str):
        if len(value) <= MAX_INLINE_ARGUMENT_LENGTH:
            return value
        return f"<elided {len(value)}-character str>"
    return f"<elided {type(value).__name__}>"


def _elide_args(args: Any, template: str) -> Any:
    """Elide a record's argument set, preserving the shape logging expects.

    `LogRecord.__init__` replaces a lone non-empty Mapping argument with the
    mapping ITSELF, so by the time a record reaches the buffer,
    ``logger.debug("hook_input: %s", payload_dict)`` and
    ``logger.debug("user=%(user)s", {...})`` have identical ``args``. The
    distinction matters enormously — the first is the single worst leak in the
    daemon's log output and the second is developer-authored throughout — and
    the values cannot supply it.

    The TEMPLATE can, and the template is ours: mapping-style formatting is
    exactly the case that writes `%(`. Its keys are named in that template, so
    they are as publishable as the rest of it and only the values are elided.
    Without `%(`, the dict is a positional argument stdlib unwrapped, and it is
    re-wrapped here so it can be elided whole.
    """
    if isinstance(args, dict):
        if "%(" in template:
            return {key: _elide_value(value) for key, value in args.items()}
        return (_elide_value(args),)
    return tuple(_elide_value(value) for value in args)


def elide_record_arguments(record: logging.LogRecord) -> logging.LogRecord:
    """A copy of ``record`` carrying its format string but not its values.

    Args:
        record: A record from the daemon's in-memory buffer.

    Returns:
        The record itself when it interpolates nothing, or a shallow copy whose
        arguments have been elided. A COPY is essential: the buffer holds one
        set of records shared by every reader, and `hooks-daemon logs` serves
        the same objects to an operator inspecting their own machine, where
        there is nothing to protect them from and full fidelity is the point.
    """
    if not record.args:
        return record
    elided = copy.copy(record)
    elided.args = _elide_args(record.args, str(record.msg))
    return elided
