"""Tests for the project-level daemon restart verifier handler.

Re-homed from the built-in `daemon_restart_verifier` (Plan 00370): this
repository's own dogfooding advisory, so it lives beside the other project
handlers rather than in the shared cross-project library.
"""

from typing import Any

from daemon_restart_verifier import DaemonRestartVerifierHandler

from claude_code_hooks_daemon.core.hook_result import Decision


class TestDaemonRestartVerifierHandler:
    def setup_method(self) -> None:
        self.handler = DaemonRestartVerifierHandler()

    def test_init(self) -> None:
        assert self.handler.name == "daemon-restart-verifier"
        assert self.handler.priority == 24
        assert self.handler.terminal is False
        assert "project" in self.handler.tags

    def test_matches_git_commit(self, bash_hook_input: Any) -> None:
        hook_input = bash_hook_input("git commit -m 'test WIP'")
        assert self.handler.matches(hook_input) is True

    def test_matches_git_commit_with_flags(self, bash_hook_input: Any) -> None:
        hook_input = bash_hook_input("git commit --amend -m 'oops'")
        assert self.handler.matches(hook_input) is True

    def test_no_match_other_git_commands(self, bash_hook_input: Any) -> None:
        hook_input = bash_hook_input("git status")
        assert self.handler.matches(hook_input) is False

    def test_no_match_non_bash_tools(self, write_hook_input: Any) -> None:
        hook_input = write_hook_input("/workspace/README.md", "content")
        assert self.handler.matches(hook_input) is False

    def test_no_match_empty_command(self, bash_hook_input: Any) -> None:
        hook_input = bash_hook_input("")
        assert self.handler.matches(hook_input) is False

    def test_handle_returns_one_line_advisory(self, bash_hook_input: Any) -> None:
        hook_input = bash_hook_input("git commit -m 'test WIP'")
        result = self.handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert len(result.context) == 1
        assert "RECOMMENDED" in result.context[0]
        assert "restart" in result.context[0]

    def test_get_claude_md_returns_guidance(self) -> None:
        guidance = self.handler.get_claude_md()
        assert guidance is not None
        assert "daemon_restart_verifier" in guidance
        assert "restart" in guidance

    def test_acceptance_tests_defined(self) -> None:
        tests = self.handler.get_acceptance_tests()
        assert len(tests) >= 1
        assert all(t.expected_decision == Decision.ALLOW for t in tests)
