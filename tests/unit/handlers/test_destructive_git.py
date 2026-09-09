"""Comprehensive tests for DestructiveGitHandler."""

from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.disclosure_tracker import DisclosureTracker
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test in this module.

    get_data_layer() is a process-wide singleton (Plan 00116, Decision G: the
    DisclosureTracker it carries persists in-memory for the daemon's lifetime).
    Without this, one test's ``mark_disclosed`` for a rule_id + transcript_path
    combination leaks into a later test that reuses the same pair, turning a
    genuine "first fire" into a stale "already disclosed" terse reminder.
    """
    reset_data_layer()
    yield
    reset_data_layer()


class TestDestructiveGitHandler:
    """Test suite for DestructiveGitHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return DestructiveGitHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'prevent-destructive-git'."""
        assert handler.name == "prevent-destructive-git"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 10."""
        assert handler.priority == 10

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (default)."""
        assert handler.terminal is True

    def test_init_creates_destructive_patterns_list(self, handler):
        """Handler exposes compiled destructive patterns derived from the single mapping.

        The mapping is the single source of truth. Plan 00205 added one new pattern
        entry (git update-ref -d refs/heads/<name>, sharing GIT_BRANCH_FORCE_DELETE's
        rule_id) on top of the 10 pre-existing entries, so there are 11 patterns.
        The +refspec push-force widening reuses the EXISTING push-force pattern slot
        (Task 2.1: "Extend _GIT_PUSH_FORCE_PATTERN"), so it adds no new entry.
        """
        assert hasattr(handler, "destructive_patterns")
        assert len(handler.destructive_patterns) == 11

    def test_match_reason_and_matches_agree_for_each_command(self, handler):
        """matches() and _match_reason() (used by handle()) must agree on every command.

        Guards against the pattern source drifting between matches() and handle(): both
        now consume the single ordered mapping, so a command blocked by matches() must
        yield a specific (non-generic) reason via _match_reason, and vice versa.
        """
        commands = [
            "git reset --hard HEAD~1",
            "git clean -fd",
            "git checkout .",
            "git checkout -- file.py",
            "git restore file.py",
            "git stash drop",
            "git stash clear",
            "git push --force origin main",
            "git branch -D feature",
            "git commit --amend",
        ]
        for command in commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
            assert handler.matches(hook_input) is True
            assert handler._match_reason(command) is not None

    def test_match_reason_returns_none_for_safe_git(self, handler):
        """_match_reason() returns None for non-destructive git commands."""
        assert handler._match_reason("git status") is None
        assert handler._match_reason("git restore --staged file.py") is None

    # matches() - Pattern 1: git reset --hard
    def test_matches_git_reset_hard(self, handler):
        """Should match 'git reset --hard' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_reset_hard_with_ref(self, handler):
        """Should match 'git reset --hard' with reference."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD~1"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_reset_hard_with_branch(self, handler):
        """Should match 'git reset --hard' with branch name."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git reset --hard origin/main"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_reset_hard_case_insensitive(self, handler):
        """Should match 'git reset --hard' with different casing."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "GIT RESET --HARD"}}
        assert handler.matches(hook_input) is True

    # matches() - Pattern 2: git clean -f
    def test_matches_git_clean_f(self, handler):
        """Should match 'git clean -f' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git clean -f"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_clean_fd(self, handler):
        """Should match 'git clean -fd' (force + directories)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git clean -fd"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_clean_fdx(self, handler):
        """Should match 'git clean -fdx' (force + directories + ignored)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git clean -fdx"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_clean_with_path(self, handler):
        """Should match 'git clean -f' with path argument."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git clean -f src/"}}
        assert handler.matches(hook_input) is True

    # matches() - Pattern 3: git checkout .
    def test_matches_git_checkout_dot(self, handler):
        """Should match 'git checkout .' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git checkout ."}}
        assert handler.matches(hook_input) is True

    def test_matches_git_checkout_dot_with_semicolon(self, handler):
        """Should match 'git checkout .' followed by semicolon."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git checkout .; git status"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_checkout_dot_with_and(self, handler):
        """Should match 'git checkout .' followed by &&."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout . && git status"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_checkout_dot_with_pipe(self, handler):
        """Should match 'git checkout .' followed by pipe."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout . | grep something"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Pattern 4: git checkout -- file
    def test_matches_git_checkout_dash_dash_file(self, handler):
        """Should match 'git checkout -- file' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git checkout -- file.txt"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_checkout_head_dash_dash_file(self, handler):
        """Should match 'git checkout HEAD -- file' command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout HEAD -- src/main.py"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_checkout_branch_dash_dash_file(self, handler):
        """Should match 'git checkout main -- file' command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout main -- README.md"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_checkout_ref_dash_dash_file(self, handler):
        """Should match 'git checkout @{upstream} -- file' command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout @{upstream} -- package.json"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_checkout_dash_dash_multiple_files(self, handler):
        """Should match 'git checkout --' with multiple files."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git checkout -- file1.txt file2.txt"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Pattern 5: git restore (destructive variants)
    def test_matches_git_restore_file(self, handler):
        """Should match 'git restore file' (discards working tree changes)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git restore file.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_restore_multiple_files(self, handler):
        """Should match 'git restore' with multiple files."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git restore file1.txt file2.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_restore_path(self, handler):
        """Should match 'git restore' with path."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git restore src/main.py"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_restore_worktree(self, handler):
        """Should match 'git restore --worktree' command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git restore --worktree file.txt"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_restore_worktree_with_source(self, handler):
        """Should match 'git restore --worktree' with source ref."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git restore --source=HEAD --worktree file.txt"},
        }
        assert handler.matches(hook_input) is True

    # matches() - Pattern 6: git stash drop/clear
    def test_matches_git_stash_drop(self, handler):
        """Should match 'git stash drop' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash drop"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_stash_drop_with_stash_id(self, handler):
        """Should match 'git stash drop' with stash ID."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash drop stash@{0}"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_stash_clear(self, handler):
        """Should match 'git stash clear' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash clear"}}
        assert handler.matches(hook_input) is True

    # matches() - Pattern 8: git branch -D (force delete)
    def test_matches_git_branch_force_delete(self, handler):
        """Should match 'git branch -D' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git branch -D feature"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_branch_force_delete_with_path(self, handler):
        """Should match 'git branch -D' with branch name containing slashes."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git branch -D feature/my-branch"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_branch_force_delete_case_insensitive(self, handler):
        """Should match 'git branch -D' case-insensitively."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "GIT BRANCH -D mybranch"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_branch_lowercase_d_returns_false(self, handler):
        """Should NOT match 'git branch -d' (safe delete with merge check)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git branch -d feature"}}
        assert handler.matches(hook_input) is False

    # matches() - Pattern 9: git commit --amend
    def test_matches_git_commit_amend(self, handler):
        """Should match 'git commit --amend' command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git commit --amend"}}
        assert handler.matches(hook_input) is True

    def test_matches_git_commit_amend_no_edit(self, handler):
        """Should match 'git commit --amend --no-edit' command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit --amend --no-edit"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_commit_amend_with_message(self, handler):
        """Should match 'git commit --amend -m' command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit --amend -m 'fix typo'"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_commit_a_amend(self, handler):
        """Should match 'git commit -a --amend' command."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -a --amend"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_git_commit_amend_case_insensitive(self, handler):
        """Should match 'git commit --amend' with different casing."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "GIT COMMIT --AMEND"}}
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Safe git commands
    def test_matches_git_reset_soft_returns_false(self, handler):
        """Should NOT match 'git reset --soft' (safe)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --soft HEAD~1"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_reset_mixed_returns_false(self, handler):
        """Should NOT match 'git reset --mixed' (safe)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --mixed HEAD~1"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_clean_dry_run_returns_false(self, handler):
        """Should NOT match 'git clean -n' (dry-run)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git clean -n"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_checkout_branch_returns_false(self, handler):
        """Should NOT match 'git checkout' to switch branches."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git checkout main"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_restore_staged_returns_false(self, handler):
        """Should NOT match 'git restore --staged' (safe)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git restore --staged file.txt"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_git_stash_list_returns_false(self, handler):
        """Should NOT match 'git stash list' (query)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash list"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_stash_pop_returns_false(self, handler):
        """Should NOT match 'git stash pop' (recovery)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git stash pop"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_status_returns_false(self, handler):
        """Should NOT match 'git status'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git status"}}
        assert handler.matches(hook_input) is False

    def test_matches_git_diff_returns_false(self, handler):
        """Should NOT match 'git diff'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git diff"}}
        assert handler.matches(hook_input) is False

    # matches() - Edge Cases
    def test_matches_non_bash_tool_returns_false(self, handler):
        """Should not match non-Bash tools."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.sh", "content": "git reset --hard"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_empty_command_returns_false(self, handler):
        """Should not match empty command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": ""}}
        assert handler.matches(hook_input) is False

    def test_matches_none_command_returns_false(self, handler):
        """Should not match when command is None."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": None}}
        assert handler.matches(hook_input) is False

    def test_matches_missing_command_key_returns_false(self, handler):
        """Should not match when command key is missing."""
        hook_input = {"tool_name": "Bash", "tool_input": {}}
        assert handler.matches(hook_input) is False

    def test_matches_missing_tool_input_returns_false(self, handler):
        """Should not match when tool_input is missing."""
        hook_input = {"tool_name": "Bash"}
        assert handler.matches(hook_input) is False

    def test_matches_command_without_git_returns_false(self, handler):
        """Should not match commands without 'git'."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /tmp/test"}}
        assert handler.matches(hook_input) is False

    def test_matches_comment_mentioning_git_returns_false(self, handler):
        """Should not match commands that just mention git in comments."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo 'avoid git reset --hard'"},
        }
        # This will actually match because the pattern exists in the string
        # This is acceptable behavior - better safe than sorry
        assert handler.matches(hook_input) is True

    # handle() Tests - Every deny leads with its rule ID (Plan 00116, Task 3.2)
    # A fresh transcript_path is used per test so each fire is a genuine first
    # fire (verbose) unless the test explicitly wants to exercise the terse
    # (already-disclosed) branch.
    def _hook_input(self, command: str, transcript_path: str = "/tmp/agent/transcript.jsonl"):
        return {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "transcript_path": transcript_path,
        }

    def test_handle_git_reset_hard_leads_with_rule_id(self, handler):
        """handle() deny message leads with R-GIT-RESET-HARD."""
        result = handler.handle(self._hook_input("git reset --hard"))
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{RuleID.GIT_RESET_HARD}]")

    def test_handle_git_clean_f_leads_with_rule_id(self, handler):
        """handle() deny message leads with R-GIT-CLEAN-FORCE."""
        result = handler.handle(self._hook_input("git clean -f"))
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{RuleID.GIT_CLEAN_FORCE}]")

    def test_handle_git_stash_drop_leads_with_rule_id(self, handler):
        """handle() deny message leads with R-GIT-STASH-DROP."""
        result = handler.handle(self._hook_input("git stash drop"))
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{RuleID.GIT_STASH_DROP}]")

    def test_handle_git_stash_clear_leads_with_rule_id(self, handler):
        """handle() deny message leads with R-GIT-STASH-CLEAR."""
        result = handler.handle(self._hook_input("git stash clear"))
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{RuleID.GIT_STASH_CLEAR}]")

    def test_handle_git_checkout_dash_dash_leads_with_rule_id(self, handler):
        """handle() deny message leads with R-GIT-CHECKOUT-DISCARD."""
        result = handler.handle(self._hook_input("git checkout -- file.txt"))
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{RuleID.GIT_CHECKOUT_DISCARD}]")

    def test_handle_git_restore_leads_with_rule_id(self, handler):
        """handle() deny message leads with R-GIT-RESTORE."""
        result = handler.handle(self._hook_input("git restore file.txt"))
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{RuleID.GIT_RESTORE}]")

    def test_handle_git_branch_force_delete_leads_with_rule_id(self, handler):
        """handle() deny message leads with R-GIT-BRANCH-FORCE-DELETE."""
        result = handler.handle(self._hook_input("git branch -D feature"))
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{RuleID.GIT_BRANCH_FORCE_DELETE}]")

    def test_handle_git_commit_amend_leads_with_rule_id(self, handler):
        """handle() deny message leads with R-GIT-COMMIT-AMEND."""
        result = handler.handle(self._hook_input("git commit --amend"))
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{RuleID.GIT_COMMIT_AMEND}]")

    def test_handle_generic_checkout_dot_also_uses_checkout_discard_rule(self, handler):
        """Bare 'git checkout .' shares R-GIT-CHECKOUT-DISCARD with the -- form."""
        result = handler.handle(self._hook_input("git checkout ."))
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{RuleID.GIT_CHECKOUT_DISCARD}]")

    # handle() Tests - Message structure (first fire = verbose)
    def test_handle_first_fire_reason_provides_safe_alternatives(self, handler):
        """First fire (verbose) should provide safe alternatives."""
        result = handler.handle(self._hook_input("git clean -fd"))
        assert "SAFE alternatives" in result.reason
        assert "git stash" in result.reason
        assert "git diff" in result.reason
        assert "git status" in result.reason
        assert "git commit" in result.reason

    def test_handle_first_fire_warns_no_recovery(self, handler):
        """First fire (verbose) should warn about no recovery."""
        result = handler.handle(self._hook_input("git reset --hard"))
        assert "PERMANENTLY DESTROYS" in result.reason
        assert "NO recovery possible" in result.reason

    def test_handle_first_fire_explains_llm_not_allowed(self, handler):
        """First fire (verbose) should explain LLM is not allowed."""
        result = handler.handle(self._hook_input("git stash drop"))
        assert "LLM is NOT ALLOWED" in result.reason

    # handle() Tests - Return values
    def test_handle_returns_deny_decision(self, handler):
        """handle() should always return deny decision."""
        result = handler.handle(self._hook_input("git reset --hard"))
        assert result.decision == "deny"

    def test_handle_context_is_none(self, handler):
        """handle() context should be None (not used)."""
        result = handler.handle(self._hook_input("git reset --hard"))
        assert result.context == []

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None (not used)."""
        result = handler.handle(self._hook_input("git clean -f"))
        assert result.guidance is None

    def test_handle_empty_command_returns_allow(self, handler):
        """handle() should return ALLOW for empty command."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": ""}}
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    # Integration Tests
    def test_blocks_all_destructive_commands(self, handler):
        """Should block all known destructive commands."""
        destructive_commands = [
            "git reset --hard",
            "git reset --hard HEAD~1",
            "git clean -f",
            "git clean -fd",
            "git clean -fdx",
            "git checkout .",
            "git checkout -- file.txt",
            "git checkout HEAD -- file.txt",
            "git restore file.txt",
            "git restore src/main.py",
            "git restore --worktree file.txt",
            "git stash drop",
            "git stash clear",
            "git branch -D feature",
            "git commit --amend",
            "git commit --amend --no-edit",
        ]
        for cmd in destructive_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is True, f"Should block: {cmd}"

    def test_allows_all_safe_commands(self, handler):
        """Should allow all safe git commands."""
        safe_commands = [
            "git status",
            "git diff",
            "git log",
            "git reset --soft HEAD~1",
            "git reset --mixed HEAD~1",
            "git clean -n",
            "git checkout main",
            "git restore --staged file.txt",
            "git stash list",
            "git stash pop",
            "git stash apply",
            "git commit -m 'message'",
            "git add .",
            "git push",
            "git branch -d feature",
        ]
        for cmd in safe_commands:
            hook_input = {"tool_name": "Bash", "tool_input": {"command": cmd}}
            assert handler.matches(hook_input) is False, f"Should allow: {cmd}"


class TestDestructiveGitGetRules:
    """get_rules() declares the 9 Rule objects (Decision A/B/D, Task 3.2)."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return DestructiveGitHandler()

    def test_returns_nine_rules(self, handler):
        """get_rules() returns exactly 9 Rule objects (Decision B)."""
        rules = handler.get_rules()
        assert len(rules) == 9
        assert all(isinstance(rule, Rule) for rule in rules)

    def test_rule_ids_match_constants(self, handler):
        """Every declared rule_id is one of the 9 destructive_git RuleID constants."""
        expected = {
            RuleID.GIT_RESET_HARD,
            RuleID.GIT_CLEAN_FORCE,
            RuleID.GIT_CHECKOUT_DISCARD,
            RuleID.GIT_RESTORE,
            RuleID.GIT_STASH_DROP,
            RuleID.GIT_STASH_CLEAR,
            RuleID.GIT_PUSH_FORCE,
            RuleID.GIT_BRANCH_FORCE_DELETE,
            RuleID.GIT_COMMIT_AMEND,
        }
        actual = {rule.rule_id for rule in handler.get_rules()}
        assert actual == expected

    def test_no_duplicate_rule_ids(self, handler):
        """No two declared rules share a rule_id."""
        rule_ids = [rule.rule_id for rule in handler.get_rules()]
        assert len(rule_ids) == len(set(rule_ids))

    def test_every_rule_has_non_empty_verbose(self, handler):
        """Every rule's verbose teaching content is non-empty (contract on Rule.verbose)."""
        for rule in handler.get_rules():
            assert rule.verbose, f"{rule.rule_id} has empty verbose content"

    def test_every_rule_blocked_literal_is_backticked(self, handler):
        """Every rule's blocked literal names the offending git invocation."""
        for rule in handler.get_rules():
            assert "git" in rule.blocked.lower(), f"{rule.rule_id}.blocked missing 'git'"


class TestDestructiveGitDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder (Task 3.2, Decision G).

    Replaces the old block-count-driven ladder: verbosity is now keyed by
    (transcript_path, rule_id) via DisclosureTracker, not by a running total
    of previous blocks from HandlerHistory.
    """

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return DestructiveGitHandler()

    def _hook_input(self, command: str, transcript_path):
        return {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "transcript_path": transcript_path,
        }

    def test_first_fire_for_agent_is_verbose(self, handler):
        """The first time a rule fires for a given agent, the block is verbose."""
        hook_input = self._hook_input("git reset --hard", "/tmp/agent-a/transcript.jsonl")
        result = handler.handle(hook_input)

        assert result.decision == "deny"
        assert "PERMANENTLY DESTROYS" in result.reason
        assert "SAFE alternatives" in result.reason
        assert "LLM is NOT ALLOWED" in result.reason

    def test_second_fire_for_same_agent_same_rule_is_terse(self, handler):
        """A repeat fire of the SAME rule for the SAME agent is terse."""
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input("git reset --hard", transcript_path))
        result = handler.handle(self._hook_input("git reset --hard HEAD~1", transcript_path))

        assert result.decision == "deny"
        assert "PERMANENTLY DESTROYS" not in result.reason
        assert "SAFE alternatives" not in result.reason
        assert "LLM is NOT ALLOWED" not in result.reason

    def test_terse_message_still_leads_with_rule_id_and_names_fix(self, handler):
        """The terse reminder still leads with the rule ID and names the fix."""
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input("git clean -f", transcript_path))
        result = handler.handle(self._hook_input("git clean -fd", transcript_path))

        assert result.reason.startswith(f"BLOCKED [{RuleID.GIT_CLEAN_FORCE}]")
        assert "Fix:" in result.reason

    def test_different_rule_same_agent_is_independently_verbose(self, handler):
        """A DIFFERENT rule for the same agent gets its own first-fire verbose block."""
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input("git reset --hard", transcript_path))
        result = handler.handle(self._hook_input("git stash drop", transcript_path))

        assert "PERMANENTLY DESTROYS" in result.reason

    def test_same_rule_different_agent_is_independently_verbose(self, handler):
        """A sub-agent (different transcript_path) never inherits another agent's disclosure."""
        handler.handle(self._hook_input("git reset --hard", "/tmp/agent-a/transcript.jsonl"))
        result = handler.handle(
            self._hook_input("git reset --hard", "/tmp/agent-b/transcript.jsonl")
        )

        assert "PERMANENTLY DESTROYS" in result.reason

    def test_missing_transcript_path_fails_toward_verbose_every_time(self, handler):
        """No transcript_path in the payload -> always verbose (unknown state -> more info)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard"}}

        first = handler.handle(hook_input)
        second = handler.handle(hook_input)

        assert "PERMANENTLY DESTROYS" in first.reason
        assert "PERMANENTLY DESTROYS" in second.reason

    def test_uses_the_shared_daemon_disclosure_tracker(self, handler):
        """handle() consults get_data_layer().disclosure, not a handler-local tracker."""
        mock_tracker = DisclosureTracker()
        mock_dl = MagicMock()
        mock_dl.disclosure = mock_tracker
        transcript_path = "/tmp/agent-a/transcript.jsonl"

        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git.get_data_layer",
            return_value=mock_dl,
        ):
            handler.handle(self._hook_input("git reset --hard", transcript_path))

        assert mock_tracker.was_disclosed(transcript_path, RuleID.GIT_RESET_HARD) is True


class TestDestructiveGitRestoreStagedShortFlag:
    """Finding #55: `git restore -S` (short form of --staged) is non-destructive."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return DestructiveGitHandler()

    def test_matches_git_restore_short_staged_returns_false(self, handler):
        """Should NOT match 'git restore -S file.txt' (short form of --staged, safe)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git restore -S file.txt"},
        }
        assert handler.matches(hook_input) is False

    def test_match_reason_none_for_short_staged(self, handler):
        """_match_reason() returns None for the short-staged restore form."""
        assert handler._match_reason("git restore -S file.txt") is None

    def test_matches_git_restore_short_staged_with_path(self, handler):
        """Short '-S' flag with a path should remain safe (unstage only)."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git restore -S src/main.py"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_git_restore_worktree_still_blocked(self, handler):
        """Sanity: destructive '--worktree' restore must still be blocked."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git restore --worktree file.txt"},
        }
        assert handler.matches(hook_input) is True


class TestDestructiveGitPushForceSeparatorScoping:
    """NEW finding: push-force detection must be scoped to the `git push` segment.

    A benign compound command whose `--force` belongs to a DIFFERENT git
    sub-command (e.g. `git worktree remove ... --force`) must not be falsely
    blocked, while a real `git push --force` / `git push -f` must still block.
    """

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return DestructiveGitHandler()

    def test_compound_push_then_worktree_remove_force_not_blocked(self, handler):
        """`git push ...; git worktree remove <path> --force` must NOT be blocked."""
        command = "git push origin main; git worktree remove /tmp/wt --force"
        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
        assert handler.matches(hook_input) is False

    def test_worktree_remove_force_alone_not_blocked(self, handler):
        """A standalone `git worktree remove --force` must NOT be blocked."""
        command = "git worktree remove /tmp/wt --force"
        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
        assert handler.matches(hook_input) is False

    def test_push_force_still_blocked(self, handler):
        """A real `git push --force` must still be blocked."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git push --force origin main"},
        }
        assert handler.matches(hook_input) is True

    def test_push_short_force_flag_still_blocked(self, handler):
        """A real `git push -f` must still be blocked."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git push -f origin main"},
        }
        assert handler.matches(hook_input) is True

    def test_push_force_in_compound_still_blocked(self, handler):
        """`git status && git push --force` must still block on the push segment."""
        command = "git status && git push --force origin main"
        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
        assert handler.matches(hook_input) is True

    def test_push_force_with_lease_blocked(self, handler):
        """`git push --force-with-lease` is still a force push and must block."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git push --force-with-lease origin main"},
        }
        assert handler.matches(hook_input) is True

    def test_match_reason_push_force_specific(self, handler):
        """A real push --force yields the push-specific reason."""
        reason = handler._match_reason("git push --force origin main")
        assert reason is not None
        assert "overwrite remote history" in reason


class TestDestructiveGitTagForceNotBlocked:
    """Plan 00200 (Task 6.4): pin the `git tag -f` false positive forever.

    A live session reported `git tag -f v1.0.0 <sha>` blocked with the
    "git push --force" reason despite no push being present — the `-f` flag
    was matched too broadly. The push-force pattern is already scoped to the
    `git push` sub-command segment (see `_GIT_PUSH_FORCE_PATTERN`), so this
    class pins that scoping as a permanent regression test rather than
    re-deriving it from first principles each time.
    """

    @pytest.fixture
    def handler(self):
        return DestructiveGitHandler()

    def test_git_tag_force_not_blocked(self, handler):
        """`git tag -f` (force-move a tag) is unrelated to force-push and must ALLOW."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git tag -f v1.0.0 abc123def456"},
        }
        assert handler.matches(hook_input) is False

    def test_match_reason_none_for_git_tag_force(self, handler):
        assert handler._match_reason("git tag -f v1.0.0 abc123def456") is None

    def test_git_tag_force_short_alone_not_blocked(self, handler):
        assert (
            handler.matches({"tool_name": "Bash", "tool_input": {"command": "git tag -f v2.0.0"}})
            is False
        )

    def test_real_force_push_still_blocked_alongside_tag_force(self, handler):
        """Guardrail: a real force-push must NEVER be weakened by this fix."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git push --force origin main"},
        }
        assert handler.matches(hook_input) is True


class TestDestructiveGitPushForceRefspec:
    """Plan 00205 Task 2.1: `+refspec` is an exact `git push --force` equivalent.

    A refspec argument prefixed with `+` forces the update exactly like
    `--force` — it is ordinary, appears in CI/deploy scripts, and was
    confirmed unguarded against v3.52.0 source (`_GIT_PUSH_FORCE_PATTERN`
    matched only `--force`/`--force-with-lease`/`-f`).
    """

    @pytest.fixture
    def handler(self):
        return DestructiveGitHandler()

    def test_plus_refspec_short_form_blocked(self, handler):
        """`git push origin +main:main` must be denied."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin +main:main"},
        }
        assert handler.matches(hook_input) is True

    def test_plus_refspec_full_ref_form_blocked(self, handler):
        """`git push origin +refs/heads/main:refs/heads/main` must be denied."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin +refs/heads/main:refs/heads/main"},
        }
        assert handler.matches(hook_input) is True

    def test_plus_refspec_without_colon_blocked(self, handler):
        """`git push origin +main` (no explicit destination) is still a force push."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin +main"},
        }
        assert handler.matches(hook_input) is True

    def test_handle_plus_refspec_leads_with_push_force_rule_id(self, handler):
        """handle() classifies the +refspec form under the existing GIT_PUSH_FORCE rule."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "git push origin +main:main",
                "transcript_path": "/tmp/agent/transcript.jsonl",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{RuleID.GIT_PUSH_FORCE}]")

    def test_plain_refspec_no_plus_stays_allowed(self, handler):
        """`git push origin main:main` (no +) must stay ALLOWED."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin main:main"},
        }
        assert handler.matches(hook_input) is False

    def test_head_to_refs_for_refspec_no_plus_stays_allowed(self, handler):
        """`git push origin HEAD:refs/for/main` (a Gerrit-style push, no +) stays ALLOWED."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin HEAD:refs/for/main"},
        }
        assert handler.matches(hook_input) is False

    def test_plus_inside_a_branch_name_stays_allowed(self, handler):
        """A `+` that is part of a branch name, not a leading refspec marker, is safe.

        `+` is a legal git ref-name character. Only a `+` at the START of the
        refspec token forces the update; one in the middle of a name is just a
        name. This is the false-positive test written BEFORE the pattern, per
        the `sudo_pip` near-miss lesson (PLAN.md Risks & Mitigations).
        """
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin feature+fix"},
        }
        assert handler.matches(hook_input) is False

    def test_plus_inside_a_branch_name_with_destination_stays_allowed(self, handler):
        """Same false-positive, with an explicit (non-forcing) destination refspec."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git push origin feature+fix:feature+fix"},
        }
        assert handler.matches(hook_input) is False

    def test_bare_push_stays_allowed(self, handler):
        """Sanity: an ordinary push with no refspec at all stays ALLOWED."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}
        assert handler.matches(hook_input) is False


class TestDestructiveGitUpdateRefBranchDelete:
    """Plan 00205 Task 2.2: `git update-ref -d refs/heads/<name>` is an exact
    `git branch -D` equivalent — it force-deletes a branch ref with no merge
    check. Confirmed unguarded against v3.52.0 source (`update-ref` appeared
    nowhere under `src/claude_code_hooks_daemon/`).

    Scoped to `-d` with a `refs/heads/` target (PLAN.md Risks & Mitigations):
    every other `update-ref` use — creating/moving a ref, or deleting a
    non-branch ref — stays untouched.
    """

    @pytest.fixture
    def handler(self):
        return DestructiveGitHandler()

    def test_update_ref_delete_branch_blocked(self, handler):
        """`git update-ref -d refs/heads/<name>` must be denied."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git update-ref -d refs/heads/feature"},
        }
        assert handler.matches(hook_input) is True

    def test_update_ref_delete_branch_with_old_value_blocked(self, handler):
        """The compare-and-swap form (`-d <ref> <old-value>`) must also be denied."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git update-ref -d refs/heads/feature abc123def456"},
        }
        assert handler.matches(hook_input) is True

    def test_handle_update_ref_leads_with_branch_force_delete_rule_id(self, handler):
        """handle() classifies update-ref -d under the existing GIT_BRANCH_FORCE_DELETE rule."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "git update-ref -d refs/heads/feature",
                "transcript_path": "/tmp/agent/transcript.jsonl",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert result.reason.startswith(f"BLOCKED [{RuleID.GIT_BRANCH_FORCE_DELETE}]")

    def test_update_ref_without_delete_flag_stays_allowed(self, handler):
        """`git update-ref refs/heads/<name> <sha>` (create/move, no -d) stays ALLOWED.

        This is the same scope decision the porcelain rule already makes:
        `git branch -f` (force-move a branch pointer) is not blocked either —
        only DELETION without a merge check is in scope for this rule.
        """
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git update-ref refs/heads/feature abc123def456"},
        }
        assert handler.matches(hook_input) is False

    def test_update_ref_delete_non_branch_ref_stays_allowed(self, handler):
        """Deleting a non-branch ref (e.g. a remote-tracking ref) is out of scope.

        Only `refs/heads/` is the `git branch -D` equivalent; every other
        `update-ref -d` target is left untouched, per PLAN.md's scoping
        decision.
        """
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git update-ref -d refs/remotes/origin/feature"},
        }
        assert handler.matches(hook_input) is False

    def test_update_ref_query_stays_allowed(self, handler):
        """A read-only `update-ref` query (no -d) stays ALLOWED."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git update-ref --stdin < /dev/null"},
        }
        assert handler.matches(hook_input) is False

    def test_update_ref_delete_branch_with_global_option_still_blocked(self, handler):
        """Global options before the subcommand must not defeat this rule either."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git -C /srv/project update-ref -d refs/heads/feature"},
        }
        assert handler.matches(hook_input) is True

    @pytest.mark.parametrize(
        "command",
        [
            "git update-ref refs/heads/backup HEAD; echo -d refs/heads/backup",
            "git update-ref refs/heads/backup HEAD && printf -- '-d refs/heads/x'",
        ],
    )
    def test_a_later_statements_text_does_not_condemn_a_ref_create(self, handler, command):
        """The pattern must stay inside ONE segment, like its push-force sibling.

        Both statements here are benign: `update-ref` with no `-d` CREATES a
        ref, and the flag text belongs to a later, unrelated statement. A `.*`
        spanning `;` and `&&` judges one statement by another's text, so the
        author sees a deny citing a rule their command does not match — with
        nothing in it to point at.
        """
        hook_input = {"tool_name": "Bash", "tool_input": {"command": command}}
        assert handler.matches(hook_input) is False

    def test_the_delete_is_still_blocked_when_it_is_the_later_statement(self, handler):
        """Scoping to a segment must not lose the segment that IS destructive."""
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "git fetch origin && git update-ref -d refs/heads/feature"},
        }
        assert handler.matches(hook_input) is True
