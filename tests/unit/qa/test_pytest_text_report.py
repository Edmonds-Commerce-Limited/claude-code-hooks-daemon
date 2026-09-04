"""Tests for parsing pytest's text output (Plan 00226).

When `pytest-json-report` is absent, `scripts/qa/run_tests.sh` falls back to
scraping pytest's console output — and scraped only the COUNTS, discarding
which tests failed. A red QA run therefore said "2 failed" and gave the reader
no way to learn what broke short of re-running the suite. During Plan 00224 one
of two real failures was never identified because of this.

Every fixture below is REAL captured pytest output, escape codes included. The
format is not written from memory on purpose: pytest colours its short summary
even when redirected to a file, and the escape sequences sit INSIDE the node id
(``::\\x1b[1mtest_name\\x1b[0m``), so a naive ``^FAILED (\\S+)`` captures a name
polluted with terminal control characters.
"""

from __future__ import annotations

from claude_code_hooks_daemon.qa.pytest_text_report import parse_pytest_text_output

# Captured verbatim from `pytest --tb=short --no-cov` on a fixture package.
#
# The banner is part of the capture, not decoration: only the text BELOW it is
# scraped for node ids, because the captured stream also carries subprocess
# log output and an unrelated line beginning with "ERROR" was otherwise read
# as a verdict. pytest emits this section for failures and errors by default,
# independently of the project's `-ra` setting.
_SUMMARY_BANNER = (
    "\x1b[36m\x1b[1m=========================== short test summary info "
    "============================\x1b[0m\n"
)

_REAL_RED_OUTPUT = _SUMMARY_BANNER + (
    "\x1b[31mFAILED\x1b[0m untracked/pytestfix/test_sample_failures.py::"
    "\x1b[1mtest_one_that_fails\x1b[0m - assert 1 == 2\n"
    "\x1b[31mFAILED\x1b[0m untracked/pytestfix/test_sample_failures.py::"
    "\x1b[1mtest_another_that_fails\x1b[0m - ValueError: boom\n"
    "\x1b[31m========================= \x1b[31m\x1b[1m2 failed\x1b[0m, "
    "\x1b[32m1 passed\x1b[0m\x1b[31m in 0.10s\x1b[0m\x1b[31m "
    "==========================\x1b[0m\n"
)

_REAL_GREEN_OUTPUT = (
    "\x1b[32m\x1b[1m12528 passed\x1b[0m, \x1b[33m4 skipped\x1b[0m\x1b[32m in 214.11s\x1b[0m\n"
)


class TestFailingTestsAreNamed:
    def test_every_failing_node_id_is_extracted(self) -> None:
        report = parse_pytest_text_output(_REAL_RED_OUTPUT)
        assert report["failed_tests"] == [
            "untracked/pytestfix/test_sample_failures.py::test_one_that_fails",
            "untracked/pytestfix/test_sample_failures.py::test_another_that_fails",
        ]

    def test_node_ids_carry_no_escape_sequences(self) -> None:
        """The whole point of using real output as the fixture."""
        report = parse_pytest_text_output(_REAL_RED_OUTPUT)
        assert report["failed_tests"]
        for node_id in report["failed_tests"]:
            assert "\x1b" not in node_id
            assert "[1m" not in node_id

    def test_the_failure_reason_is_not_glued_onto_the_node_id(self) -> None:
        report = parse_pytest_text_output(_REAL_RED_OUTPUT)
        assert not any("assert" in node_id for node_id in report["failed_tests"])
        assert not any(" - " in node_id for node_id in report["failed_tests"])


class TestCountsStillParse:
    """The counts already worked; extracting the parser must not regress them."""

    def test_red_counts(self) -> None:
        report = parse_pytest_text_output(_REAL_RED_OUTPUT)
        assert report["passed"] == 1
        assert report["failed"] == 2
        assert report["skipped"] == 0
        assert report["total"] == 3
        assert report["passed_all"] is False

    def test_green_counts(self) -> None:
        report = parse_pytest_text_output(_REAL_GREEN_OUTPUT)
        assert report["passed"] == 12528
        assert report["failed"] == 0
        assert report["skipped"] == 4
        assert report["passed_all"] is True

    def test_a_green_run_names_no_failures(self) -> None:
        assert parse_pytest_text_output(_REAL_GREEN_OUTPUT)["failed_tests"] == []


class TestDegradesSafely:
    def test_empty_output_is_handled(self) -> None:
        report = parse_pytest_text_output("")
        assert report["total"] == 0
        assert report["failed_tests"] == []
        assert report["passed_all"] is True

    def test_output_without_a_summary_line_is_handled(self) -> None:
        report = parse_pytest_text_output("collecting ...\ninterrupted\n")
        assert report["failed_tests"] == []

    def test_plain_uncoloured_output_still_parses(self) -> None:
        """CI often disables colour; the same parser must cope."""
        plain = (
            "=========================== short test summary info "
            "============================\n"
            "FAILED tests/unit/test_thing.py::test_case - AssertionError\n1 failed in 0.1s\n"
        )
        report = parse_pytest_text_output(plain)
        assert report["failed_tests"] == ["tests/unit/test_thing.py::test_case"]
        assert report["failed"] == 1


# Captured verbatim from a real `pytest --tb=short --no-cov` run whose fixture
# raised during teardown. pytest counts this as an ERROR, not a failure: the
# summary line says "1 error" and never says "failed", while the short summary
# still names the node id. That asymmetry is the whole point of these tests.
_REAL_ERROR_OUTPUT = _SUMMARY_BANNER + (
    "\x1b[31mERROR\x1b[0m untracked/pytestfix/test_sample_error.py::"
    "\x1b[1mtest_passes_but_teardown_errors\x1b[0m - RuntimeError: teardown boom\n"
    "\x1b[31m========================== \x1b[32m2 passed\x1b[0m, "
    "\x1b[31m\x1b[1m1 error\x1b[0m\x1b[31m in 0.05s\x1b[0m\x1b[31m "
    "==========================\x1b[0m\n"
)


class TestErroredRunsAreNotReportedAsGreen:
    """An ERROR is a red run, and the counts must say so.

    pytest reports a fixture/setup/teardown failure as an "error", never as a
    "failed", so a parser that scrapes only `(\\d+) failed` sees zero and
    concludes the suite is green. The node id still lands in `failed_tests`,
    which produced the giveaway symptom: a report simultaneously claiming
    `passed_all: True` and naming a failing test.

    The gate itself survives this because `llm_qa.py` also cross-checks the
    tool's exit code and pytest exits non-zero on an error. That makes this a
    latent bug rather than a masked failure — but `tests.json` is read on its
    own by other consumers, and a report that contradicts itself cannot be
    relied on by any of them.
    """

    def test_the_errored_node_id_is_named(self) -> None:
        report = parse_pytest_text_output(_REAL_ERROR_OUTPUT)

        assert report["failed_tests"] == [
            "untracked/pytestfix/test_sample_error.py::test_passes_but_teardown_errors"
        ]

    def test_an_error_is_counted(self) -> None:
        assert parse_pytest_text_output(_REAL_ERROR_OUTPUT)["errors"] == 1

    def test_an_errored_run_is_not_passed_all(self) -> None:
        """The defect, stated directly."""
        assert parse_pytest_text_output(_REAL_ERROR_OUTPUT)["passed_all"] is False

    def test_the_report_never_contradicts_itself(self) -> None:
        """The invariant that would have caught this without knowing the cause.

        Naming a failing test while declaring the run green is incoherent
        regardless of which count pytest happened to use, so assert the
        relationship rather than the specific mechanism.
        """
        report = parse_pytest_text_output(_REAL_ERROR_OUTPUT)

        assert not (report["failed_tests"] and report["passed_all"])

    def test_errors_are_included_in_the_total(self) -> None:
        report = parse_pytest_text_output(_REAL_ERROR_OUTPUT)

        assert report["total"] == report["passed"] + report["failed"] + (
            report["skipped"] + report["errors"]
        )

    def test_a_green_run_reports_no_errors(self) -> None:
        assert parse_pytest_text_output(_REAL_GREEN_OUTPUT)["errors"] == 0

    def test_a_failed_run_is_still_red(self) -> None:
        """The pre-existing failure path must be untouched by the error path."""
        report = parse_pytest_text_output(_REAL_RED_OUTPUT)

        assert report["passed_all"] is False
        assert report["failed"] == 2


# A GREEN run whose captured stream also carries a stray line beginning with
# "ERROR". pytest tees subprocess stdout/stderr into the same log, and this
# project's suite starts real daemon processes, so arbitrary log lines land
# here alongside pytest's own output. `PYTEST_CURRENT_TEST` carries the node
# id, which is how such a line can name a real test.
_GREEN_OUTPUT_WITH_STRAY_ERROR_LOG = (
    "ERROR    tests/integration/test_daemon_smoke.py::TestDaemonSmoke::"
    "test_daemon_processes_session_start_hook (call) socket closed early\n"
    "\x1b[32m\x1b[1m17820 passed\x1b[0m, \x1b[33m5 skipped\x1b[0m"
    "\x1b[32m in 214.11s\x1b[0m\n"
)


class TestOnlyPytestsOwnVerdictIsScraped:
    """A stray log line must not manufacture a failing test.

    ``^(?:FAILED|ERROR)\\s+(\\S+)`` was applied to the ENTIRE captured stream,
    which is pytest's output plus anything subprocesses wrote to the inherited
    file descriptors. A daemon log line starting with ``ERROR`` therefore
    produced a failing node id in a run that passed cleanly — the report named
    a test that never failed, and re-running that test in isolation proved
    nothing because it was green all along.

    Scoping the scrape to pytest's own ``short test summary info`` section is
    correct whatever the stray line happened to be: anything outside that
    section is by definition not pytest's verdict.
    """

    def test_a_stray_error_log_line_names_no_failure(self) -> None:
        report = parse_pytest_text_output(_GREEN_OUTPUT_WITH_STRAY_ERROR_LOG)

        assert report["failed_tests"] == []

    def test_such_a_run_is_still_green(self) -> None:
        report = parse_pytest_text_output(_GREEN_OUTPUT_WITH_STRAY_ERROR_LOG)

        assert report["passed_all"] is True
        assert report["passed"] == 17820

    def test_the_invariant_holds_for_the_stray_log_case_too(self) -> None:
        """The same self-consistency rule, against the other way of breaking it."""
        report = parse_pytest_text_output(_GREEN_OUTPUT_WITH_STRAY_ERROR_LOG)

        assert not (report["failed_tests"] and report["passed_all"])
