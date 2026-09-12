"""Tests for the shared merge/pull/rebase scope helper (Plan 00389 Task 1.1).

Extracted verbatim from ``merge_qa_report`` so a second handler can match the
same operations and attribute against the same ``ORIG_HEAD..HEAD`` diff. The
security-relevant half is the segmentation: a command-evasion pattern that
exists in two copies is one that eventually diverges, and the copy that stops
matching is the one nobody notices.
"""

from pathlib import Path
from unittest.mock import patch

from claude_code_hooks_daemon.utils.merge_scope import (
    changed_path_is_or_is_under,
    changed_paths,
    is_git_merge_pull_rebase_command,
)

_RUN_GIT_TARGET = "claude_code_hooks_daemon.utils.merge_scope.run_git"


class _Result:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


class TestIsGitMergePullRebaseCommand:
    def test_plain_merge_pull_and_rebase_match(self) -> None:
        assert is_git_merge_pull_rebase_command("git merge feature") is True
        assert is_git_merge_pull_rebase_command("git pull") is True
        assert is_git_merge_pull_rebase_command("git rebase main") is True

    def test_unrelated_git_command_does_not_match(self) -> None:
        assert is_git_merge_pull_rebase_command("git commit -m 'x'") is False
        assert is_git_merge_pull_rebase_command("git status") is False

    def test_a_word_merely_containing_the_verb_does_not_match(self) -> None:
        """`git pullimaginary` is not `git pull` -- the trailing boundary matters."""
        assert is_git_merge_pull_rebase_command("git pullimaginary") is False

    def test_global_option_prefix_still_matches(self) -> None:
        """`git -C <path> pull` is the same operation from another directory."""
        assert is_git_merge_pull_rebase_command("git -C /some/repo pull") is True

    def test_env_prefix_still_matches(self) -> None:
        assert is_git_merge_pull_rebase_command("GIT_EDITOR=true git merge x") is True

    def test_matches_in_a_later_segment(self) -> None:
        """The operation need not be the first command in the line."""
        assert is_git_merge_pull_rebase_command("git fetch && git merge origin/main") is True

    def test_line_continuation_is_normalised_before_segmenting(self) -> None:
        assert is_git_merge_pull_rebase_command("git fetch && \\\n  git pull") is True


class TestChangedPaths:
    def test_returns_the_diffed_paths(self, tmp_path: Path) -> None:
        with patch(_RUN_GIT_TARGET, return_value=_Result(0, "a.py\nb/c.md\n")):
            assert changed_paths(tmp_path) == frozenset({"a.py", "b/c.md"})

    def test_non_zero_exit_is_empty_not_an_error(self, tmp_path: Path) -> None:
        """ORIG_HEAD absent, or git failing, must read as 'nothing to attribute'."""
        with patch(_RUN_GIT_TARGET, return_value=_Result(128, "")):
            assert changed_paths(tmp_path) == frozenset()

    def test_blank_lines_are_dropped(self, tmp_path: Path) -> None:
        with patch(_RUN_GIT_TARGET, return_value=_Result(0, "a.py\n\n  \n")):
            assert changed_paths(tmp_path) == frozenset({"a.py"})


class TestChangedPathIsOrIsUnder:
    def test_exact_match(self) -> None:
        assert changed_path_is_or_is_under(".claude/hooks-daemon.yaml", frozenset({".claude/hooks-daemon.yaml"}))

    def test_nested_under_a_directory(self) -> None:
        assert changed_path_is_or_is_under(
            ".claude/project-handlers", frozenset({".claude/project-handlers/pre_tool_use/x.py"})
        )

    def test_trailing_slash_on_the_candidate_is_tolerated(self) -> None:
        assert changed_path_is_or_is_under(
            ".claude/project-handlers/", frozenset({".claude/project-handlers/x.py"})
        )

    def test_a_sibling_with_a_shared_prefix_does_not_match(self) -> None:
        """`.claude/project-handlers-old/x.py` is not under `.claude/project-handlers`."""
        assert not changed_path_is_or_is_under(
            ".claude/project-handlers", frozenset({".claude/project-handlers-old/x.py"})
        )

    def test_no_changed_paths_is_false(self) -> None:
        assert not changed_path_is_or_is_under(".claude/hooks-daemon.yaml", frozenset())
