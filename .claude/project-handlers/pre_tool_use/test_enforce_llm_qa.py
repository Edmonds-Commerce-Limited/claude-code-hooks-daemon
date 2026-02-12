"""Tests for EnforceLlmQaHandler - blocks run_all.sh, requires llm_qa.py."""

from typing import Any

import pytest

from enforce_llm_qa import EnforceLlmQaHandler


class TestEnforceLlmQaHandler:
    """Tests for the LLM QA script enforcement handler."""

    @pytest.fixture
    def handler(self) -> EnforceLlmQaHandler:
        return EnforceLlmQaHandler()

    # ── Identity ──

    def test_name(self, handler: EnforceLlmQaHandler) -> None:
        assert handler.name == "enforce-llm-qa"

    def test_terminal(self, handler: EnforceLlmQaHandler) -> None:
        assert handler.terminal is True

    def test_tags(self, handler: EnforceLlmQaHandler) -> None:
        assert "project" in handler.tags
        assert "blocking" in handler.tags

    # ── matches() ──

    def test_matches_run_all_sh(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Blocks ./scripts/qa/run_all.sh."""
        assert handler.matches(bash_hook_input("./scripts/qa/run_all.sh")) is True

    def test_matches_run_all_sh_with_redirect(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Blocks run_all.sh even with output redirect."""
        assert handler.matches(
            bash_hook_input("./scripts/qa/run_all.sh > /tmp/qa.txt 2>&1; tail -20 /tmp/qa.txt")
        ) is True

    def test_matches_run_all_sh_absolute_path(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Blocks run_all.sh with absolute path."""
        assert handler.matches(
            bash_hook_input("/workspace/scripts/qa/run_all.sh")
        ) is True

    def test_does_not_match_llm_qa(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Does NOT block llm_qa.py."""
        assert handler.matches(
            bash_hook_input("./scripts/qa/llm_qa.py all")
        ) is False

    def test_does_not_match_individual_qa_scripts(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Does NOT block individual QA scripts (run_tests.sh, etc.)."""
        assert handler.matches(bash_hook_input("./scripts/qa/run_tests.sh")) is False
        assert handler.matches(bash_hook_input("./scripts/qa/run_lint.sh")) is False
        assert handler.matches(bash_hook_input("./scripts/qa/run_format_check.sh")) is False

    def test_does_not_match_non_bash(self, handler: EnforceLlmQaHandler) -> None:
        """Does NOT match Write tool."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "scripts/qa/run_all.sh", "content": "x"},
        }
        assert handler.matches(hook_input) is False

    def test_does_not_match_unrelated_commands(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Does NOT match unrelated bash commands."""
        assert handler.matches(bash_hook_input("git status")) is False
        assert handler.matches(bash_hook_input("pytest tests/")) is False

    # ── handle() ──

    def test_handle_blocks_with_guidance(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Returns DENY with llm_qa.py guidance."""
        result = handler.handle(bash_hook_input("./scripts/qa/run_all.sh"))
        assert result.decision == "deny"
        assert "llm_qa.py" in result.reason
        assert "run_all.sh" in result.reason

    # ── Acceptance tests ──

    def test_has_acceptance_tests(self, handler: EnforceLlmQaHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) > 0
