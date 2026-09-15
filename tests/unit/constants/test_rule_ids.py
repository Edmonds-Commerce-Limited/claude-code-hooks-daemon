"""Tests for constants/rule_ids.py — RuleID constants.

Phase 2 of Plan 00116: Rule ID named constants (NO MAGIC strings).

Design contract (Decision D from PLAN.md):
  - Rule IDs are a PUBLIC CONTRACT (appear in user CLAUDE.md + block messages)
  - Named constants in constants/rule_ids.py
  - IDs for destructive_git: 9 IDs matching 9 block reasons
"""

from __future__ import annotations

from claude_code_hooks_daemon.constants.rule_ids import RuleID


class TestRuleIDConstants:
    """RuleID provides named constants for all rule identifiers."""

    def test_ruleid_importable(self) -> None:
        """RuleID can be imported from constants.rule_ids."""
        assert RuleID is not None

    def test_ruleid_is_class(self) -> None:
        """RuleID is a class (not a module-level dict or enum)."""
        assert isinstance(RuleID, type)

    # --- destructive_git: 9 rules (Decision B: per-rule granularity) ---

    def test_git_reset_hard_constant_exists(self) -> None:
        """RuleID has a constant for git reset --hard."""
        assert hasattr(RuleID, "GIT_RESET_HARD")

    def test_git_reset_hard_is_string(self) -> None:
        """RuleID.GIT_RESET_HARD is a non-empty string."""
        assert isinstance(RuleID.GIT_RESET_HARD, str)
        assert len(RuleID.GIT_RESET_HARD) > 0

    def test_git_clean_constant_exists(self) -> None:
        """RuleID has a constant for git clean -f."""
        assert hasattr(RuleID, "GIT_CLEAN_FORCE")

    def test_git_clean_is_string(self) -> None:
        """RuleID.GIT_CLEAN_FORCE is a non-empty string."""
        assert isinstance(RuleID.GIT_CLEAN_FORCE, str)
        assert len(RuleID.GIT_CLEAN_FORCE) > 0

    def test_git_checkout_discard_constant_exists(self) -> None:
        """RuleID has a constant for git checkout -- <file>."""
        assert hasattr(RuleID, "GIT_CHECKOUT_DISCARD")

    def test_git_restore_constant_exists(self) -> None:
        """RuleID has a constant for git restore <file>."""
        assert hasattr(RuleID, "GIT_RESTORE")

    def test_git_stash_drop_constant_exists(self) -> None:
        """RuleID has a constant for git stash drop."""
        assert hasattr(RuleID, "GIT_STASH_DROP")

    def test_git_stash_clear_constant_exists(self) -> None:
        """RuleID has a constant for git stash clear."""
        assert hasattr(RuleID, "GIT_STASH_CLEAR")

    def test_git_push_force_constant_exists(self) -> None:
        """RuleID has a constant for git push --force."""
        assert hasattr(RuleID, "GIT_PUSH_FORCE")

    def test_git_branch_force_delete_constant_exists(self) -> None:
        """RuleID has a constant for git branch -D."""
        assert hasattr(RuleID, "GIT_BRANCH_FORCE_DELETE")

    def test_git_commit_amend_constant_exists(self) -> None:
        """RuleID has a constant for git commit --amend."""
        assert hasattr(RuleID, "GIT_COMMIT_AMEND")

    def test_nine_destructive_git_constants(self) -> None:
        """There are exactly 9 destructive_git rule IDs (Decision B)."""
        git_constants = [
            RuleID.GIT_RESET_HARD,
            RuleID.GIT_CLEAN_FORCE,
            RuleID.GIT_CHECKOUT_DISCARD,
            RuleID.GIT_RESTORE,
            RuleID.GIT_STASH_DROP,
            RuleID.GIT_STASH_CLEAR,
            RuleID.GIT_PUSH_FORCE,
            RuleID.GIT_BRANCH_FORCE_DELETE,
            RuleID.GIT_COMMIT_AMEND,
        ]
        assert len(git_constants) == 9

    # --- No duplicate IDs ---

    def test_all_ids_unique(self) -> None:
        """All RuleID constant values are unique (no two constants share an ID)."""
        all_ids = [
            value
            for name, value in vars(RuleID).items()
            if not name.startswith("_") and isinstance(value, str)
        ]
        assert len(all_ids) == len(
            set(all_ids)
        ), f"Duplicate RuleID values found: {sorted(all_ids)}"

    def test_all_ids_are_strings(self) -> None:
        """All RuleID constants are strings."""
        for name, value in vars(RuleID).items():
            if name.startswith("_"):
                continue
            if callable(value):
                continue
            assert isinstance(value, str), f"RuleID.{name} is not a string: {type(value)}"

    def test_ids_follow_naming_convention(self) -> None:
        """All RuleID values follow an uppercase-with-hyphens convention.

        IDs appear in user-facing CLAUDE.md and block messages, so they must
        be stable and readable (e.g. 'R-GIT-RESET-HARD', not 'rule_123').
        """
        for name, value in vars(RuleID).items():
            if name.startswith("_"):
                continue
            if callable(value):
                continue
            if not isinstance(value, str):
                continue
            # IDs should be non-empty and contain only uppercase letters, digits, hyphens
            assert len(value) > 0, f"RuleID.{name} is empty"
            assert all(
                c.isupper() or c.isdigit() or c == "-" for c in value
            ), f"RuleID.{name} value {value!r} contains unexpected characters"

    def test_ids_start_with_prefix(self) -> None:
        """All RuleID values start with 'R-' prefix for clarity in block messages."""
        for name, value in vars(RuleID).items():
            if name.startswith("_"):
                continue
            if callable(value):
                continue
            if not isinstance(value, str):
                continue
            assert value.startswith("R-"), f"RuleID.{name} value {value!r} does not start with 'R-'"

    # --- sed_blocker ---

    def test_sed_file_modification_constant_exists(self) -> None:
        """RuleID has a constant for sed -i (file modification)."""
        assert hasattr(RuleID, "SED_FILE_MODIFICATION")

    def test_sed_file_modification_is_string(self) -> None:
        """RuleID.SED_FILE_MODIFICATION is a non-empty string."""
        assert isinstance(RuleID.SED_FILE_MODIFICATION, str)
        assert len(RuleID.SED_FILE_MODIFICATION) > 0

    # --- pipe_blocker ---

    def test_pipe_to_tail_constant_exists(self) -> None:
        """RuleID has a constant for piping to tail."""
        assert hasattr(RuleID, "PIPE_TO_TAIL")

    def test_pipe_to_head_constant_exists(self) -> None:
        """RuleID has a constant for piping to head."""
        assert hasattr(RuleID, "PIPE_TO_HEAD")

    # --- dangerous_permissions ---

    def test_chmod_world_writable_constant_exists(self) -> None:
        """RuleID has a constant for chmod 777."""
        assert hasattr(RuleID, "CHMOD_WORLD_WRITABLE")

    # --- curl_pipe_shell ---

    def test_curl_pipe_shell_constant_exists(self) -> None:
        """RuleID has a constant for curl | bash."""
        assert hasattr(RuleID, "CURL_PIPE_SHELL")

    # --- git_stash (the handler, not the drop/clear rules) ---

    def test_git_stash_push_constant_exists(self) -> None:
        """RuleID has a constant for git stash push (the stash handler rule)."""
        assert hasattr(RuleID, "GIT_STASH_PUSH")
