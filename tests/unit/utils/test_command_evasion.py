"""Shared regex fragments must survive the evasion vectors that defeated handlers.

These fragments exist because three separate blocking handlers were each
bypassable by a caller who spelled the same command differently:

* ``destructive_git`` and ``git_stash`` anchored on ``git <subcommand>``, so
  ``git -C /path <subcommand>`` sailed through.
* ``sudo_pip`` anchored on ``sudo pip``, so ``sudo -H pip`` sailed through.
* ``curl_pipe_shell`` anchored on the interpreter NAME, so ``| /bin/bash``
  sailed through.

Every one of those is the same defect: a bare-name anchor. Encoding the three
spellings once means a new handler composes the hardening instead of
rediscovering it — and these tests are what stop the fragments regressing.
"""

from __future__ import annotations

import re

import pytest

from claude_code_hooks_daemon.utils.command_evasion import (
    GIT_INVOCATION,
    OPTIONAL_PATH,
    OPTIONAL_SUDO,
    SUBCOMMAND_SEPARATOR_CHARS,
    git_subcommand_index,
    normalise_line_continuations,
)


class TestNormaliseLineContinuations:
    r"""A shell line continuation is whitespace, and must be treated as such.

    ``git \<newline> reset --hard`` bypassed destructive_git even BEFORE global
    options were considered: ``\s+`` does not match the backslash, so the
    subcommand never followed ``git``. This is not an adversarial trick — it is
    how anyone writes a long command across lines, so a well-intentioned agent
    reaches it by accident.

    Normalising once here beats teaching every pattern about it: the shell
    already defines the sequence as whitespace, so the patterns should never
    have to see it.
    """

    def test_collapses_backslash_newline(self) -> None:
        assert "git" in normalise_line_continuations("git \\\n  status")
        assert "\\" not in normalise_line_continuations("git \\\n  status")

    def test_collapses_windows_line_ending(self) -> None:
        assert "\\" not in normalise_line_continuations("git \\\r\n  status")

    def test_collapses_repeated_continuations(self) -> None:
        result = normalise_line_continuations("git \\\n  -C /srv \\\n  status")

        assert "\\" not in result

    def test_leaves_ordinary_commands_untouched(self) -> None:
        command = "git status --porcelain"

        assert normalise_line_continuations(command) == command

    def test_preserves_a_backslash_that_is_not_a_continuation(self) -> None:
        """Only backslash-NEWLINE is a continuation; a lone backslash is data."""
        command = r"grep 'a\bc' file.txt"

        assert normalise_line_continuations(command) == command

    def test_normalised_command_is_matchable(self) -> None:
        """The point of the exercise: patterns match after normalisation."""
        raw = "git \\\n  -C /srv/project \\\n  reset --hard HEAD"

        normalised = normalise_line_continuations(raw)

        assert re.search(GIT_INVOCATION + r"reset\b", normalised) is not None


class TestAContinuationJoinsRatherThanSeparates:
    r"""bash REMOVES a backslash-newline; it does not turn it into a space.

    Confirmed against bash itself rather than from memory::

        ec\<newline>ho joined   -> prints "joined"   (the token is `echo`)
        echo a\<newline>b       -> prints "ab"

    Substituting a space SPLITS a token the shell JOINS, which is the
    fail-open direction: `git pu\<newline>sh --force` is a real force push,
    and every guard reading through ``get_bash_command`` saw the harmless
    `git pu sh --force` instead.

    The surrounding class's framing -- "a shell line continuation is
    whitespace" -- is where this came from, and it is only true between
    tokens. Inside one it is the opposite of whitespace: it is glue. Every
    existing case in that class writes a space BEFORE the backslash, so the
    two behaviours were indistinguishable there and the wrong one was
    chosen.
    """

    def test_a_mid_token_continuation_joins_the_halves(self) -> None:
        assert normalise_line_continuations("git pu\\\nsh --force") == "git push --force"

    def test_a_continuation_with_no_space_either_side_joins(self) -> None:
        assert normalise_line_continuations("echo a\\\nb") == "echo ab"

    def test_a_split_git_binary_name_joins(self) -> None:
        assert normalise_line_continuations("gi\\\nt push --force") == "git push --force"

    def test_whitespace_already_present_is_preserved_not_doubled(self) -> None:
        """The between-tokens case every existing test covers, stated exactly.

        Removal is correct here too because the author already wrote the
        separating space before the backslash.
        """
        assert normalise_line_continuations("git \\\nreset --hard") == "git reset --hard"

    def test_a_join_that_produces_no_real_command_is_left_unmatched(self) -> None:
        r"""``git\<newline>push`` is ``gitpush`` to bash, and must not read as git.

        The space substitution made this LOOK like a force push. Nothing runs
        here, so denying it would be a false positive -- the fix has to lose
        that match, not keep it.
        """
        assert normalise_line_continuations("git\\\npush --force") == "gitpush --force"


# A path with no "git" substring anywhere: a path ending in ".git" lets a
# `\bgit` anchor match inside the PATH and mask a broken fragment.
_SAFE_PATH = "/srv/project"


class TestGitInvocation:
    """`git` plus any run of global options, positioned at the subcommand."""

    @pytest.mark.parametrize(
        "command",
        [
            "git reset",
            f"git -C {_SAFE_PATH} reset",
            "git -c core.pager=cat reset",
            f"git --git-dir={_SAFE_PATH}/.repo reset",
            f"git --work-tree={_SAFE_PATH} reset",
            "git --no-pager reset",
            f"git --no-pager -C {_SAFE_PATH} -c a.b=c reset",
        ],
    )
    def test_reaches_the_subcommand(self, command: str) -> None:
        assert re.search(GIT_INVOCATION + r"reset\b", command) is not None

    def test_unknown_option_is_still_tolerated(self) -> None:
        """Fail CLOSED: an option we have never heard of must not mean 'allow'."""
        assert re.search(GIT_INVOCATION + r"reset\b", "git --future-flag=x reset") is not None

    @pytest.mark.parametrize("separator", list(SUBCOMMAND_SEPARATOR_CHARS))
    def test_option_run_cannot_cross_a_command_separator(self, separator: str) -> None:
        """`git status; reset` is two commands — the second is not a git subcommand."""
        command = f"git status {separator} reset --hard"

        assert re.search(GIT_INVOCATION + r"reset\b", command) is None

    def test_does_not_match_a_bare_word_later_in_the_line(self) -> None:
        assert re.search(GIT_INVOCATION + r"reset\b", "git show HEAD:notes/reset") is None


class TestTheSeparatorSetIsLearnableFromATest:
    r"""The boundary set is stated here so the next reader need not infer it."""

    def test_the_separator_set_is_exactly_these_five(self) -> None:
        """`;`, `&`, `|` AND the two newline characters (Plan 00406).

        The newline was missing, so every consumer's segment ran past the end
        of its own command and judged the next line. It is asserted rather than
        described because the omission was invisible: each consumer looked
        correct on its own, and only the `&&`-versus-newline control exposed it.
        """
        assert set(SUBCOMMAND_SEPARATOR_CHARS) == {";", "&", "|", "\n", "\r"}

    def test_the_characters_are_real_not_escape_sequences(self) -> None:
        r"""A backslash in here would be iterated as a separator in its own right.

        The constant is interpolated into regex classes, where `\n` and a real
        newline are equivalent — but it is ALSO iterated character by character
        (the parametrised test above), and the escape spelling would hand that
        one a `\` and an `n` as two bogus separators.
        """
        assert "\\" not in SUBCOMMAND_SEPARATOR_CHARS


class TestGitSubcommandIndex:
    """Token-level equivalent of GIT_INVOCATION, for token-based handlers.

    ``sensitive_content`` matches on TOKENS on purpose: "commit", "tag" and
    "branch" are ordinary English, so a substring match would deny any sentence
    mentioning a branch. It therefore cannot use the regex fragment, and needs
    the same knowledge expressed over tokens.
    """

    @pytest.mark.parametrize(
        ("tokens", "expected"),
        [
            (["git", "commit"], 1),
            (["git", "-C", _SAFE_PATH, "commit"], 3),
            (["git", "--no-pager", "commit"], 2),
            (["git", "-c", "core.pager=cat", "commit"], 3),
            (["git", f"--git-dir={_SAFE_PATH}/.repo", "commit"], 2),
            (["git", "--work-tree", _SAFE_PATH, "commit"], 3),
            (["git", "--no-pager", "-C", _SAFE_PATH, "commit"], 4),
        ],
    )
    def test_finds_the_subcommand(self, tokens: list[str], expected: int) -> None:
        assert git_subcommand_index(tokens, 0) == expected

    def test_value_of_dash_c_is_not_mistaken_for_the_subcommand(self) -> None:
        """The exact defect: `-C`'s VALUE was read as the subcommand."""
        tokens = ["git", "-C", _SAFE_PATH, "commit", "-m", "x"]

        assert tokens[git_subcommand_index(tokens, 0) or 0] == "commit"

    def test_returns_none_when_options_never_end(self) -> None:
        assert git_subcommand_index(["git", "--no-pager"], 0) is None

    def test_returns_none_for_bare_git(self) -> None:
        assert git_subcommand_index(["git"], 0) is None


class TestOptionalSudo:
    """`sudo`, with or without its own options, or absent entirely."""

    @pytest.mark.parametrize(
        "command",
        ["pip install", "sudo pip install", "sudo -H pip install", "sudo -E -H pip install"],
    )
    def test_matches_with_and_without_sudo(self, command: str) -> None:
        assert re.search(OPTIONAL_SUDO + r"pip\s+install\b", command) is not None


class TestOptionalPath:
    """A binary may be named bare or by any path."""

    @pytest.mark.parametrize(
        "command",
        ["sed -i", "/usr/bin/sed -i", "/bin/sed -i", "./sed -i"],
    )
    def test_matches_named_and_path_qualified(self, command: str) -> None:
        assert re.search(OPTIONAL_PATH + r"sed\b", command) is not None

    def test_does_not_swallow_a_preceding_argument(self) -> None:
        """`\\S*/` must stay inside one token, not span a space.

        Otherwise `cat /etc/sed.conf` would read as an invocation of `sed`.
        """
        assert re.search(r"\|\s*" + OPTIONAL_PATH + r"bash\b", "curl x | cat /opt/bash") is None


class TestCompileCommandNamePattern:
    """A command name anchored at a segment start (Plan 00268 Phase 2).

    Extracted from ``command_hints`` because a SECOND handler now needs the
    same question answered. Two private copies is where the drift that Plan
    00200 Task 3.7 consolidated away begins again.
    """

    @pytest.mark.parametrize(
        "segment",
        [
            "ansible-lint site.yml",
            "/usr/bin/ansible-lint site.yml",
            "./ansible-lint site.yml",
            "env ANSIBLE_CONFIG=x ansible-lint site.yml",
            "env ansible-lint site.yml",
            "ansible-lint",
        ],
    )
    def test_matches_every_respelling_of_the_invocation(self, segment: str) -> None:
        from claude_code_hooks_daemon.utils.command_evasion import compile_command_name_pattern

        assert compile_command_name_pattern("ansible-lint").search(segment) is not None

    def test_does_not_match_the_name_as_an_argument(self) -> None:
        """The whole point of anchoring: `grep` is the command here."""
        from claude_code_hooks_daemon.utils.command_evasion import compile_command_name_pattern

        assert (
            compile_command_name_pattern("ansible-lint").search("grep ansible-lint notes") is None
        )

    def test_does_not_match_a_longer_hyphenated_name(self) -> None:
        """A trailing ``\\b`` would match here: the boundary between ``t`` and
        ``-`` is itself a word/non-word transition."""
        from claude_code_hooks_daemon.utils.command_evasion import compile_command_name_pattern

        assert compile_command_name_pattern("ansible-lint").search("ansible-lint-extra x") is None

    def test_matches_a_multi_word_name(self) -> None:
        from claude_code_hooks_daemon.utils.command_evasion import compile_command_name_pattern

        pattern = compile_command_name_pattern("go vet")

        assert pattern.search("go vet ./...") is not None
        assert pattern.search("go build ./...") is None

    def test_tolerates_extra_whitespace_between_words(self) -> None:
        from claude_code_hooks_daemon.utils.command_evasion import compile_command_name_pattern

        assert compile_command_name_pattern("go vet").search("go  vet ./...") is not None

    def test_leading_whitespace_in_the_segment_is_tolerated(self) -> None:
        """Segments arrive stripped in practice, but a caller that forgets
        should not silently get a non-match."""
        from claude_code_hooks_daemon.utils.command_evasion import compile_command_name_pattern

        assert compile_command_name_pattern("pytest").search("   pytest tests/") is not None
