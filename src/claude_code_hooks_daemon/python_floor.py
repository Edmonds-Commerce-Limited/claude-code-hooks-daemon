"""The one declared minimum Python, and the guard every entry point calls.

This file is deliberately written in the oldest syntax that still parses
everywhere an arbitrary interpreter might start the daemon: no ``X | Y``
annotations, no ``from __future__`` import, no third-party or package imports.
It can therefore run, and refuse, under an interpreter far older than the code
it protects (f-strings, 3.6+, are its newest syntax).

Entry points call :func:`require_min_python` BEFORE their first construct that
needs more than the oldest interpreter they accept:

* Python scripts (``daemon/paths.py``, ``daemon/signal_standalone.py``,
  ``install.py``) load this file by path with ``runpy`` and call the guard.
* ``python -m claude_code_hooks_daemon...`` runs the package ``__init__`` first,
  which calls the guard before importing anything else.
* A launcher whose own target cannot even parse on an old interpreter
  (``bin/hooks-daemon`` before it execs ``signal_standalone.py``) runs this file
  as a script: ``python3 python_floor.py <entry-point-name>``.

``MIN_PYTHON`` must equal ``requires-python`` in ``pyproject.toml``;
``tests/unit/test_python_floor.py`` fails if the two drift.
"""

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

#: The lowest ``(major, minor)`` any entry point accepts.
MIN_PYTHON = (3, 11)


def _dotted(parts: "Sequence[int]") -> str:
    return ".".join(str(part) for part in parts)


def refusal_line(entry_point: str, version_info: "Sequence[int]") -> str:
    """The single line an entry point prints when the interpreter is too old."""
    return f"{entry_point}: needs Python {_dotted(MIN_PYTHON)} or newer, but this is Python {_dotted(tuple(version_info[:3]))} ({sys.executable})."


def require_min_python(
    entry_point: str, version_info: "Sequence[int]" = sys.version_info[:3]
) -> None:
    """Exit with status 1 and one line on stderr when below :data:`MIN_PYTHON`."""
    if tuple(version_info[:2]) >= MIN_PYTHON:
        return
    sys.stderr.write(refusal_line(entry_point, version_info) + "\n")
    sys.exit(1)


if __name__ == "__main__":
    require_min_python(sys.argv[1] if len(sys.argv) > 1 else "python_floor.py")
