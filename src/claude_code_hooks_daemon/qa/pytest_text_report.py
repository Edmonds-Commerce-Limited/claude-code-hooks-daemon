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

# pytest's own verdict lives under this banner, and ONLY the text below it is
# scraped for node ids. The captured stream is pytest's output plus whatever
# subprocesses wrote to the inherited file descriptors, and this project's
# suite starts real daemon processes — so a log line beginning with "ERROR"
# was being read as a failing test and named in a run that passed cleanly.
# Re-running the named test then proved nothing, because it had never failed.
#
# Safe to require: pytest emits this section for failures and errors by
# DEFAULT, verified by running a failing suite with addopts overridden to
# empty — the output is byte-identical once colour is stripped. The project's
# `-ra` only widens which OTHER outcomes get listed, so it is not load-bearing
# here and removing it would not blind this parser.
#
# No banner therefore means no verdict to scrape. The counts are parsed
# separately from the totals line and remain the sole basis for pass/fail
# either way, so a missing banner can never turn a red run green.
_SUMMARY_SECTION_MARKER = "short test summary info"

_PASSED_COUNT_PATTERN = re.compile(r"(\d+) passed")
_FAILED_COUNT_PATTERN = re.compile(r"(\d+) failed")
_SKIPPED_COUNT_PATTERN = re.compile(r"(\d+) skipped")
# pytest counts a fixture/setup/teardown failure as an ERROR and never as a
# "failed", so a summary can read "17820 passed, 5 skipped, 1 error" with the
# word "failed" absent entirely. Scraping only the failed count therefore read
# a red run as green while the short summary's `ERROR <node id>` line still
# landed in ``failed_tests`` — a report naming a broken test and declaring
# itself passing in the same breath. Matches both "1 error" and "2 errors".
_ERROR_COUNT_PATTERN = re.compile(r"(\d+) error")


def strip_ansi(text: str) -> str:
    """Remove SGR escape sequences so patterns match the plain text."""
    return _ANSI_ESCAPE_PATTERN.sub("", text)


def _summary_section(plain: str) -> str:
    """The text below pytest's short-summary banner, or "" when absent.

    Args:
        plain: ANSI-stripped pytest output.

    Returns:
        Everything after the banner line. An empty string when there is no
        banner, which means pytest reported no failures or errors — returning
        the whole text there is what let an unrelated log line be read as a
        verdict.
    """
    index = plain.find(_SUMMARY_SECTION_MARKER)
    if index == -1:
        return ""
    newline = plain.find("\n", index)
    return "" if newline == -1 else plain[newline + 1 :]


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
    errors = _count(_ERROR_COUNT_PATTERN, plain)

    # De-duplicated while preserving order: a node id can appear both in the
    # short summary and in a rerun/verbose section of the same output.
    failed_tests: list[str] = []
    for node_id in _FAILED_LINE_PATTERN.findall(_summary_section(plain)):
        if node_id not in failed_tests:
            failed_tests.append(node_id)

    return {
        "total": passed + failed + skipped + errors,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errors": errors,
        # An ERRORED run is a red run. Deriving this from the failed count
        # alone let a suite whose fixtures blew up report itself as green.
        "passed_all": failed == 0 and errors == 0,
        "failed_tests": failed_tests,
    }
