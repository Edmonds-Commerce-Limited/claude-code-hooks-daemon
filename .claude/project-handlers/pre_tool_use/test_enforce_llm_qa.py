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

    def test_matches_run_all_sh(self, handler: EnforceLlmQaHandler, bash_hook_input: Any) -> None:
        """Blocks ./scripts/qa/run_all.sh."""
        assert handler.matches(bash_hook_input("./scripts/qa/run_all.sh")) is True

    def test_matches_run_all_sh_with_redirect(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Blocks run_all.sh even with output redirect."""
        assert (
            handler.matches(
                bash_hook_input("./scripts/qa/run_all.sh > /tmp/qa.txt 2>&1; tail -20 /tmp/qa.txt")
            )
            is True
        )

    def test_matches_run_all_sh_absolute_path(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Blocks run_all.sh with absolute path."""
        assert handler.matches(bash_hook_input("/workspace/scripts/qa/run_all.sh")) is True

    def test_does_not_match_llm_qa(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Does NOT block llm_qa.py."""
        assert handler.matches(bash_hook_input("./scripts/qa/llm_qa.py all")) is False

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

    def test_does_not_match_git_add_of_script(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Does NOT match git add that stages the script file."""
        assert handler.matches(bash_hook_input("git add scripts/qa/run_all.sh")) is False

    def test_does_not_match_git_commit_mentioning_script(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Does NOT match git commit whose message mentions the script."""
        assert (
            handler.matches(bash_hook_input('git commit -m "Integrated into run_all.sh"')) is False
        )

    def test_does_not_match_glob_of_script(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Does NOT match git add with glob that matches the script."""
        assert handler.matches(bash_hook_input("git add scripts/qa/run_all*")) is False

    # ── handle() ──

    def test_handle_blocks_with_guidance(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Returns DENY with llm_qa.py guidance."""
        result = handler.handle(bash_hook_input("./scripts/qa/run_all.sh"))
        assert result.decision == "deny"
        assert "llm_qa.py" in result.reason
        assert "run_all.sh" in result.reason

    # ── matches() — invocation vs mention (Plan 00200, dogfooding false positive) ──

    def test_does_not_match_cat_of_run_all_sh(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """`cat` inspects the script's contents, it does not execute it."""
        assert handler.matches(bash_hook_input("cat scripts/qa/run_all.sh")) is False

    def test_does_not_match_less_of_run_all_sh(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        assert handler.matches(bash_hook_input("less scripts/qa/run_all.sh")) is False

    def test_does_not_match_grep_of_run_all_sh(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        assert handler.matches(bash_hook_input('grep -n "check" scripts/qa/run_all.sh')) is False

    def test_does_not_match_head_of_run_all_sh(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        assert handler.matches(bash_hook_input("head -20 scripts/qa/run_all.sh")) is False

    def test_still_matches_bash_invocation_of_run_all_sh(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Explicit interpreter invocation still executes the script."""
        assert handler.matches(bash_hook_input("bash scripts/qa/run_all.sh")) is True

    def test_does_not_match_git_commit_preceded_by_cd(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """The git exemption must survive a leading `cd`.

        Regression: the exemption tested `command.startswith("git ")` against
        the WHOLE string, so the ubiquitous `cd /workspace; git commit -m ...`
        lost it entirely and a commit message mentioning the script was denied.
        The exemption belongs to the segment, like every other verdict here.
        """
        command = 'cd /workspace; git commit -m "wired the check into run_all.sh"'
        assert handler.matches(bash_hook_input(command)) is False

    def test_still_matches_invocation_after_a_cd(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """Moving the exemption per-segment must not blind the guard."""
        assert (
            handler.matches(bash_hook_input("cd /workspace; bash scripts/qa/run_all.sh")) is True
        )

    def test_does_not_match_shellcheck_of_run_all_sh(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """A static analyser READS the script; it never runs it.

        Regression for a real dogfooding false positive: `shellcheck -x
        scripts/qa/run_all.sh` -- the canonical way to verify an edit to that
        very script -- was denied with "run_all.sh produces 200+ lines of
        verbose output", which shellcheck does not produce and would not cause.
        """
        assert handler.matches(bash_hook_input("shellcheck -x scripts/qa/run_all.sh")) is False

    def test_does_not_match_diff_of_run_all_sh(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        assert handler.matches(bash_hook_input("diff scripts/qa/run_all.sh /tmp/old.sh")) is False

    # ── matches() — segmentation defects ──

    def test_matches_invocation_on_a_later_LINE_of_a_multiline_command(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """A newline separates commands just as `;` does.

        Regression: segmentation split only on `&&`/`||`/`;`/`|`, so a
        multi-line command collapsed into ONE segment. The leading word was
        taken from line 1 -- an inspection command -- and a real invocation on
        line 2 was waved through. A false NEGATIVE: the block simply did not
        apply to the shape agents use most (a heredoc-style multi-line script).
        """
        command = "grep -n pattern some/file.txt\nbash scripts/qa/run_all.sh"
        assert handler.matches(bash_hook_input(command)) is True

    def test_does_not_match_grep_whose_PATTERN_contains_a_pipe(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """A `|` inside quotes is data, not a pipeline separator.

        Regression: splitting on a bare `[;|]` cut through a quoted grep
        alternation, leaving a fragment whose "leading word" was the tail of
        the pattern (``CHECKS="``). That is in no allowlist, so an ordinary
        read of the script was denied. A false POSITIVE, and the reason this
        test exists.
        """
        command = 'grep -n "print_result\\|^run_check\\|CHECKS=" scripts/qa/run_all.sh'
        assert handler.matches(bash_hook_input(command)) is False

    def test_matches_real_pipeline_invocation(
        self, handler: EnforceLlmQaHandler, bash_hook_input: Any
    ) -> None:
        """An UNQUOTED `|` still separates -- the fix must not blind the guard."""
        assert handler.matches(bash_hook_input("echo hi | bash scripts/qa/run_all.sh")) is True

    # ── Acceptance tests ──

    def test_has_acceptance_tests(self, handler: EnforceLlmQaHandler) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) > 0

    def test_has_negative_case_for_cat_inspection(self, handler: EnforceLlmQaHandler) -> None:
        """Plan 00200 Task 6.4: every DENY-capable handler needs a near-miss ALLOW case."""
        from claude_code_hooks_daemon.core.hook_result import Decision

        tests = handler.get_acceptance_tests()
        allow_tests = [t for t in tests if t.expected_decision == Decision.ALLOW]
        assert allow_tests, "Expected at least one ALLOW acceptance test (near-miss case)"
        assert any("cat " in t.command for t in allow_tests)
