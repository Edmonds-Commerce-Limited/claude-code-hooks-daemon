"""Tests for NpmCommandHandler.

Comprehensive test coverage for npm/npx command enforcement.
"""

from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.npm_command import NpmCommandHandler


class TestNpmCommandHandler:
    """Test suite for NpmCommandHandler."""

    @pytest.fixture
    def handler(self) -> NpmCommandHandler:
        """Create handler instance with llm commands detected (enforcement mode)."""
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command.has_llm_commands_in_package_json",
            return_value=True,
        ):
            return NpmCommandHandler()

    @pytest.fixture
    def advisory_handler(self) -> NpmCommandHandler:
        """Create handler instance without llm commands (advisory mode)."""
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command.has_llm_commands_in_package_json",
            return_value=False,
        ):
            return NpmCommandHandler()

    # Tests for matches() method - npm run commands

    def test_matches_npm_run_non_llm_command(self, handler: NpmCommandHandler) -> None:
        """Handler matches npm run command without llm: prefix."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npm_run_with_colon_non_llm(self, handler: NpmCommandHandler) -> None:
        """Handler matches npm run command with colon but not llm: prefix."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build:prod"},
        }
        assert handler.matches(hook_input) is True

    def test_does_not_match_npm_run_llm_prefixed(self, handler: NpmCommandHandler) -> None:
        """Handler does not match npm run commands already prefixed with llm:."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run llm:build"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_npm_run_allowed_command_clean(self, handler: NpmCommandHandler) -> None:
        """Handler does not match whitelisted command: clean."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run clean"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_npm_run_allowed_command_dev_permissive(
        self, handler: NpmCommandHandler
    ) -> None:
        """Handler does not match whitelisted command: dev:permissive."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run dev:permissive"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_npm_run_with_extra_spaces(self, handler: NpmCommandHandler) -> None:
        """Handler matches npm run with extra spaces."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm  run  test"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npm_run_with_dashes_in_command(self, handler: NpmCommandHandler) -> None:
        """Handler matches npm run commands with dashes."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run type-check"},
        }
        assert handler.matches(hook_input) is True

    # Tests for matches() method - npx commands

    def test_matches_npx_tsc(self, handler: NpmCommandHandler) -> None:
        """Handler matches npx tsc command."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx tsc --noEmit"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npx_eslint(self, handler: NpmCommandHandler) -> None:
        """Handler matches npx eslint command."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx eslint src/"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npx_prettier(self, handler: NpmCommandHandler) -> None:
        """Handler matches npx prettier command."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx prettier --check ."},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npx_cspell(self, handler: NpmCommandHandler) -> None:
        """Handler matches npx cspell command."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx cspell '**/*.ts'"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npx_playwright(self, handler: NpmCommandHandler) -> None:
        """Handler matches npx playwright command."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx playwright test"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npx_tsx(self, handler: NpmCommandHandler) -> None:
        """Handler matches npx tsx command."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx tsx src/script.ts"},
        }
        assert handler.matches(hook_input) is True

    def test_does_not_match_npx_unknown_tool(self, handler: NpmCommandHandler) -> None:
        """Handler does not match npx tools not in suggestion map."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx unknown-tool --help"},
        }
        assert handler.matches(hook_input) is False

    # Tests for matches() method - piped commands

    def test_matches_npm_run_piped_to_grep(self, handler: NpmCommandHandler) -> None:
        """Handler matches npm run command piped to grep."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run test | grep error"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npm_run_llm_piped_to_grep(self, handler: NpmCommandHandler) -> None:
        """Handler matches even llm: commands when piped (pointless)."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run llm:test | grep failed"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npx_piped_to_awk(self, handler: NpmCommandHandler) -> None:
        """Handler matches npx command piped to awk."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx tsc | awk '{print $1}'"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npm_run_piped_to_sed(self, handler: NpmCommandHandler) -> None:
        """Handler matches npm run piped to sed."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run lint | sed 's/error/ERROR/'"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_npm_run_piped_to_tee(self, handler: NpmCommandHandler) -> None:
        """Handler matches npm run piped to tee."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run test | tee output.log"},
        }
        assert handler.matches(hook_input) is True

    def test_does_not_match_npm_run_without_pipe(self, handler: NpmCommandHandler) -> None:
        """Handler distinguishes between piped and non-piped llm: commands."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run llm:test"},
        }
        assert handler.matches(hook_input) is False

    # Tests for matches() method - edge cases

    def test_does_not_match_non_bash_tool(self, handler: NpmCommandHandler) -> None:
        """Handler only matches Bash tool."""
        hook_input: dict[str, Any] = {
            "tool_name": "Write",
            "tool_input": {"content": "npm run build"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_empty_command(self, handler: NpmCommandHandler) -> None:
        """Handler does not match when command is empty."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": ""},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_missing_command(self, handler: NpmCommandHandler) -> None:
        """Handler does not match when command field is missing."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_npm_install(self, handler: NpmCommandHandler) -> None:
        """Handler does not match npm install commands."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm install lodash"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_npm_ci(self, handler: NpmCommandHandler) -> None:
        """Handler does not match npm ci commands."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm ci"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_npm_version(self, handler: NpmCommandHandler) -> None:
        """Handler does not match npm version commands."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm version"},
        }
        assert handler.matches(hook_input) is False

    # Tests for handle() method - npm run commands

    def test_handle_blocks_npm_run_build(self, handler: NpmCommandHandler) -> None:
        """Handler blocks npm run build with suggestion."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "npm run build" in result.reason
        assert "npm run llm:build" in result.reason
        assert "PHILOSOPHY" in result.reason

    def test_handle_blocks_npm_run_lint(self, handler: NpmCommandHandler) -> None:
        """Handler blocks npm run lint with llm:lint suggestion."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run lint"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "npm run llm:lint" in result.reason

    def test_handle_blocks_npm_run_type_check(self, handler: NpmCommandHandler) -> None:
        """Handler blocks npm run type-check with llm:type-check suggestion."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run type-check"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "npm run llm:type-check" in result.reason

    def test_handle_blocks_npm_run_format(self, handler: NpmCommandHandler) -> None:
        """Handler blocks npm run format with llm:format suggestion."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run format"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "npm run llm:format" in result.reason

    def test_handle_blocks_npm_run_test(self, handler: NpmCommandHandler) -> None:
        """Handler blocks npm run test with llm:test suggestion."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run test"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "npm run llm:test" in result.reason

    def test_handle_blocks_npm_run_qa(self, handler: NpmCommandHandler) -> None:
        """Handler blocks npm run qa with llm:qa suggestion."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run qa"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "npm run llm:qa" in result.reason

    def test_handle_blocks_npm_run_unknown_suggests_qa(self, handler: NpmCommandHandler) -> None:
        """Handler blocks unknown npm run command and suggests llm:qa."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run unknown-command"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "npm run llm:qa" in result.reason

    # Tests for handle() method - npx commands

    def test_handle_blocks_npx_tsc(self, handler: NpmCommandHandler) -> None:
        """Handler blocks npx tsc with llm:type-check suggestion."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx tsc --noEmit"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "npx tsc" in result.reason
        assert "llm:type-check" in result.reason

    def test_handle_blocks_npx_eslint(self, handler: NpmCommandHandler) -> None:
        """Handler blocks npx eslint with llm:lint suggestion."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx eslint src/"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "npx eslint" in result.reason
        assert "llm:lint" in result.reason

    def test_handle_blocks_npx_prettier(self, handler: NpmCommandHandler) -> None:
        """Handler blocks npx prettier with llm:format:check suggestion."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx prettier --check ."},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "npx prettier" in result.reason
        assert "llm:format:check" in result.reason

    def test_handle_blocks_npx_cspell(self, handler: NpmCommandHandler) -> None:
        """Handler blocks npx cspell with llm:spell-check suggestion."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx cspell '**/*.ts'"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "npx cspell" in result.reason
        assert "llm:spell-check" in result.reason

    def test_handle_blocks_npx_playwright(self, handler: NpmCommandHandler) -> None:
        """Handler blocks npx playwright with llm:test suggestion."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx playwright test"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "npx playwright" in result.reason
        assert "llm:test" in result.reason

    def test_handle_blocks_npx_tsx(self, handler: NpmCommandHandler) -> None:
        """Handler blocks npx tsx with contextual suggestion."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx tsx script.ts"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "npx tsx" in result.reason
        assert "npm run llm:" in result.reason

    # Tests for handle() method - piped commands

    def test_handle_blocks_npm_run_piped_to_grep(self, handler: NpmCommandHandler) -> None:
        """Handler blocks npm run piped to grep (pointless)."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run test | grep error"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "Piping npm/npx commands is pointless" in result.reason
        assert "./var/qa/" in result.reason
        assert "jq" in result.reason

    def test_handle_blocks_npm_run_llm_piped(self, handler: NpmCommandHandler) -> None:
        """Handler blocks even llm: commands when piped."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run llm:lint | grep warning"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "Piping npm/npx commands is pointless" in result.reason

    def test_handle_blocks_npx_piped_to_awk(self, handler: NpmCommandHandler) -> None:
        """Handler blocks npx piped to awk."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx eslint . | awk '{print $1}'"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "Piping npm/npx commands is pointless" in result.reason

    def test_handle_pipe_block_message_includes_philosophy(
        self, handler: NpmCommandHandler
    ) -> None:
        """Pipe blocking message explains philosophy."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run test | grep failed"},
        }
        result = handler.handle(hook_input)
        assert "PHILOSOPHY" in result.reason
        assert "cache files" in result.reason
        assert "jq to query" in result.reason

    def test_handle_pipe_block_extracts_command_name(self, handler: NpmCommandHandler) -> None:
        """Pipe blocking extracts command name for suggestion."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run llm:test | grep error"},
        }
        result = handler.handle(hook_input)
        assert "npm run llm:test" in result.reason  # Shows the correct command

    # Tests for handle() method - edge cases

    def test_handle_allows_when_no_command(self, handler: NpmCommandHandler) -> None:
        """Handler allows when command field is missing."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert "No command found" in result.reason

    def test_handle_allows_when_pattern_not_matched(self, handler: NpmCommandHandler) -> None:
        """Handler allows when command pattern doesn't match."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 'test'"},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    # Tests for handler metadata

    def test_handler_has_correct_name(self, handler: NpmCommandHandler) -> None:
        """Handler has correct name."""
        assert handler.name == "enforce-npm-commands"

    def test_handler_has_correct_priority(self, handler: NpmCommandHandler) -> None:
        """Handler has correct priority."""
        assert handler.priority == 50

    def test_handler_has_correct_tags(self, handler: NpmCommandHandler) -> None:
        """Handler has correct tags."""
        assert "workflow" in handler.tags
        assert "npm" in handler.tags
        assert "nodejs" in handler.tags
        assert "javascript" in handler.tags
        assert "advisory" in handler.tags
        assert "non-terminal" in handler.tags

    # Tests for class constants

    def test_allowed_commands_constant(self, handler: NpmCommandHandler) -> None:
        """ALLOWED_COMMANDS constant includes expected commands."""
        assert "clean" in handler.ALLOWED_COMMANDS
        assert "dev:permissive" in handler.ALLOWED_COMMANDS

    def test_suggestions_constant(self, handler: NpmCommandHandler) -> None:
        """SUGGESTIONS constant maps commands correctly."""
        assert handler.SUGGESTIONS["build"] == "llm:build"
        assert handler.SUGGESTIONS["lint"] == "llm:lint"
        assert handler.SUGGESTIONS["type-check"] == "llm:type-check"
        assert handler.SUGGESTIONS["format"] == "llm:format"
        assert handler.SUGGESTIONS["test"] == "llm:test"
        assert handler.SUGGESTIONS["qa"] == "llm:qa"

    def test_npx_tool_suggestions_constant(self, handler: NpmCommandHandler) -> None:
        """NPX_TOOL_SUGGESTIONS constant maps tools correctly."""
        assert handler.NPX_TOOL_SUGGESTIONS["tsc"] == "llm:type-check"
        assert handler.NPX_TOOL_SUGGESTIONS["eslint"] == "llm:lint"
        assert handler.NPX_TOOL_SUGGESTIONS["prettier"] == "llm:format:check"
        assert handler.NPX_TOOL_SUGGESTIONS["cspell"] == "llm:spell-check"
        assert handler.NPX_TOOL_SUGGESTIONS["playwright"] == "llm:test"
        assert "tsx" in handler.NPX_TOOL_SUGGESTIONS

    # Tests for error message content

    def test_error_message_includes_blocked_command(self, handler: NpmCommandHandler) -> None:
        """Error message shows the blocked command."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build"},
        }
        result = handler.handle(hook_input)
        assert "BLOCKED COMMAND:" in result.reason
        assert "npm run build" in result.reason

    def test_error_message_includes_suggested_command(self, handler: NpmCommandHandler) -> None:
        """Error message shows the suggested llm: command."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run lint"},
        }
        result = handler.handle(hook_input)
        assert "USE THIS INSTEAD:" in result.reason
        assert "npm run llm:lint" in result.reason

    def test_error_message_explains_philosophy(self, handler: NpmCommandHandler) -> None:
        """Error message explains llm: command philosophy."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run test"},
        }
        result = handler.handle(hook_input)
        assert "PHILOSOPHY" in result.reason
        assert "Minimal stdout" in result.reason
        assert "Verbose JSON logging" in result.reason
        assert "Machine-readable output" in result.reason

    # Tests for has_llm_commands caching

    def test_has_llm_commands_cached_at_init(self) -> None:
        """has_llm_commands is cached at __init__ time."""
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command.has_llm_commands_in_package_json",
            return_value=True,
        ) as mock_detect:
            handler = NpmCommandHandler()
            assert handler.has_llm_commands is True
            mock_detect.assert_called_once()

    def test_has_llm_commands_false_when_no_llm_scripts(self) -> None:
        """has_llm_commands is False when no llm: scripts exist."""
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command.has_llm_commands_in_package_json",
            return_value=False,
        ):
            handler = NpmCommandHandler()
            assert handler.has_llm_commands is False

    # Tests for advisory mode (no llm: commands)

    def test_advisory_mode_allows_npm_run_build(self, advisory_handler: NpmCommandHandler) -> None:
        """Advisory mode allows npm run build with advisory message."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build"},
        }
        result = advisory_handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert "ADVISORY" in result.reason
        assert "llm:" in result.reason

    def test_advisory_mode_allows_npm_run_lint(self, advisory_handler: NpmCommandHandler) -> None:
        """Advisory mode allows npm run lint with advisory message."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run lint"},
        }
        result = advisory_handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert "ADVISORY" in result.reason

    def test_advisory_mode_allows_npx_tsc(self, advisory_handler: NpmCommandHandler) -> None:
        """Advisory mode allows npx tsc with advisory message."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx tsc --noEmit"},
        }
        result = advisory_handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert "ADVISORY" in result.reason

    def test_advisory_mode_includes_recommendation(
        self, advisory_handler: NpmCommandHandler
    ) -> None:
        """Advisory message includes recommendation to create llm: wrappers."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run test"},
        }
        result = advisory_handler.handle(hook_input)
        assert "RECOMMENDATION" in result.reason
        assert "llm:" in result.reason
        assert "package.json" in result.reason

    def test_advisory_mode_still_blocks_piped_commands(
        self, advisory_handler: NpmCommandHandler
    ) -> None:
        """Advisory mode still blocks piped commands (always pointless)."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run test | grep error"},
        }
        result = advisory_handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "Piping npm/npx commands is pointless" in result.reason

    def test_advisory_mode_includes_example_script(
        self, advisory_handler: NpmCommandHandler
    ) -> None:
        """Advisory message includes example package.json script."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run lint"},
        }
        result = advisory_handler.handle(hook_input)
        assert "llm:lint" in result.reason

    def test_advisory_mode_includes_guide_path(self, advisory_handler: NpmCommandHandler) -> None:
        """Advisory message includes path to LLM command wrapper guide."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build"},
        }
        result = advisory_handler.handle(hook_input)
        assert "Full guide:" in result.reason
        assert "llm-command-wrappers.md" in result.reason
