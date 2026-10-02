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

import pytest

from claude_code_hooks_daemon.utils.git_commit_parsing import (
    CommitForm,
    commits_working_tree,
    extract_commit_form,
    extract_commit_message,
    extract_commit_pathspecs,
    git_invocations,
    is_git_commit,
    read_commit_form,
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
        assert extract_commit_pathspecs("git status") == []

    def test_skips_value_flags(self) -> None:
        assert extract_commit_pathspecs("git commit -m msg CLAUDE/A.md") == ["CLAUDE/A.md"]

    def test_after_separator(self) -> None:
        assert extract_commit_pathspecs("git commit -- CLAUDE/A.md") == ["CLAUDE/A.md"]

    def test_boolean_flag_skipped(self) -> None:
        assert extract_commit_pathspecs("git commit --amend CLAUDE/A.md") == ["CLAUDE/A.md"]

    def test_dash_a_dash_m_separate_flags_unchanged(self) -> None:
        assert extract_commit_pathspecs("git commit -a -m wip") == []

    def test_combined_short_flag_cluster_dash_am_yields_no_pathspecs(self) -> None:
        """The bug: `-am "wip"` must not read the message as a pathspec."""
        assert extract_commit_pathspecs('git commit -am "wip"') == []

    def test_combined_cluster_dash_am_with_trailing_path(self) -> None:
        assert extract_commit_pathspecs("git commit -am wip CLAUDE/A.md") == ["CLAUDE/A.md"]

    def test_cluster_dash_ma_attached_form_only_consumes_own_token(self) -> None:
        """`-ma` carries its value attached ("a"), so the FOLLOWING token is a
        real pathspec, unlike `-am` which consumes it as the message."""
        assert extract_commit_pathspecs("git commit -ma path.md") == ["path.md"]


class TestNoShellSyntaxIsAPathspec:
    """Ledger 00466 N226: a redirection, a heredoc, ``&`` or an option's value
    read as a pathspec made every commit gate judge a path that matches
    nothing, and so judge nothing at all."""

    @pytest.mark.parametrize(
        "command",
        [
            "git commit -m x 2>&1",
            "git commit -m x 2>&1 | bin/echd-capture 20",
            "git commit -m x > /dev/null",
            "git commit -m x>/dev/null",
            "git commit -m x &>log.txt",
            "git commit -m x 2> err.txt",
            "git commit -m x {fd}>log",
            'git commit -m x <<<"body"',
            "git commit -F- <<'EOF'\nbody line\nEOF",
            'git commit -F - <<"EOF"\nIt\'s a body\nEOF',
            "git commit -F- <<-EOF\n\tbody\n\tEOF",
            "git commit -m x &",
            "git commit -m x; git status",
            "git commit -m x && git log",
            "git commit -m x\ngit status",
            "(git commit -m x)",
            "git commit -t tmpl -m x",
            "git commit --template tmpl -m x",
            "git commit --cleanup strip -m x",
            "git commit --trailer 'Co-authored-by: A <a@b>' -m x",
            "git commit --author 'A <a@b>' -m x",
            "git commit --auth 'A <a@b>' -m x",
            "git commit --date now -m x",
            "git commit -C HEAD",
            "git commit -c HEAD",
            "git commit --fixup HEAD",
            "git commit --squash HEAD",
            "git commit --reuse-message HEAD",
            "git commit -S -m x",
            "git commit -Skey -m x",
            "git commit --gpg-sign=key -m x",
        ],
    )
    def test_is_not_read_as_a_pathspec(self, command: str) -> None:
        assert extract_commit_pathspecs(command) == []

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("git commit -m x a.md 2>&1", ["a.md"]),
            ("git commit -m x a.md > out.log", ["a.md"]),
            ("git commit -u a.md -m x", ["a.md"]),
            ("git commit -au -m x a.md", ["a.md"]),
            ("git commit -t tmpl a.md", ["a.md"]),
            ("git commit -F- a.md <<'EOF'\nbody\nEOF", ["a.md"]),
            ("git commit --no-edit a.md", ["a.md"]),
            ("git commit -m x -- -odd.md", ["-odd.md"]),
            ("git commit -m 'a;b' a.md; git status", ["a.md"]),
        ],
    )
    def test_a_real_pathspec_is_kept(self, command: str, expected: list[str]) -> None:
        assert extract_commit_pathspecs(command) == expected

    def test_an_ambiguous_abbreviation_consumes_nothing(self) -> None:
        """``--re`` is reedit-message, reuse-message or reset-author: git refuses it."""
        assert extract_commit_pathspecs("git commit --re a.md") == ["a.md"]


class TestGitInvocations:
    """The shared walker: every ``git`` a command runs, and where."""

    @pytest.mark.parametrize(
        "command",
        [
            "git commit -m x",
            "sudo git commit -m x",
            "command git commit -m x",
            "exec git commit -m x",
            "nice -n 5 git commit -m x",
            "xargs git commit -m x",
            "env -i git commit -m x",
            "env -u X git commit -m x",
            "eval 'git commit -m x'",
            "eval git commit -m x",
            "sh -c 'git commit -m x'",
            "bash -lc 'git commit -m x'",
            "(git commit -m x)",
            "{ git commit -m x; }",
            "/usr/bin/git commit -m x",
            "if true; then git commit -m x; fi",
        ],
    )
    def test_finds_the_commit(self, command: str) -> None:
        assert [run.subcommand for run in git_invocations(command)] == ["commit"]

    def test_echo_mentioning_a_commit_runs_none(self) -> None:
        assert git_invocations("echo 'git commit -m x'") == []

    @pytest.mark.parametrize(
        ("command", "directory"),
        [
            ("cd sub && git commit -m x", ("sub",)),
            ("cd -P sub && git commit -m x", ("sub",)),
            ("cd -- sub && git commit -m x", ("sub",)),
            ("cd && git commit -m x", ("~",)),
            ("cd - && git commit -m x", (None,)),
            ("cd a b && git commit -m x", (None,)),
            ("popd && git commit -m x", (None,)),
            ('cd "$WT" && git commit -m x', ("$WT",)),
            ("(cd sub && git commit -m x)", ("sub",)),
            ("(cd sub); git commit -m x", ()),
            ("sh -c 'cd sub && git commit -m x'", ("sub",)),
            ("cd a; cd b; git commit -m x", ("a", "b")),
        ],
    )
    def test_records_the_directory(self, command: str, directory: tuple[str | None, ...]) -> None:
        (run,) = git_invocations(command)
        assert run.directory == directory

    def test_records_global_options_and_assignments(self) -> None:
        (run,) = git_invocations("GIT_INDEX_FILE=i git -C wt --no-pager commit -m x 2>&1")
        assert run.global_options == ("-C", "wt", "--no-pager")
        assert run.assignments == ("GIT_INDEX_FILE=i",)
        assert run.arguments == ("-m", "x")


class TestCommitForm:
    """Ledger 00474 N245: which tree a commit records is decided by its form."""

    @pytest.mark.parametrize(
        ("command", "pathspecs", "include"),
        [
            ("git commit -m x", (), False),
            ("git commit -m x a.py b.py", ("a.py", "b.py"), False),
            ("git commit -m x --only a.py", ("a.py",), False),
            ("git commit -m x -i a.py", ("a.py",), True),
            ("git commit -m x --include a.py", ("a.py",), True),
            ("git commit --inc -m x a.py", ("a.py",), True),
            ("git commit -im x a.py", ("a.py",), True),
            ("git commit -m x -- a.py", ("a.py",), False),
            ("git commit -m x -i -- a.py", ("a.py",), True),
            ("git -C /r commit -m x -i a.py", ("a.py",), True),
        ],
    )
    def test_reads_pathspecs_and_include(
        self, command: str, pathspecs: tuple[str, ...], include: bool
    ) -> None:
        form = extract_commit_form(command)

        assert form.pathspecs == pathspecs
        assert form.include is include
        assert form.pathspec_from_file is False

    @pytest.mark.parametrize(
        "command",
        [
            "git commit -m 'about the -i flag'",
            "git commit -m 'about --include' a.py",
            "git commit --message=--include a.py",
            "git commit -m x -- -i",
            "git commit -mi a.py",
        ],
    )
    def test_an_include_flag_inside_a_value_or_after_the_separator_is_not_one(
        self, command: str
    ) -> None:
        assert extract_commit_form(command).include is False

    @pytest.mark.parametrize(
        "command",
        [
            "git commit -m x --pathspec-from-file=list.txt",
            "git commit -m x --pathspec-from-file list.txt",
        ],
    )
    def test_a_pathspec_file_is_flagged_since_its_paths_cannot_be_read(self, command: str) -> None:
        form = extract_commit_form(command)

        assert form.pathspec_from_file is True
        assert form.pathspecs == ()

    def test_no_commit_in_the_command_is_the_bare_form(self) -> None:
        assert extract_commit_form("git status") == CommitForm()


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


class TestReadCommitFormCertainty:
    """A pathspec view may be trusted only for the plain shape a careless agent types."""

    @pytest.mark.parametrize(
        "command",
        [
            "git commit -m x a.txt",
            "git commit -m x a.txt b.txt && git push",
            "git commit -m x -- a.txt",
            "git commit -m x",
        ],
    )
    def test_one_plain_commit_is_certain(self, command: str) -> None:
        assert read_commit_form(command).certain is True

    @pytest.mark.parametrize(
        "command",
        [
            "cd sub && git commit -m x a.txt",
            "pushd sub && git commit -m x a.txt",
            "(cd sub; git commit -m x a.txt)",
            "git -C sub commit -m x a.txt",
            "git --git-dir=other/.git commit -m x a.txt",
            "git --work-tree other commit -m x a.txt",
            "GIT_DIR=other/.git git commit -m x a.txt",
            "git commit -m x a.txt && git commit -m y",
            "git commit -m x a.txt $F",
            "git commit -m x a.txt $(echo b.txt)",
            "git commit -m x a.txt `echo b.txt`",
            "git commit -m x {a,b}.txt",
            "git commit -m x ~/a.txt",
        ],
    )
    def test_any_other_shape_is_not_certain(self, command: str) -> None:
        assert read_commit_form(command).certain is False

    def test_a_subshell_cd_that_has_ended_does_not_move_a_later_commit(self) -> None:
        assert read_commit_form("(cd sub; ls); git commit -m x a.txt").certain is True

    def test_the_form_is_the_first_commits(self) -> None:
        assert read_commit_form("git commit -m x --include a.txt").form.include is True
