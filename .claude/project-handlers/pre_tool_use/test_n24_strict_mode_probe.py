"""Tests for the N24 strict_mode acceptance probe (Plan 00466 N24).

This handler exists only so tests/acceptance/test_n24_strict_mode_probe_socket.py
can prove `daemon.strict_mode` really reaches the LIVE daemon process
end-to-end, without depending on an unrelated bug's lifecycle (the review's
own live reproduction used a still-live, separately-tracked defect). It
never fires on real traffic: the marker it matches on is never set by a real
Claude Code session.
"""

from typing import Any

from n24_strict_mode_probe import N24StrictModeProbeHandler

from claude_code_hooks_daemon.constants import HandlerTag


class TestN24StrictModeProbeHandler:
    def setup_method(self) -> None:
        self.handler = N24StrictModeProbeHandler()

    def test_init(self) -> None:
        assert self.handler.name == "n24-strict-mode-probe"
        assert self.handler.terminal is False
        assert "project" in self.handler.tags
        # Deliberately NOT SAFETY+BLOCKING: the acceptance probe isolates
        # daemon.strict_mode plumbing (Plan 00466 N24 Part 1) from the
        # SAFETY+BLOCKING fail-closed policy (Part 2, tested at the chain
        # level in tests/unit/core/test_chain.py).
        assert HandlerTag.SAFETY not in self.handler.tags
        assert HandlerTag.BLOCKING not in self.handler.tags

    def test_matches_the_marked_payload(self) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "synthetic_source": "n24-probe",
        }
        assert self.handler.matches(hook_input) is True

    def test_does_not_match_an_unmarked_payload(self) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
        }
        assert self.handler.matches(hook_input) is False

    def test_does_not_match_a_different_synthetic_source(self) -> None:
        """Only the exact probe marker fires -- not every synthetic source."""
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "synthetic_source": "playbook-probe",
        }
        assert self.handler.matches(hook_input) is False

    def test_handle_raises(self) -> None:
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": "true"},
            "synthetic_source": "n24-probe",
        }
        try:
            self.handler.handle(hook_input)
        except RuntimeError as exc:
            assert "n24" in str(exc).lower()
        else:
            raise AssertionError("handle() did not raise")

    def test_get_claude_md_returns_guidance(self) -> None:
        guidance = self.handler.get_claude_md()
        assert guidance is not None
        assert "n24" in guidance.lower()

    def test_acceptance_tests_include_a_harness_cannot_produce_case(self) -> None:
        """A real Claude Code session never sets `synthetic_source`.

        Same reasoning as absolute_path.get_acceptance_tests() (Plan 00196):
        the harness cannot produce this input, so live-socket coverage
        moves to tests/acceptance/test_n24_strict_mode_probe_socket.py.
        """
        tests = self.handler.get_acceptance_tests()
        assert tests
        assert any(t.harness_cannot_produce for t in tests)

    def test_acceptance_tests_include_a_producible_near_miss_allow_case(self) -> None:
        """The negative case is a REAL, harness-producible command."""
        from claude_code_hooks_daemon.core.hook_result import Decision

        tests = self.handler.get_acceptance_tests()
        allow_cases = [t for t in tests if t.expected_decision == Decision.ALLOW]
        assert allow_cases
        assert all(t.harness_cannot_produce is None for t in allow_cases)
