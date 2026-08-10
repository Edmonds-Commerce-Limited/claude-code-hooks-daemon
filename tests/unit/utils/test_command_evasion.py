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
)

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
