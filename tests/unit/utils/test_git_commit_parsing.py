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
    commits_working_tree,
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


class TestCommitsWorkingTree:
    """Does this ``git commit`` record the WORKING TREE rather than the index?

    Promoted here from ``sensitive_content`` (Plan 00412 class 2a) because a
    second caller now needs it, and this module's own docstring records what
    copying such a helper cost the last time: an identical bug in two gates at
    once. A third copy of short-flag cluster parsing is that bug's next
    instalment.

    Load-bearing rather than cosmetic for the caller that prompted the move. A
    guard-config commit gate that reads only the INDEX sees nothing when the
    config is edited and committed with ``-a`` -- which is precisely the route
    class 2 is about.

    Takes the options AFTER the subcommand, not the whole command: callers
    locate ``commit`` with the rigorous ``git_subcommand_index`` (which handles
    ``git -C path commit``), and taking the full token list here would tempt a
    caller into a weaker locator.
    """

    def test_bare_commit_records_the_index(self) -> None:
        assert commits_working_tree(["-m", "msg"]) is False

    def test_short_all_flag(self) -> None:
        assert commits_working_tree(["-a", "-m", "msg"]) is True

    def test_long_all_flag(self) -> None:
        assert commits_working_tree(["--all", "-m", "msg"]) is True

    def test_cluster_carrying_all_before_the_value_letter(self) -> None:
        assert commits_working_tree(["-am", "msg"]) is True

    def test_a_inside_an_attached_value_is_not_the_all_flag(self) -> None:
        """`-ma` is a message whose attached value is "a" -- no ``-a`` flag.

        The cluster ends at the first value-taking letter; reading straight
        through the token instead mines the MESSAGE for flags.
        """
        assert commits_working_tree(["-ma", "path.md"]) is False

    def test_the_letter_a_in_a_quoted_message_is_not_a_flag(self) -> None:
        """The defect this parsing exists to prevent, at the helper level.

        ``git commit -m 'fix the -a flag handling'`` must not be read as
        committing the working tree: doing so diffed the whole dirty tree and
        let an UNSTAGED file deny a commit that never included it.
        """
        assert commits_working_tree(["-m", "fix the -a flag handling"]) is False

    def test_all_after_the_end_of_options_separator_is_a_pathspec(self) -> None:
        """After ``--`` every token is an operand, including one spelled `-a`."""
        assert commits_working_tree(["-m", "msg", "--", "-a"]) is False

    def test_a_long_flags_value_is_not_scanned_for_flags(self) -> None:
        assert commits_working_tree(["--author", "-a", "-m", "msg"]) is False

    def test_a_trailer_value_is_not_scanned_for_flags(self) -> None:
        """``--trailer`` and ``--pathspec-from-file`` take separate values too.

        Both were in the handler's long-flag set and absent from the one this
        function first used -- so a trailer value beginning with a dash was
        walked as options and its leading ``a`` read as ``--all``.
        """
        assert commits_working_tree(["--trailer", "-ack: someone", "-m", "msg"]) is False

    def test_a_pathspec_from_file_value_is_not_scanned_for_flags(self) -> None:
        assert commits_working_tree(["--pathspec-from-file", "-argh.txt"]) is False

    def test_untracked_files_flag_does_not_swallow_a_following_all(self) -> None:
        """``-u`` takes an OPTIONAL value, so ``-a`` after it is a real flag.

        ``VALUE_FLAGS`` lists ``-u`` because the pathspec reader must not file
        its value as a path, but that set does not distinguish required from
        optional values. Reusing it here consumed the next token and lost an
        ``-a`` -- a commit recording the working tree read as recording the
        index, which is the wrong direction for a guard.
        """
        assert commits_working_tree(["-u", "-a", "-m", "msg"]) is True

    def test_no_options_at_all(self) -> None:
        assert commits_working_tree([]) is False

    def test_template_flags_attached_value_is_not_the_all_flag(self) -> None:
        """`-ta` is ``--template a``, not ``-t -a``.

        ``-t`` takes a REQUIRED value, so the ``a`` after it is the template
        path. This is the divergence that made the promotion worth doing
        carefully: the shared module's value-letter set did not carry ``t``,
        so a straight lift would have read an ``-a`` flag here that the
        handler's own copy correctly did not.
        """
        assert commits_working_tree(["-ta", "path.md"]) is False

    def test_template_flag_consumes_its_separate_value(self) -> None:
        assert commits_working_tree(["-t", "-a", "-m", "msg"]) is False

    def test_gpg_sign_does_not_consume_the_following_token(self) -> None:
        """``-S`` takes an OPTIONAL value, so the next token is NOT its value.

        Treating it like a required-value flag would swallow the following
        token -- and if that token were ``-a``, the commit would be read as
        recording the index when it records the working tree.
        """
        assert commits_working_tree(["-S", "-a", "-m", "msg"]) is True

    def test_gpg_sign_with_an_attached_key_still_ends_the_cluster(self) -> None:
        """The key id deliberately CONTAINS an ``a``.

        A key id without one passes whether or not the cluster is terminated
        correctly, so it proves nothing -- the first version of this test used
        ``keyid`` and was green against an implementation that scans the whole
        token.
        """
        assert commits_working_tree(["-Skeya", "-m", "msg"]) is False
