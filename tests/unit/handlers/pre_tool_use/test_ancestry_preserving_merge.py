"""Tests for AncestryPreservingMergeHandler (Plan 00207).

A squash merge collapses N commits into one new commit on the target, and a
rebase merge replays them as new commits with new shas. In both cases the
branch's original commits never become ancestors of the target, so
`git branch -d` refuses the branch permanently even though its content is
fully upstream. This handler blocks the three ancestry-severing spellings
that fire from a Bash tool call: `git merge --squash`, `gh pr merge --squash`
and `gh pr merge --rebase`.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.ancestry_preserving_merge import (
    AncestryPreservingMergeHandler,
)


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test (Plan 00116)."""
    reset_data_layer()
    yield
    reset_data_layer()


class TestInitialisation:
    """Handler identity: name, priority, terminal flag, config key."""

    @pytest.fixture
    def handler(self) -> AncestryPreservingMergeHandler:
        return AncestryPreservingMergeHandler()

    def test_config_key(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.config_key == "ancestry_preserving_merge"

    def test_priority_in_safety_band(self, handler: AncestryPreservingMergeHandler) -> None:
        # Plan 00207: "priority in the 10-20 safety band alongside destructive_git"
        assert 10 <= handler.priority <= 20

    def test_not_terminal(self, handler: AncestryPreservingMergeHandler) -> None:
        """`mode: warn` returns ALLOW, and a terminal ALLOW ends the chain.

        The chain breaks on ANY terminal match whatever it decided, so a
        terminal handler here would silently disable every higher-numbered
        handler for that command whenever warn mode allowed one through.
        Denying is unaffected: core/chain.py keeps the most restrictive
        decision seen, so a non-terminal deny still denies.
        """
        assert handler.terminal is False

    def test_default_mode_is_block(self, handler: AncestryPreservingMergeHandler) -> None:
        assert hasattr(handler, "_mode")
        assert handler._mode == "block"


class TestMatchesGitMergeSquash:
    """git merge --squash — the direct case."""

    @pytest.fixture
    def handler(self) -> AncestryPreservingMergeHandler:
        return AncestryPreservingMergeHandler()

    def test_squash_flag_before_branch(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("git merge --squash feature-branch")) is True

    def test_squash_flag_after_branch(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("git merge feature-branch --squash")) is True

    def test_case_insensitive(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("GIT MERGE --SQUASH feature-branch")) is True

    def test_inside_echo_quotes(self, handler: AncestryPreservingMergeHandler) -> None:
        # Acceptance tests wrap dangerous commands in echo for safe testing
        # (destructive_git / git_stash precedent) — the handler must still see it.
        assert handler.matches(_bash('echo "git merge --squash feature-branch"')) is True

    def test_in_command_chain(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("git fetch && git merge --squash feature-branch")) is True


class TestMatchesGitMergeSquashEvasion:
    """Plan 00202 evasion spellings: global options + line continuation."""

    @pytest.fixture
    def handler(self) -> AncestryPreservingMergeHandler:
        return AncestryPreservingMergeHandler()

    def test_git_dash_c_global_option(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("git -C /workspace merge --squash feature")) is True

    def test_no_pager_global_option(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("git --no-pager merge --squash feature")) is True

    def test_trailing_backslash_line_continuation(
        self, handler: AncestryPreservingMergeHandler
    ) -> None:
        assert handler.matches(_bash("git \\\n  merge --squash feature-branch")) is True

    def test_dash_c_plus_line_continuation(self, handler: AncestryPreservingMergeHandler) -> None:
        assert (
            handler.matches(_bash("git \\\n  -C /workspace \\\n  merge --squash feature-branch"))
            is True
        )


class TestMatchesGhPrMergeSquash:
    """gh pr merge --squash."""

    @pytest.fixture
    def handler(self) -> AncestryPreservingMergeHandler:
        return AncestryPreservingMergeHandler()

    def test_squash_flag(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("gh pr merge --squash 123")) is True

    def test_squash_flag_after_number(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("gh pr merge 123 --squash")) is True

    def test_case_insensitive(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("GH PR MERGE --SQUASH 123")) is True

    def test_inside_echo_quotes(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash('echo "gh pr merge --squash 123"')) is True


class TestMatchesGhPrMergeRebase:
    """gh pr merge --rebase — the case that widened this plan's scope."""

    @pytest.fixture
    def handler(self) -> AncestryPreservingMergeHandler:
        return AncestryPreservingMergeHandler()

    def test_rebase_flag(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("gh pr merge --rebase 123")) is True

    def test_rebase_flag_after_number(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("gh pr merge 123 --rebase")) is True

    def test_case_insensitive(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("GH PR MERGE --REBASE 123")) is True

    def test_inside_echo_quotes(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash('echo "gh pr merge --rebase 123"')) is True


class TestFalsePositivesStayAllowed:
    """Every command Success Criteria says must stay ALLOWED."""

    @pytest.fixture
    def handler(self) -> AncestryPreservingMergeHandler:
        return AncestryPreservingMergeHandler()

    def test_plain_git_merge(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("git merge feature-branch")) is False

    def test_git_merge_no_ff(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("git merge --no-ff feature-branch")) is False

    def test_gh_pr_merge_merge_flag(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("gh pr merge --merge 123")) is False

    def test_local_git_rebase_onto_main(self, handler: AncestryPreservingMergeHandler) -> None:
        # A LOCAL rebase preserves ancestry once merged with --no-ff; it is the
        # REBASE MERGE integration button that severs it, not this command.
        assert handler.matches(_bash("git rebase main")) is False

    def test_word_squash_in_commit_message(self, handler: AncestryPreservingMergeHandler) -> None:
        hook_input = _bash('git commit -m "squash these debug prints later"')
        assert handler.matches(hook_input) is False

    def test_word_rebase_in_commit_message(self, handler: AncestryPreservingMergeHandler) -> None:
        hook_input = _bash('git commit -m "rebase workflow notes"')
        assert handler.matches(hook_input) is False

    def test_word_squash_in_filename(self, handler: AncestryPreservingMergeHandler) -> None:
        hook_input = _bash("git add docs/squash-and-rebase-notes.md")
        assert handler.matches(hook_input) is False

    def test_git_status(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("git status")) is False

    def test_non_bash_tool(self, handler: AncestryPreservingMergeHandler) -> None:
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.sh", "content": "git merge --squash x"},
        }
        assert handler.matches(hook_input) is False

    def test_empty_command(self, handler: AncestryPreservingMergeHandler) -> None:
        assert handler.matches(_bash("")) is False

    def test_none_command(self, handler: AncestryPreservingMergeHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": None}}
        assert handler.matches(hook_input) is False


class TestEscapeHatch:
    """MUST_SQUASH_BECAUSE bypasses the block (block mode only)."""

    @pytest.fixture
    def handler(self) -> AncestryPreservingMergeHandler:
        return AncestryPreservingMergeHandler()

    def test_escape_hatch_bypasses_squash_merge(
        self, handler: AncestryPreservingMergeHandler
    ) -> None:
        hook_input = _bash(
            'MUST_SQUASH_BECAUSE="platform mandates squash-only merging"; '
            "git merge --squash feature-branch"
        )
        assert handler.matches(hook_input) is False

    def test_escape_hatch_bypasses_gh_rebase_merge(
        self, handler: AncestryPreservingMergeHandler
    ) -> None:
        hook_input = _bash(
            'MUST_SQUASH_BECAUSE="platform mandates rebase-only merging"; '
            "gh pr merge --rebase 123"
        )
        assert handler.matches(hook_input) is False

    def test_escape_hatch_requires_non_empty_reason(
        self, handler: AncestryPreservingMergeHandler
    ) -> None:
        hook_input = _bash('MUST_SQUASH_BECAUSE=""; git merge --squash feature-branch')
        assert handler.matches(hook_input) is True

    def test_missing_escape_hatch_still_blocked(
        self, handler: AncestryPreservingMergeHandler
    ) -> None:
        assert handler.matches(_bash("git merge --squash feature-branch")) is True


class TestHandleBlockMode:
    """handle() in the default 'block' mode."""

    @pytest.fixture
    def handler(self) -> AncestryPreservingMergeHandler:
        return AncestryPreservingMergeHandler()

    def test_returns_deny(self, handler: AncestryPreservingMergeHandler) -> None:
        result = handler.handle(_bash("git merge --squash feature-branch"))
        assert result.decision == Decision.DENY

    def test_reason_explains_ancestry_not_style(
        self, handler: AncestryPreservingMergeHandler
    ) -> None:
        result = handler.handle(_bash("git merge --squash feature-branch"))
        assert result.reason is not None
        assert "ancestor" in result.reason.lower()
        assert "branch -d" in result.reason

    def test_reason_names_no_ff_alternative(self, handler: AncestryPreservingMergeHandler) -> None:
        result = handler.handle(_bash("git merge --squash feature-branch"))
        assert result.reason is not None
        assert "--no-ff" in result.reason

    def test_reason_documents_escape_hatch(self, handler: AncestryPreservingMergeHandler) -> None:
        result = handler.handle(_bash("git merge --squash feature-branch"))
        assert result.reason is not None
        assert "MUST_SQUASH_BECAUSE" in result.reason

    def test_gh_pr_merge_squash_reason(self, handler: AncestryPreservingMergeHandler) -> None:
        result = handler.handle(_bash("gh pr merge --squash 123"))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "squash" in result.reason.lower()

    def test_gh_pr_merge_rebase_reason(self, handler: AncestryPreservingMergeHandler) -> None:
        result = handler.handle(_bash("gh pr merge --rebase 123"))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "rebase" in result.reason.lower()


class TestHandleWarnMode:
    """handle() in 'warn' mode: advisory only, never denies."""

    @pytest.fixture
    def handler(self) -> AncestryPreservingMergeHandler:
        handler = AncestryPreservingMergeHandler()
        handler._mode = "warn"
        return handler

    def test_returns_allow(self, handler: AncestryPreservingMergeHandler) -> None:
        result = handler.handle(_bash("git merge --squash feature-branch"))
        assert result.decision == Decision.ALLOW

    def test_guidance_present(self, handler: AncestryPreservingMergeHandler) -> None:
        result = handler.handle(_bash("git merge --squash feature-branch"))
        assert result.guidance is not None
        assert "ancestor" in result.guidance.lower()

    def test_matches_unaffected_by_mode(self) -> None:
        block_handler = AncestryPreservingMergeHandler()
        warn_handler = AncestryPreservingMergeHandler()
        warn_handler._mode = "warn"

        hook_input = _bash("git merge --squash feature-branch")
        assert block_handler.matches(hook_input) == warn_handler.matches(hook_input)


class TestGetClaudeMd:
    def test_returns_content(self) -> None:
        handler = AncestryPreservingMergeHandler()
        content = handler.get_claude_md()
        assert content is not None

    def test_mentions_ancestry_not_style_opinion(self) -> None:
        handler = AncestryPreservingMergeHandler()
        content = handler.get_claude_md() or ""
        assert "ancestor" in content.lower() or "ancestry" in content.lower()

    def test_documents_web_ui_non_goal(self) -> None:
        """Plan 00207 Non-Goals: must not imply coverage of web-UI squash merges."""
        handler = AncestryPreservingMergeHandler()
        content = handler.get_claude_md() or ""
        assert "web" in content.lower()

    def test_documents_escape_hatch(self) -> None:
        handler = AncestryPreservingMergeHandler()
        content = handler.get_claude_md() or ""
        assert "MUST_SQUASH_BECAUSE" in content


class TestGetRules:
    """get_rules() declares the 3 Rule objects (Decision B)."""

    @pytest.fixture
    def handler(self) -> AncestryPreservingMergeHandler:
        return AncestryPreservingMergeHandler()

    def test_returns_three_rules(self, handler: AncestryPreservingMergeHandler) -> None:
        rules = handler.get_rules()
        assert len(rules) == 3
        assert all(isinstance(rule, Rule) for rule in rules)

    def test_rule_ids_match_constants(self, handler: AncestryPreservingMergeHandler) -> None:
        expected = {
            RuleID.GIT_MERGE_SQUASH,
            RuleID.GH_PR_MERGE_SQUASH,
            RuleID.GH_PR_MERGE_REBASE,
        }
        actual = {rule.rule_id for rule in handler.get_rules()}
        assert actual == expected

    def test_every_rule_has_non_empty_verbose(
        self, handler: AncestryPreservingMergeHandler
    ) -> None:
        for rule in handler.get_rules():
            assert rule.verbose


class TestDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder (Plan 00116)."""

    @pytest.fixture
    def handler(self) -> AncestryPreservingMergeHandler:
        return AncestryPreservingMergeHandler()

    def _hook_input(self, command: str, transcript_path: str) -> dict:
        return {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "transcript_path": transcript_path,
        }

    def test_deny_leads_with_rule_id(self, handler: AncestryPreservingMergeHandler) -> None:
        result = handler.handle(
            self._hook_input("git merge --squash feature", "/tmp/agent-a/transcript.jsonl")
        )
        assert result.reason.startswith(f"BLOCKED [{RuleID.GIT_MERGE_SQUASH}]")

    def test_first_fire_is_verbose(self, handler: AncestryPreservingMergeHandler) -> None:
        result = handler.handle(
            self._hook_input("git merge --squash feature", "/tmp/agent-a/transcript.jsonl")
        )
        assert "WHY THIS MATTERS" in result.reason

    def test_second_fire_same_rule_same_agent_is_terse(
        self, handler: AncestryPreservingMergeHandler
    ) -> None:
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input("git merge --squash feature", transcript_path))
        result = handler.handle(self._hook_input("git merge --squash other", transcript_path))
        assert "WHY THIS MATTERS" not in result.reason
        assert "Fix:" in result.reason

    def test_different_rule_same_agent_is_independently_verbose(
        self, handler: AncestryPreservingMergeHandler
    ) -> None:
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input("git merge --squash feature", transcript_path))
        result = handler.handle(self._hook_input("gh pr merge --squash 123", transcript_path))
        assert "WHY THIS MATTERS" in result.reason

    def test_different_agent_is_independently_verbose(
        self, handler: AncestryPreservingMergeHandler
    ) -> None:
        handler.handle(
            self._hook_input("git merge --squash feature", "/tmp/agent-a/transcript.jsonl")
        )
        result = handler.handle(
            self._hook_input("git merge --squash feature", "/tmp/agent-b/transcript.jsonl")
        )
        assert "WHY THIS MATTERS" in result.reason

    def test_missing_transcript_path_fails_toward_verbose_every_time(
        self, handler: AncestryPreservingMergeHandler
    ) -> None:
        hook_input = _bash("git merge --squash feature")
        first = handler.handle(hook_input)
        second = handler.handle(hook_input)
        assert "WHY THIS MATTERS" in first.reason
        assert "WHY THIS MATTERS" in second.reason


class TestGetAcceptanceTests:
    def test_block_mode_returns_deny_tests(self) -> None:
        handler = AncestryPreservingMergeHandler()
        tests = handler.get_acceptance_tests()
        deny_tests = [t for t in tests if t.expected_decision == Decision.DENY]
        assert len(deny_tests) >= 3

    def test_includes_allow_case(self) -> None:
        """False-positive coverage: at least one test must expect ALLOW."""
        handler = AncestryPreservingMergeHandler()
        tests = handler.get_acceptance_tests()
        allow_tests = [t for t in tests if t.expected_decision == Decision.ALLOW]
        assert len(allow_tests) >= 1

    def test_warn_mode_returns_allow_tests(self) -> None:
        handler = AncestryPreservingMergeHandler()
        handler._mode = "warn"
        tests = handler.get_acceptance_tests()
        assert all(t.expected_decision == Decision.ALLOW for t in tests)
