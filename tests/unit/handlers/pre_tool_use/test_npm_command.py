"""Tests for NpmCommandHandler.

Comprehensive test coverage for npm/npx command enforcement.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.workspace import ProjectRegistry
from claude_code_hooks_daemon.handlers.pre_tool_use.npm_command import NpmCommandHandler


class TestNpmCommandHandler:
    """Test suite for NpmCommandHandler."""

    @pytest.fixture
    def handler(self) -> Iterator[NpmCommandHandler]:
        """Handler in enforcement mode (llm: commands present).

        The patch spans the whole test, not just construction: since Plan
        00296 the mode is decided per invocation from the command's own
        workspace, so `handle()` calls the detector too.
        """
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command.has_llm_commands_in_package_json",
            return_value=True,
        ):
            yield NpmCommandHandler()

    @pytest.fixture
    def advisory_handler(self) -> Iterator[NpmCommandHandler]:
        """Handler in advisory mode (no llm: commands anywhere)."""
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command.has_llm_commands_in_package_json",
            return_value=False,
        ):
            yield NpmCommandHandler()

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

    # Finding #61: capture the FULL script token (underscores, digits, mixed case)

    def test_handle_captures_full_underscore_script_name(self, handler: NpmCommandHandler) -> None:
        """A script name with an underscore must be echoed in full, not truncated."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build_prod"},
        }
        result = handler.handle(hook_input)
        assert "npm run build_prod" in result.reason
        # The truncated form must NOT be the blocked command.
        assert "BLOCKED COMMAND:\n  npm run build\n" not in result.reason

    def test_handle_captures_full_digit_script_name(self, handler: NpmCommandHandler) -> None:
        """A script name with trailing digits must be echoed in full."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run test123"},
        }
        result = handler.handle(hook_input)
        assert "npm run test123" in result.reason

    def test_matches_uppercase_script_name(self, handler: NpmCommandHandler) -> None:
        """An uppercase (non-llm) script must still be matched, not silently skipped."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run Build"},
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

    def test_does_not_match_npx_with_logical_or(self, handler: NpmCommandHandler) -> None:
        """Handler must NOT match || (logical OR) as a pipe operator."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "npx hooks-daemon restart 2>/dev/null || npx claude-code-hooks-daemon restart 2>/dev/null"
            },
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_npm_run_with_logical_or(self, handler: NpmCommandHandler) -> None:
        """Handler must NOT match || (logical OR) in npm run commands."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run llm:build || echo 'build failed'"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_npm_run_with_logical_and(self, handler: NpmCommandHandler) -> None:
        """Handler must NOT match && (logical AND) - only real pipes."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run llm:test && npm run llm:lint"},
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

    def test_handle_pipe_block_caps_echoed_command_length(self, handler: NpmCommandHandler) -> None:
        """Plan 00209 Task 1.4 (DBF audit): the piped-command branch echoes
        the FULL raw command back into the deny reason with no length cap —
        the same defect class fixed in pipe_blocker.py. A long command (a
        heredoc or verbose one-liner containing 'npm run X ... |') must not
        be echoed back in full."""
        long_command = "npm run test " + ("x" * 1000) + " | grep failed"
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": long_command},
        }
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert len(result.reason) < 1000

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

    # Tests for explicit project_root (Plan 00305 Task 1.1: construct without
    # a live ProjectContext, e.g. from a CLI command talking to config files
    # directly rather than a running daemon session)

    def test_project_root_param_used_instead_of_project_context(self, tmp_path: Path) -> None:
        """An explicit `project_root` is read from directly, bypassing ProjectContext.

        `ProjectContext.project_root()` is never called when a root is
        passed explicitly -- construction must succeed with no
        ProjectContext initialised at all.
        """
        (tmp_path / "package.json").write_text(
            json.dumps({"scripts": {"llm:build": "true"}}), encoding="utf-8"
        )
        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root",
            side_effect=AssertionError("ProjectContext.project_root() must not be called"),
        ):
            handler = NpmCommandHandler(project_root=tmp_path)
        assert handler.has_llm_commands is True

    def test_project_root_param_defaults_to_none(self) -> None:
        """Omitting `project_root` preserves the original ProjectContext-driven behaviour."""
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command.has_llm_commands_in_package_json",
            return_value=True,
        ) as mock_detect:
            NpmCommandHandler()
            mock_detect.assert_called_once_with(None)

    # Tests for advisory mode (no llm: commands)

    def test_advisory_mode_allows_npm_run_build(self, advisory_handler: NpmCommandHandler) -> None:
        """Advisory mode allows npm run build with advisory message.

        Regression test: the advisory message MUST be in `context`, not
        `reason` - the PreToolUse response formatter only surfaces `reason`
        for DENY/ASK decisions (see HookResult.to_json), so an ALLOW decision
        with the message in `reason` is silently dropped and never reaches
        the user. Asserting on `context` here (and round-tripping through
        `to_json` in test_advisory_mode_message_survives_pretooluse_formatting
        below) pins the real, user-visible contract.
        """
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build"},
        }
        result = advisory_handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        advisory = "\n".join(result.context)
        assert "ADVISORY" in advisory
        assert "llm:" in advisory

    def test_advisory_mode_allows_npm_run_lint(self, advisory_handler: NpmCommandHandler) -> None:
        """Advisory mode allows npm run lint with advisory message."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run lint"},
        }
        result = advisory_handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert "ADVISORY" in "\n".join(result.context)

    def test_advisory_mode_allows_npx_tsc(self, advisory_handler: NpmCommandHandler) -> None:
        """Advisory mode allows npx tsc with advisory message."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npx tsc --noEmit"},
        }
        result = advisory_handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert "ADVISORY" in "\n".join(result.context)

    def test_advisory_mode_includes_recommendation(
        self, advisory_handler: NpmCommandHandler
    ) -> None:
        """Advisory message includes recommendation to create llm: wrappers."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run test"},
        }
        result = advisory_handler.handle(hook_input)
        advisory = "\n".join(result.context)
        assert "RECOMMENDATION" in advisory
        assert "llm:" in advisory
        assert "package.json" in advisory

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
        assert "llm:lint" in "\n".join(result.context)

    def test_advisory_mode_includes_guide_path(self, advisory_handler: NpmCommandHandler) -> None:
        """Advisory message includes path to LLM command wrapper guide."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build"},
        }
        result = advisory_handler.handle(hook_input)
        advisory = "\n".join(result.context)
        assert "Full guide:" in advisory
        assert "llm-command-wrappers.md" in advisory

    def test_advisory_mode_message_survives_pretooluse_formatting(
        self, advisory_handler: NpmCommandHandler
    ) -> None:
        """The advisory message must actually reach the user via to_json().

        This is the real regression guard: HookResult.to_json() only copies
        `reason` into the PreToolUse response for DENY/ASK decisions, so this
        confirms the ALLOW-decision advisory text is present in
        `additionalContext` - not silently dropped as it was before this
        message moved from `reason` to `context`.
        """
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build"},
        }
        result = advisory_handler.handle(hook_input)
        response = result.to_json("PreToolUse")
        additional_context = response["hookSpecificOutput"]["additionalContext"]
        assert "ADVISORY" in additional_context
        assert "llm:" in additional_context

    # ==========================================================================
    # CLAUDE.MD GUIDANCE TESTS
    # ==========================================================================

    def test_get_claude_md_returns_guidance(self) -> None:
        """Should return non-None guidance for CLAUDE.md injection."""
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command.has_llm_commands_in_package_json",
            return_value=True,
        ):
            handler = NpmCommandHandler()
        guidance = handler.get_claude_md()
        assert guidance is not None

    def test_get_claude_md_mentions_llm_prefix(self) -> None:
        """Guidance should explain the llm: prefix convention."""
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command.has_llm_commands_in_package_json",
            return_value=True,
        ):
            handler = NpmCommandHandler()
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "llm:" in guidance


class TestNpmCommandGetRules:
    """get_rules() (Plan 00116): 2 rules for the 2 distinct deny shapes."""

    def test_get_rules_returns_two_rules(self) -> None:
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command.has_llm_commands_in_package_json",
            return_value=True,
        ):
            handler = NpmCommandHandler()
        assert len(handler.get_rules()) == 2

    def test_get_rules_ids_are_constants(self) -> None:
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command.has_llm_commands_in_package_json",
            return_value=True,
        ):
            handler = NpmCommandHandler()
        rule_ids = {rule.rule_id for rule in handler.get_rules()}
        assert rule_ids == {RuleID.NPM_PIPED_COMMAND, RuleID.NPM_NON_LLM_COMMAND}

    def test_get_rules_every_verbose_is_non_empty(self) -> None:
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command.has_llm_commands_in_package_json",
            return_value=True,
        ):
            handler = NpmCommandHandler()
        for rule in handler.get_rules():
            assert rule.verbose


class TestNpmCommandEnforcementStatus:
    """get_enforcement_status() (Plan 00296 T4.1): degraded-mode visibility."""

    def test_nominal_when_llm_commands_present(self, tmp_path: Path) -> None:
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command."
            "has_llm_commands_in_package_json",
            return_value=True,
        ):
            handler = NpmCommandHandler()
            assert handler.get_enforcement_status(tmp_path) == []

    def test_advisory_when_no_llm_commands(self, tmp_path: Path) -> None:
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command."
            "has_llm_commands_in_package_json",
            return_value=False,
        ):
            handler = NpmCommandHandler()
            statuses = handler.get_enforcement_status(tmp_path)
        assert len(statuses) == 1
        assert "npm_command" in statuses[0]
        assert str(tmp_path) in statuses[0]
        assert "advisory only" in statuses[0]

    def test_evaluates_at_the_given_root_not_construction_root(self, tmp_path: Path) -> None:
        """The probe re-reads at the PASSED root -- it is not frozen at __init__."""
        other_root = tmp_path / "other"
        other_root.mkdir()
        (other_root / "package.json").write_text(
            json.dumps({"scripts": {"llm:build": "true"}}), encoding="utf-8"
        )
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command."
            "has_llm_commands_in_package_json",
            return_value=False,
        ):
            handler = NpmCommandHandler()
        # Real (unpatched) probe against a root that DOES have llm: scripts.
        assert handler.get_enforcement_status(other_root) == []


class TestNpmCommandDisclosureLadder:
    """Verbose-first/terse-after per (transcript_path, rule_id) (Plan 00116)."""

    @pytest.fixture(autouse=True)
    def _reset_disclosure_tracker(self):
        from claude_code_hooks_daemon.core import reset_data_layer

        reset_data_layer()
        yield
        reset_data_layer()

    @pytest.fixture
    def handler(self) -> Iterator[NpmCommandHandler]:
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command.has_llm_commands_in_package_json",
            return_value=True,
        ):
            yield NpmCommandHandler()

    @staticmethod
    def _non_llm_input(transcript_path: str | None) -> dict[str, Any]:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run build"},
        }
        if transcript_path is not None:
            hook_input["transcript_path"] = transcript_path
        return hook_input

    def test_deny_reason_starts_with_rule_id_prefix(self, handler: NpmCommandHandler) -> None:
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        result = handler.handle(self._non_llm_input("/tmp/transcript-npm-a.jsonl"))
        assert result.reason.startswith(f"BLOCKED [{RuleID.NPM_NON_LLM_COMMAND}]")

    def test_first_fire_is_verbose(self, handler: NpmCommandHandler) -> None:
        result = handler.handle(self._non_llm_input("/tmp/transcript-npm-b.jsonl"))
        assert "PHILOSOPHY" in result.reason

    def test_second_fire_same_agent_is_terse(self, handler: NpmCommandHandler) -> None:
        transcript = "/tmp/transcript-npm-c.jsonl"
        handler.handle(self._non_llm_input(transcript))
        second = handler.handle(self._non_llm_input(transcript))
        assert "PHILOSOPHY" not in second.reason
        assert "BLOCKED COMMAND:" in second.reason

    def test_different_agent_is_independently_verbose(self, handler: NpmCommandHandler) -> None:
        handler.handle(self._non_llm_input("/tmp/transcript-npm-d.jsonl"))
        other = handler.handle(self._non_llm_input("/tmp/transcript-npm-e.jsonl"))
        assert "PHILOSOPHY" in other.reason

    def test_missing_transcript_path_always_verbose(self, handler: NpmCommandHandler) -> None:
        first = handler.handle(self._non_llm_input(None))
        second = handler.handle(self._non_llm_input(None))
        assert "PHILOSOPHY" in first.reason
        assert "PHILOSOPHY" in second.reason

    def test_piped_and_non_llm_rules_disclose_independently(
        self, handler: NpmCommandHandler
    ) -> None:
        """Two DIFFERENT rules for the SAME agent both disclose verbose."""
        transcript = "/tmp/transcript-npm-f.jsonl"
        piped_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "npm run test | grep failed"},
            "transcript_path": transcript,
        }
        non_llm_result = handler.handle(self._non_llm_input(transcript))
        piped_result = handler.handle(piped_input)
        assert "PHILOSOPHY" in non_llm_result.reason
        assert "Piping npm/npx commands is pointless" in piped_result.reason


class TestNpmCommandMonorepoWorkspace:
    """Mode is decided per invocation, against the command's DECLARED project.

    Plan 00296. Deciding once at construction against the git root makes the
    handler permanently inert in a monorepo that has gone to the trouble of
    defining llm: wrappers -- enforcement silently downgrades to advisory and
    nothing says why.

    Projects are declared, never inferred: every test here that expects
    per-project behaviour declares the projects, and
    `test_undeclared_monorepo_is_not_split_up` pins the negative.
    """

    @staticmethod
    def _monorepo(tmp_path: Path) -> Path:
        """Two sibling Node workspaces, NO root manifest (the reported shape)."""
        enforced = tmp_path / "apps" / "web"
        enforced.mkdir(parents=True)
        (enforced / "package.json").write_text(
            json.dumps({"scripts": {"llm:build": "vite build", "build": "vite build"}}),
            encoding="utf-8",
        )
        advisory = tmp_path / "apps" / "api"
        advisory.mkdir(parents=True)
        (advisory / "package.json").write_text(
            json.dumps({"scripts": {"build": "tsc"}}), encoding="utf-8"
        )
        return tmp_path

    @staticmethod
    @contextmanager
    def _rooted_at(root: Path) -> Iterator[None]:
        """Point BOTH root lookups at the fixture repo.

        `ProjectContext.project_root` is what the mode probe reads;
        `resolve_project_root` is what supplies the fallback root.
        """
        with (
            patch(
                "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root",
                return_value=root,
            ),
            patch(
                "claude_code_hooks_daemon.handlers.pre_tool_use.npm_command.resolve_project_root",
                return_value=str(root),
            ),
        ):
            yield

    @classmethod
    def _handler(cls, root: Path, declare: bool = True) -> NpmCommandHandler:
        """Construct at the ROOT, where no manifest exists.

        Construction-time detection therefore yields False; any DENY below
        proves the decision was re-made per invocation.

        ``declare=False`` leaves the registry empty, which is how an
        unconfigured repository behaves.
        """
        with cls._rooted_at(root):
            handler = NpmCommandHandler()

        projects = (
            [{"name": "web", "root": "apps/web"}, {"name": "api", "root": "apps/api"}]
            if declare
            else []
        )
        handler._project_registry = ProjectRegistry.from_config(
            Config.model_validate({"projects": projects}), root
        )
        return handler

    @staticmethod
    def _input(command: str, cwd: Path | None = None) -> dict[str, Any]:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        if cwd is not None:
            hook_input["cwd"] = str(cwd)
        return hook_input

    def test_enforces_in_workspace_with_llm_scripts_via_cwd(self, tmp_path: Path) -> None:
        root = self._monorepo(tmp_path)
        handler = self._handler(root)
        assert handler.has_llm_commands is False, "root has no manifest: precondition"

        with self._rooted_at(root):
            result = handler.handle(self._input("npm run build", cwd=root / "apps" / "web"))

        assert result.decision == Decision.DENY
        assert "llm:build" in result.reason

    def test_advises_in_sibling_workspace_without_llm_scripts(self, tmp_path: Path) -> None:
        """The sibling must NOT inherit the other workspace's mode."""
        root = self._monorepo(tmp_path)
        handler = self._handler(root)

        with self._rooted_at(root):
            result = handler.handle(self._input("npm run build", cwd=root / "apps" / "api"))

        assert result.decision == Decision.ALLOW
        assert result.context is not None

    def test_leading_cd_selects_the_workspace(self, tmp_path: Path) -> None:
        """`cd apps/web && npm run build` is how a monorepo command is actually shaped.

        The hook's cwd stays at the repo root, so honouring cwd alone would
        resolve nothing and leave enforcement off for the real invocation.
        """
        root = self._monorepo(tmp_path)
        handler = self._handler(root)

        with self._rooted_at(root):
            result = handler.handle(self._input("cd apps/web && npm run build", cwd=root))

        assert result.decision == Decision.DENY

    def test_leading_cd_into_workspace_without_llm_scripts_advises(self, tmp_path: Path) -> None:
        root = self._monorepo(tmp_path)
        handler = self._handler(root)

        with self._rooted_at(root):
            result = handler.handle(self._input("cd apps/api && npm run build", cwd=root))

        assert result.decision == Decision.ALLOW

    def test_no_manifest_anywhere_falls_back_to_advisory(self, tmp_path: Path) -> None:
        """Single-root repo with no Node in it behaves exactly as before."""
        root = self._monorepo(tmp_path)
        handler = self._handler(root)

        with self._rooted_at(root):
            result = handler.handle(self._input("npm run build", cwd=root))

        assert result.decision == Decision.ALLOW

    def test_missing_cwd_falls_back_to_project_root(self, tmp_path: Path) -> None:
        """A hook payload without cwd must not raise; it degrades to the root."""
        root = self._monorepo(tmp_path)
        (root / "package.json").write_text(
            json.dumps({"scripts": {"llm:qa": "qa"}}), encoding="utf-8"
        )
        handler = self._handler(root)

        with self._rooted_at(root):
            result = handler.handle(self._input("npm run build"))

        assert result.decision == Decision.DENY

    def test_undeclared_monorepo_is_not_split_up(self, tmp_path: Path) -> None:
        """THE anti-inference pin, at handler level.

        `apps/web` has a package.json with llm: scripts and looks exactly like
        a workspace. With NOTHING declared the handler must resolve to the
        repository root -- which has no manifest, so advisory -- rather than
        quietly deciding `apps/web` is a project. A guessed boundary that
        happened to be wrong would enforce against the wrong tree while
        looking perfectly healthy.
        """
        root = self._monorepo(tmp_path)
        handler = self._handler(root, declare=False)

        with self._rooted_at(root):
            result = handler.handle(self._input("npm run build", cwd=root / "apps" / "web"))

        assert result.decision == Decision.ALLOW
        assert result.context is not None

    def test_piped_command_denies_before_workspace_resolution(self, tmp_path: Path) -> None:
        """The piped branch denies regardless of mode -- unchanged by this task.

        Documented in the field report as a secondary observation: 'advisory'
        mode still hard-denies pipes. Pinned here so the workspace work does
        not silently alter it.
        """
        root = self._monorepo(tmp_path)
        handler = self._handler(root)

        with self._rooted_at(root):
            result = handler.handle(
                self._input("npm run build | grep x", cwd=root / "apps" / "api")
            )

        assert result.decision == Decision.DENY
        assert "Piping npm/npx commands is pointless" in result.reason
