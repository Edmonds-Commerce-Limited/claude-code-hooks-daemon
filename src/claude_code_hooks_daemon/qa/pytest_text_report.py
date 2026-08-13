"""Parse pytest's console output into a QA report (Plan 00226).

`scripts/qa/run_tests.sh` prefers `pytest-json-report`, but falls back to
scraping pytest's console output when that plugin is not installed — which is
the path this project actually takes. The fallback recorded only the COUNTS, so
a red QA run reported "2 failed" and gave the reader no way to learn WHICH,
short of re-running the whole suite. During Plan 00224 one of two real failures
was never identified for exactly this reason.

The logic lives here rather than in a shell heredoc so it can be unit-tested
against real captured output.
"""

from __future__ import annotations

import re
from typing import Any

# pytest colours its short summary even when stdout is redirected to a file,
# and the escape sequences sit INSIDE the node id
# ("path::\x1b[1mtest_name\x1b[0m"), so they must be stripped before the node
# id is read rather than trimmed from the ends afterwards.
_ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*m")

# "FAILED path::test_name - AssertionError: ..." — the reason after " - " is
# deliberately not captured; the node id is what is missing, and a reason can
# itself contain " - ".
_FAILED_LINE_PATTERN = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)

_PASSED_COUNT_PATTERN = re.compile(r"(\d+) passed")
_FAILED_COUNT_PATTERN = re.compile(r"(\d+) failed")
_SKIPPED_COUNT_PATTERN = re.compile(r"(\d+) skipped")


def strip_ansi(text: str) -> str:
    """Remove SGR escape sequences so patterns match the plain text."""
    return _ANSI_ESCAPE_PATTERN.sub("", text)


def _count(pattern: re.Pattern[str], text: str) -> int:
    match = pattern.search(text)
    return int(match.group(1)) if match else 0


def parse_pytest_text_output(content: str) -> dict[str, Any]:
    """Extract counts and failing node ids from pytest console output.

    Args:
        content: Raw pytest stdout/stderr, with or without ANSI colouring.

    Returns:
        Mapping with ``total``, ``passed``, ``failed``, ``skipped``,
        ``passed_all`` and ``failed_tests`` (the node ids, in the order pytest
        reported them).
    """
    plain = strip_ansi(content)

    passed = _count(_PASSED_COUNT_PATTERN, plain)
    failed = _count(_FAILED_COUNT_PATTERN, plain)
    skipped = _count(_SKIPPED_COUNT_PATTERN, plain)

    # De-duplicated while preserving order: a node id can appear both in the
    # short summary and in a rerun/verbose section of the same output.
    failed_tests: list[str] = []
    for node_id in _FAILED_LINE_PATTERN.findall(plain):
        if node_id not in failed_tests:
            failed_tests.append(node_id)

    return {
        "total": passed + failed + skipped,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "passed_all": failed == 0,
        "failed_tests": failed_tests,
    }
