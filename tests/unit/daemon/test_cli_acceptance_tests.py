"""Tests for CLI acceptance test definitions."""

from claude_code_hooks_daemon.core.cli_acceptance_test import CliAcceptanceTest
from claude_code_hooks_daemon.daemon.cli_acceptance_tests import get_cli_acceptance_tests


class TestGetCliAcceptanceTests:
    """Tests for get_cli_acceptance_tests function."""

    def test_returns_list(self) -> None:
        """Returns a list of CliAcceptanceTest objects."""
        tests = get_cli_acceptance_tests()
        assert isinstance(tests, list)
        assert len(tests) > 0

    def test_all_items_are_cli_acceptance_tests(self) -> None:
        """Every item is a CliAcceptanceTest instance."""
        tests = get_cli_acceptance_tests()
        for test in tests:
            assert isinstance(test, CliAcceptanceTest)

    def test_restart_mode_advisory_test_exists(self) -> None:
        """Restart mode advisory test is included."""
        tests = get_cli_acceptance_tests()
        titles = [t.title for t in tests]
        assert any("restart" in title.lower() and "mode" in title.lower() for title in titles)

    def test_restart_mode_advisory_has_setup_and_cleanup(self) -> None:
        """Restart mode advisory test has setup (set mode) and cleanup (reset mode)."""
        tests = get_cli_acceptance_tests()
        restart_tests = [t for t in tests if "restart" in t.title.lower()]
        assert len(restart_tests) >= 1

        test = restart_tests[0]
        assert test.setup_commands is not None
        assert len(test.setup_commands) > 0
        assert test.cleanup_commands is not None
        assert len(test.cleanup_commands) > 0

    def test_all_tests_have_expected_patterns(self) -> None:
        """Every test has at least one expected stdout pattern."""
        tests = get_cli_acceptance_tests()
        for test in tests:
            assert len(test.expected_stdout_patterns) > 0, f"Test '{test.title}' has no patterns"

    def test_check_truth_changes_test_exists(self) -> None:
        """check-truth-changes acceptance test is included (Plan 00118)."""
        tests = get_cli_acceptance_tests()
        truth_tests = [t for t in tests if "truth-change" in t.title.lower()]
        assert len(truth_tests) >= 1

    def test_check_truth_changes_surfaces_plan_number_entry(self) -> None:
        """The plan-number truth-change surfaces for a range spanning v3.16.0."""
        tests = get_cli_acceptance_tests()
        truth_tests = [t for t in tests if "truth-change" in t.title.lower()]
        assert truth_tests, "no truth-changes CLI acceptance test registered"

        test = truth_tests[0]
        # Exercises the real command with a --from before v3.16.0
        assert "check-truth-changes" in test.command
        assert "--from 3.11.0" in test.command
        # Expects the plan-number git-counter truth to be printed
        joined = " ".join(test.expected_stdout_patterns)
        assert "hooksdaemon.latestPlanNumber" in joined
