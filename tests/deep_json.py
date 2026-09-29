"""Hook input nested deeper than the forwarder's ``python3`` can handle.

``init.sh`` parses a hook's input with ``json.loads`` and wraps it in the
daemon's request envelope with ``json.dumps``; on input nested deep enough
either raises RecursionError. How deep differs by interpreter: about 1000 on
3.11 (the recursion limit), about 10000 on 3.12 and 3.13 (the C recursion
limit), and on 3.14 wherever the C stack runs out (tens of thousands with an
8 MiB stack, varying from run to run with where the stack starts). So a fixed
depth near one of those limits is too deep on one interpreter and parses on
the next; ``TOO_DEEP_FOR_ANY_PYTHON`` is past all of them.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Final

#: Past every supported interpreter's limit: 3.14's is bounded by the C stack,
#: and a million levels needs far more stack than any default gives.
TOO_DEEP_FOR_ANY_PYTHON: Final = 1_000_000


def nested_call(depth: int, markers: Mapping[str, str] | None = None) -> str:
    """An MCP-shaped PreToolUse input whose tool_input nests ``depth`` lists,
    carrying ``markers`` (a probe's ``synthetic_source`` and ``probe_as``)."""
    marker_fields = "".join(
        f", {json.dumps(key)}: {json.dumps(value)}" for key, value in (markers or {}).items()
    )
    return (
        '{"tool_name": "mcp__deep__tool", "tool_input": {"value": '
        + "[" * depth
        + "]" * depth
        + "}"
        + marker_fields
        + "}"
    )
