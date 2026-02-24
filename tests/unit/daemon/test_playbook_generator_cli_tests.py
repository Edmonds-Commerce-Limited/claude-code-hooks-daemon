"""Tests for PlaybookGenerator CLI acceptance test integration."""

from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core import AcceptanceTest, Decision, Handler
from claude_code_hooks_daemon.core.cli_acceptance_test import CliAcceptanceTest
from claude_code_hooks_daemon.core.hook_result import HookResult
from claude_code_hooks_daemon.daemon.playbook_generator import PlaybookGenerator
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry


class MinimalHandler(Handler):
    """Minimal handler for playbook generator testing."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DESTRUCTIVE_GIT,
            priority=Priority.DESTRUCTIVE_GIT,
            terminal=False,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return []


class TestPlaybookGeneratorCliTests:
    """Tests for CLI acceptance test section in playbook."""

    def _make_generator(
        self, cli_tests: list[CliAcceptanceTest] | None = None
    ) -> PlaybookGenerator:
        """Create a PlaybookGenerator with optional CLI tests."""
        registry = HandlerRegistry()
        config: dict[str, Any] = {"pre_tool_use": {}}
        return PlaybookGenerator(
            config=config,
            registry=registry,
            cli_acceptance_tests=cli_tests,
        )

    def test_markdown_includes_cli_section_when_tests_provided(self) -> None:
        """Markdown output includes CLI Features section when tests exist."""
        cli_tests = [
            CliAcceptanceTest(
                title="Test restart advisory",
                description="Verify restart prints mode advisory",
                command="restart",
                expected_stdout_patterns=["Mode before restart"],
                expected_exit_code=0,
            ),
        ]
        gen = self._make_generator(cli_tests=cli_tests)
        markdown = gen.generate_markdown()

        assert "## CLI Feature Tests" in markdown
        assert "Test restart advisory" in markdown
        assert "Mode before restart" in markdown

    def test_markdown_excludes_cli_section_when_no_tests(self) -> None:
        """Markdown output has no CLI section when no CLI tests."""
        gen = self._make_generator(cli_tests=None)
        markdown = gen.generate_markdown()

        assert "## CLI Feature Tests" not in markdown

    def test_markdown_excludes_cli_section_when_empty_list(self) -> None:
        """Markdown output has no CLI section when empty list."""
        gen = self._make_generator(cli_tests=[])
        markdown = gen.generate_markdown()

        assert "## CLI Feature Tests" not in markdown

    def test_cli_test_shows_setup_and_cleanup(self) -> None:
        """CLI test renders setup and cleanup commands."""
        cli_tests = [
            CliAcceptanceTest(
                title="Advisory test",
                description="Tests advisory output",
                command="restart",
                expected_stdout_patterns=["advisory"],
                setup_commands=["set-mode unattended -m 'testing'"],
                cleanup_commands=["set-mode default"],
            ),
        ]
        gen = self._make_generator(cli_tests=cli_tests)
        markdown = gen.generate_markdown()

        assert "set-mode unattended" in markdown
        assert "set-mode default" in markdown
        assert "**Setup**" in markdown
        assert "**Cleanup**" in markdown

    def test_cli_test_shows_expected_patterns(self) -> None:
        """CLI test renders expected stdout patterns."""
        cli_tests = [
            CliAcceptanceTest(
                title="Pattern test",
                description="Tests patterns",
                command="restart",
                expected_stdout_patterns=["Mode before restart", "set-mode"],
            ),
        ]
        gen = self._make_generator(cli_tests=cli_tests)
        markdown = gen.generate_markdown()

        assert "`Mode before restart`" in markdown
        assert "`set-mode`" in markdown

    def test_cli_test_shows_expected_exit_code(self) -> None:
        """CLI test renders expected exit code."""
        cli_tests = [
            CliAcceptanceTest(
                title="Exit code test",
                description="Tests exit code",
                command="restart",
                expected_stdout_patterns=["ok"],
                expected_exit_code=0,
            ),
        ]
        gen = self._make_generator(cli_tests=cli_tests)
        markdown = gen.generate_markdown()

        assert "Exit Code**: 0" in markdown

    def test_cli_tests_included_in_summary_count(self) -> None:
        """CLI tests are counted in the total test summary."""
        cli_tests = [
            CliAcceptanceTest(
                title="Test 1",
                description="First",
                command="cmd1",
                expected_stdout_patterns=["pat"],
            ),
            CliAcceptanceTest(
                title="Test 2",
                description="Second",
                command="cmd2",
                expected_stdout_patterns=["pat"],
            ),
        ]
        gen = self._make_generator(cli_tests=cli_tests)
        markdown = gen.generate_markdown()

        # Should count these 2 CLI tests in total
        assert "**Total Tests**: 2" in markdown

    def test_json_includes_cli_tests(self) -> None:
        """JSON output includes CLI tests with correct fields."""
        cli_tests = [
            CliAcceptanceTest(
                title="JSON test",
                description="Tests JSON",
                command="restart",
                expected_stdout_patterns=["advisory"],
                expected_exit_code=0,
                setup_commands=["setup"],
                cleanup_commands=["cleanup"],
            ),
        ]
        gen = self._make_generator(cli_tests=cli_tests)
        json_tests = gen.generate_json()

        cli_entries = [t for t in json_tests if t.get("source") == "cli"]
        assert len(cli_entries) == 1

        entry = cli_entries[0]
        assert entry["title"] == "JSON test"
        assert entry["command"] == "restart"
        assert entry["expected_stdout_patterns"] == ["advisory"]
        assert entry["expected_exit_code"] == 0
        assert entry["source"] == "cli"
        assert entry["setup_commands"] == ["setup"]
        assert entry["cleanup_commands"] == ["cleanup"]
