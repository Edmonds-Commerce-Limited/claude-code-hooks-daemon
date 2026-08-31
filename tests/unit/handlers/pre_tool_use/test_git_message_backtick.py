"""Plan 00219: backticks in a double-quoted -m are executed, not quoted.

Bash performs command substitution inside double quotes, so a backticked
span in `git commit -m "..."` is EXECUTED and its stdout replaces the text.
This happened in this repo: commit cc7dddc0's body reads "pipe_blocker now
allows , so the force-delete form" where a backticked command used to be.
Bash ran the command, it printed to stderr and nothing to stdout, and the
phrase was silently deleted. The commit itself succeeded, so nothing
signalled the loss.

Two halves to the hazard, and only one was uncovered:

- EXECUTION of a dangerous backticked command is ALREADY denied, because
  the blocking handlers match the full Bash command string. Probed against
  the live daemon before this handler was written, in both quoting forms.
- CORRUPTION of a benign message had nothing watching it at all. That is
  the gap this handler closes.

Measured against this repo's own history before choosing to block: 120 of
1,736 commit messages contain backticks, and every one of them is evidence
of SAFE authoring — had they been double-quoted, bash would have consumed
the backticked span and the stored message would contain no backticks.
cc7dddc0 has none for exactly that reason. So this rule would have fired on
none of the 120, and blocking carries no measured false-positive cost.
"""

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.git_message_backtick import (
    GitMessageBacktickHandler,
)

BACKTICK = "`"


def _bash(command: str) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test (Plan 00116)."""
    reset_data_layer()
    yield
    reset_data_layer()


class TestGetRules:
    def test_returns_one_rule(self) -> None:
        rules = GitMessageBacktickHandler().get_rules()
        assert len(rules) == 1
        assert isinstance(rules[0], Rule)
        assert rules[0].rule_id == RuleID.GIT_MESSAGE_BACKTICK
        assert rules[0].verbose


class TestDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder (Plan 00116)."""

    def _hook_input(self, transcript_path: str) -> dict[str, object]:
        command = f'git commit -m "see {BACKTICK}ls{BACKTICK}"'
        return {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "transcript_path": transcript_path,
        }

    def test_deny_leads_with_rule_id(self) -> None:
        handler = GitMessageBacktickHandler()
        result = handler.handle(self._hook_input("/tmp/agent-a/transcript.jsonl"))
        assert result.reason.startswith(f"BLOCKED [{RuleID.GIT_MESSAGE_BACKTICK}]")

    def test_first_fire_is_verbose(self) -> None:
        handler = GitMessageBacktickHandler()
        result = handler.handle(self._hook_input("/tmp/agent-a/transcript.jsonl"))
        assert "cc7dddc0" in result.reason

    def test_second_fire_same_agent_is_terse(self) -> None:
        handler = GitMessageBacktickHandler()
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input(transcript_path))
        result = handler.handle(self._hook_input(transcript_path))
        assert "cc7dddc0" not in result.reason
        assert "Fix:" in result.reason

    def test_different_agent_is_independently_verbose(self) -> None:
        handler = GitMessageBacktickHandler()
        handler.handle(self._hook_input("/tmp/agent-a/transcript.jsonl"))
        result = handler.handle(self._hook_input("/tmp/agent-b/transcript.jsonl"))
        assert "cc7dddc0" in result.reason

    def test_missing_transcript_path_fails_toward_verbose_every_time(self) -> None:
        handler = GitMessageBacktickHandler()
        hook_input = _bash(f'git commit -m "see {BACKTICK}ls{BACKTICK}"')
        first = handler.handle(hook_input)
        second = handler.handle(hook_input)
        assert "cc7dddc0" in first.reason
        assert "cc7dddc0" in second.reason


class TestDoubleQuotedBackticksAreBlocked:
    """The uncovered half: a benign message silently losing its content."""

    def test_blocks_double_quoted_message_with_backticks(self) -> None:
        handler = GitMessageBacktickHandler()
        hook_input = _bash(
            f'git commit -m "now allows {BACKTICK}git branch{BACKTICK}, so it holds"'
        )
        assert handler.matches(hook_input)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_reproduces_the_actual_corrupting_commit(self) -> None:
        """The real cc7dddc0 shape, not a synthetic stand-in."""
        handler = GitMessageBacktickHandler()
        hook_input = _bash(
            f'git commit -m "Regression test pins an interaction: pipe_blocker now '
            f"allows {BACKTICK}git branch --list{BACKTICK}, so the force-delete form "
            f'must still be denied by destructive_git"'
        )
        assert handler.matches(hook_input)

    def test_blocks_equals_form_of_message_flag(self) -> None:
        handler = GitMessageBacktickHandler()
        assert handler.matches(_bash(f'git commit --message="see {BACKTICK}ls{BACKTICK} output"'))

    def test_blocks_git_tag_message_too(self) -> None:
        """`git tag -a vX -m "..."` has the identical hazard, and
        CLAUDE/development/RELEASING.md instructs exactly that form for every
        release — so the corruption path is live on the release route."""
        handler = GitMessageBacktickHandler()
        assert handler.matches(
            _bash(f'git tag -a v9.9.9 -m "ships the {BACKTICK}plan-qa{BACKTICK} check"')
        )

    def test_reason_names_both_concrete_remedies(self) -> None:
        handler = GitMessageBacktickHandler()
        result = handler.handle(_bash(f'git commit -m "see {BACKTICK}x{BACKTICK}"'))
        assert "single" in result.reason.lower()
        assert "-F" in result.reason


class TestCommandRespellingCannotEvade:
    """Built on the shared GIT_INVOCATION fragment, not a local regex.

    `git -C /path` silently bypassed four handlers before that fragment
    existed, and the evasion-classification guard's own message is blunt
    about it: silence is not a classification. These pin the respellings.
    """

    def test_global_option_before_subcommand_still_matches(self) -> None:
        handler = GitMessageBacktickHandler()
        assert handler.matches(_bash(f'git -C /workspace commit -m "see {BACKTICK}ls{BACKTICK}"'))

    def test_multiple_global_options_still_match(self) -> None:
        handler = GitMessageBacktickHandler()
        assert handler.matches(
            _bash(f'git -C /workspace -c user.name=x commit -m "see {BACKTICK}ls{BACKTICK}"')
        )

    def test_path_qualified_git_still_matches(self) -> None:
        handler = GitMessageBacktickHandler()
        assert handler.matches(_bash(f'/usr/bin/git commit -m "see {BACKTICK}ls{BACKTICK}"'))

    def test_git_after_a_separator_still_matches(self) -> None:
        """A real second command in a chain must still be seen."""
        handler = GitMessageBacktickHandler()
        assert handler.matches(_bash(f'cd /workspace && git commit -m "{BACKTICK}ls{BACKTICK}"'))


class TestSafeFormsAreNeverBlocked:
    """Every form that does NOT substitute must pass untouched.

    This is the half that decides whether the handler survives contact with
    real use: single-quoting is the documented remedy, so a handler that
    flagged it would leave no way to comply.
    """

    def test_single_quoted_message_with_backticks_is_allowed(self) -> None:
        handler = GitMessageBacktickHandler()
        assert not handler.matches(
            _bash(f"git commit -m 'now allows {BACKTICK}git branch{BACKTICK}, so it holds'")
        )

    def test_escaped_backticks_in_double_quotes_are_allowed(self) -> None:
        """A backslash-escaped backtick does not substitute — it is literal."""
        handler = GitMessageBacktickHandler()
        assert not handler.matches(_bash('git commit -m "see \\`git branch\\` output"'))

    def test_plain_double_quoted_message_is_allowed(self) -> None:
        handler = GitMessageBacktickHandler()
        assert not handler.matches(_bash('git commit -m "Fix: ordinary message, no substitution"'))

    def test_heredoc_message_form_is_allowed(self) -> None:
        """The -F form this repo uses for long messages carries no hazard."""
        handler = GitMessageBacktickHandler()
        assert not handler.matches(_bash("git commit -F /tmp/message.txt"))

    def test_non_git_command_with_backticks_is_allowed(self) -> None:
        handler = GitMessageBacktickHandler()
        assert not handler.matches(_bash(f'echo "the {BACKTICK}date{BACKTICK} is now"'))

    def test_git_command_that_is_not_commit_or_tag_is_allowed(self) -> None:
        handler = GitMessageBacktickHandler()
        assert not handler.matches(_bash(f'git log --grep="{BACKTICK}x{BACKTICK}"'))

    def test_empty_command_is_allowed(self) -> None:
        handler = GitMessageBacktickHandler()
        assert not handler.matches(_bash(""))


class TestDeclaredMetadataIsReal:
    """The handler's own declarations must be exercised, not just written.

    `get_acceptance_tests()` was initially written against an invented
    AcceptanceTest signature. Every test above still passed, because none of
    them called it — the playbook generator would have been the first thing
    to find out. Same blind spot as a guard that is never run: writing the
    declaration is not evidence that it works.
    """

    def test_acceptance_tests_construct_and_cover_both_directions(self) -> None:
        handler = GitMessageBacktickHandler()
        tests = handler.get_acceptance_tests()
        assert tests, "handler declares no acceptance tests"
        decisions = {test.expected_decision for test in tests}
        assert Decision.DENY in decisions, "no positive case"
        assert Decision.ALLOW in decisions, "no negative case — a harness that"
        for test in tests:
            assert test.title
            assert test.command
            assert test.description

    def test_acceptance_deny_case_actually_denies(self) -> None:
        """Guards against a declared command drifting out of step with the
        rule, which would make the playbook assert something untrue."""
        handler = GitMessageBacktickHandler()
        for test in handler.get_acceptance_tests():
            if test.expected_decision is not Decision.DENY:
                continue
            hook_input = _bash(test.command)
            assert handler.matches(hook_input), f"declared DENY case does not match: {test.command}"
            assert handler.handle(hook_input).decision == Decision.DENY

    def test_claude_md_guidance_names_the_permitted_forms(self) -> None:
        """Guidance that only says 'blocked' leaves no route to comply."""
        guidance = GitMessageBacktickHandler().get_claude_md()
        assert "single" in guidance.lower()
        assert "-F" in guidance
