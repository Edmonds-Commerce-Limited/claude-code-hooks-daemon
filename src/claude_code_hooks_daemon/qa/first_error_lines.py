"""A pytest plugin recording the first error line of every red test (00466 N196).

The QA tests stage reads pytest's console text, whose short summary cuts each
failure's message to the terminal width, and the gate's summary printed node
ids only. Ten errored tests were named with no cause: the reason (no daemon
was running) was in the shard's raw log alone.

This project's ``tests/conftest.py`` loads it through ``pytest_plugins``;
elsewhere it loads with ``-p claude_code_hooks_daemon.qa.first_error_lines``.
Never load it with ``-p`` in a coverage run: that imports the package before
pytest-cov starts, so its import-time code goes unmeasured (00466 N110).
Given ``--first-error-lines=PATH``, it appends one JSON record per failed or
errored test phase to PATH: ``{"nodeid", "when", "line"}``. Without the option
it writes nothing. ``attach_first_error_lines`` puts each line on its test's
record in ``tests.json`` as ``reason``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    import pytest

PLUGIN: Final[str] = "claude_code_hooks_daemon.qa.first_error_lines"
OPTION: Final[str] = "--first-error-lines"
_DEST: Final[str] = "first_error_lines"
_RECORDER_NAME: Final[str] = "first-error-lines-recorder"
_REASON_KEY: Final[str] = "reason"


def first_error_line(longrepr: object) -> str:
    """The first non-blank line of a report's error.

    A traceback's first line is a source frame, so its crash message is used
    instead: that is the ``ExceptionType: message`` line. A plain-string
    longrepr (a ``pytest.fail(pytrace=False)`` or a hook-set message) is used
    as it stands.
    """
    if longrepr is None:
        return ""
    crash = getattr(longrepr, "reprcrash", None)
    text = str(getattr(crash, "message", "")) if crash is not None else str(longrepr)
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        OPTION,
        dest=_DEST,
        default=None,
        help="Append each failed or errored test's first error line to this JSON-lines file.",
    )


class _Recorder:
    """Appends a record to ``path`` for every failed test phase."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if not report.failed:
            return
        record = {
            "nodeid": report.nodeid,
            "when": report.when,
            "line": first_error_line(report.longrepr),
        }
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")


def pytest_configure(config: pytest.Config) -> None:
    target = config.getoption(_DEST)
    if target is not None:
        config.pluginmanager.register(_Recorder(Path(target)), _RECORDER_NAME)


def read_first_error_lines(path: Path) -> dict[str, str]:
    """Node id to first error line; a missing file has none.

    The first record for a test wins, so a test that fails its call and then
    its teardown is described by the call.
    """
    if not path.is_file():
        return {}
    lines: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        record = json.loads(raw)
        lines.setdefault(str(record["nodeid"]), str(record["line"]))
    return lines


def attach_first_error_lines(tests: list[dict[str, Any]], path: Path) -> None:
    """Set ``reason`` on each test record whose node id has a recorded line."""
    lines = read_first_error_lines(path)
    for test in tests:
        line = lines.get(str(test.get("name", "")))
        if line:
            test[_REASON_KEY] = line
