"""Tests for the shared ``git commit`` command-line tokenising helpers.

Extracted from ``docs_qa_commit_gate`` and ``plan_qa_commit_gate``, which had
copied the identical ~60-line helper table (Plan 00293, release-review
finding): the duplication is how a combined short-flag cluster like ``-am``
went unrecognised as message-taking in BOTH gates at once. ``-am`` falls into
the boolean-flag branch, so the commit MESSAGE is misread as a pathspec — a
``git commit -am "wip docs"`` then diffs against a nonexistent path,
``staged_documents``/the plan-QA staged context comes back empty, and every
STAGED check silently passes on a commit it never actually examined.
"""

from __future__ import annotations

from claude_code_hooks_daemon.utils.git_commit_parsing import (
    extract_commit_message,
    extract_commit_pathspecs,
    is_git_commit,
    tokenise_command,
)


class TestTokeniseCommand:
    def test_unparseable_command_returns_empty_list(self) -> None:
        assert tokenise_command("git commit -m 'unterminated") == []

    def test_simple_command_splits_on_whitespace(self) -> None:
        assert tokenise_command("git commit -m hello") == ["git", "commit", "-m", "hello"]


class TestIsGitCommit:
    def test_true_when_commit_follows_git(self) -> None:
        assert is_git_commit(["git", "commit", "-m", "x"]) is True

    def test_false_for_unrelated_command(self) -> None:
        assert is_git_commit(["git", "status"]) is False


class TestExtractCommitMessage:
    def test_dash_m_separate_token(self) -> None:
        assert extract_commit_message(["git", "commit", "-m", "hello"]) == "hello"

    def test_equals_form(self) -> None:
        assert extract_commit_message(["git", "commit", "--message=hello"]) == "hello"

    def test_multiple_dash_m_joined(self) -> None:
        tokens = ["git", "commit", "-m", "title", "-m", "body"]
        assert extract_commit_message(tokens) == "title\n\nbody"

    def test_absent_returns_none(self) -> None:
        assert extract_commit_message(["git", "commit"]) is None

    def test_dash_a_dash_m_separate_flags_unchanged(self) -> None:
        tokens = ["git", "commit", "-a", "-m", "wip"]
        assert extract_commit_message(tokens) == "wip"

    def test_dash_m_path_unchanged(self) -> None:
        tokens = ["git", "commit", "-m", "x", "path.md"]
        assert extract_commit_message(tokens) == "x"

    def test_combined_short_flag_cluster_dash_a_m_consumes_next_token(self) -> None:
        """The bug: `-am "wip"` must read the message, not swallow it as a path."""
        tokens = ["git", "commit", "-am", "wip"]
        assert extract_commit_message(tokens) == "wip"

    def test_cluster_dash_m_a_is_attached_form_not_next_token(self) -> None:
        """`-ma` means message "a" (git's attached-value semantics), and must
        NOT consume the following token the way `-am` does."""
        tokens = ["git", "commit", "-ma", "path.md"]
        assert extract_commit_message(tokens) == "a"

    def test_attached_message_form_dash_m_msg(self) -> None:
        tokens = ["git", "commit", "-mmsg", "path.md"]
        assert extract_commit_message(tokens) == "msg"


class TestExtractCommitPathspecs:
    def test_no_commit_token_returns_empty(self) -> None:
        assert extract_commit_pathspecs(["git", "status"]) == []

    def test_skips_value_flags(self) -> None:
        tokens = ["git", "commit", "-m", "msg", "CLAUDE/A.md"]
        assert extract_commit_pathspecs(tokens) == ["CLAUDE/A.md"]

    def test_after_separator(self) -> None:
        tokens = ["git", "commit", "--", "CLAUDE/A.md"]
        assert extract_commit_pathspecs(tokens) == ["CLAUDE/A.md"]

    def test_boolean_flag_skipped(self) -> None:
        tokens = ["git", "commit", "--amend", "CLAUDE/A.md"]
        assert extract_commit_pathspecs(tokens) == ["CLAUDE/A.md"]

    def test_dash_a_dash_m_separate_flags_unchanged(self) -> None:
        tokens = ["git", "commit", "-a", "-m", "wip"]
        assert extract_commit_pathspecs(tokens) == []

    def test_combined_short_flag_cluster_dash_am_yields_no_pathspecs(self) -> None:
        """The bug: `-am "wip"` must not read the message as a pathspec."""
        tokens = ["git", "commit", "-am", "wip"]
        assert extract_commit_pathspecs(tokens) == []

    def test_combined_cluster_dash_am_with_trailing_path(self) -> None:
        tokens = ["git", "commit", "-am", "wip", "CLAUDE/A.md"]
        assert extract_commit_pathspecs(tokens) == ["CLAUDE/A.md"]

    def test_cluster_dash_ma_attached_form_only_consumes_own_token(self) -> None:
        """`-ma` carries its value attached ("a"), so the FOLLOWING token is a
        real pathspec, unlike `-am` which consumes it as the message."""
        tokens = ["git", "commit", "-ma", "path.md"]
        assert extract_commit_pathspecs(tokens) == ["path.md"]
