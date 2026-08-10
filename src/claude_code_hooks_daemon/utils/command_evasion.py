"""Regex fragments that keep command-matching handlers un-bypassable.

A blocking handler that anchors on a BARE COMMAND NAME can be talked out of
matching by a caller who spells the same command differently. Three spellings
recur, and each one silently defeated a real handler in this codebase:

* ``git`` accepts GLOBAL OPTIONS before its subcommand, so ``git -C /p reset``
  slipped past every ``destructive_git`` rule and past ``git_stash``.
* ``sudo`` accepts ITS OWN options before the target command, so
  ``sudo -H pip install`` slipped past ``sudo_pip``.
* any binary may be named by PATH, so ``| /bin/bash`` slipped past
  ``curl_pipe_shell``.

All three are one defect: a bare-name anchor. Encoding each spelling ONCE means
a new handler composes the hardening rather than rediscovering it — and,
crucially, that fixing the fragment fixes every handler that uses it.

Every fragment here is deliberately PERMISSIVE. These back safety handlers,
which must fail CLOSED: an option or path spelling nobody anticipated must
never resolve to "allow". Over-matching is the acceptable failure direction,
and this project already documents blocking-handler false positives as intended
behaviour.

Each fragment is a STRING, not a compiled pattern, so callers can embed it in a
larger expression. None contains a capturing group — they compose into patterns
whose group numbering belongs to the caller.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

# A backslash immediately before a newline: the shell's line continuation.
# Compiled once — this runs on every Bash command the daemon sees.
_LINE_CONTINUATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"\\\r?\n")

# Characters that separate shell sub-commands. A token appearing AFTER one of
# these belongs to a DIFFERENT sub-command, so a fragment that must stay inside
# one segment forbids these characters rather than matching across them. This
# is what stops `git status; reset --hard` reading as a destructive git call.
SUBCOMMAND_SEPARATOR_CHARS = ";&|"

# One git global option: a token starting with `-`, optionally followed by a
# separate value token which by definition does NOT start with `-` (that would
# be the next option). Neither part may cross a sub-command separator.
_GIT_GLOBAL_OPTION = (
    rf"-[^\s{SUBCOMMAND_SEPARATOR_CHARS}]+"
    rf"(?:\s+[^-\s{SUBCOMMAND_SEPARATOR_CHARS}][^\s{SUBCOMMAND_SEPARATOR_CHARS}]*)?"
)

# `git` followed by any run of global options, leaving the match positioned at
# the subcommand. Prefix a subcommand pattern with this instead of `\bgit\s+`.
#
#     re.search(GIT_INVOCATION + r"reset\b", command)
#
# Note the option run is unambiguous and therefore cheap: each repetition must
# begin with `-` while its optional value must not, so there is exactly one way
# to parse any input and the nested quantifier cannot backtrack exponentially.
GIT_INVOCATION = rf"\bgit\s+(?:{_GIT_GLOBAL_OPTION}\s+)*"

# A REQUIRED `sudo`, with any run of its own options: "sudo ", "sudo -H ",
# "sudo -E -H ". Use this when sudo is the thing being blocked — a handler
# named for sudo must not match the command without it.
SUDO_INVOCATION = r"\bsudo(?:\s+-\S+)*\s+"

# The same, but OPTIONAL: use when sudo merely may appear in front of the real
# target, as in `curl ... | sudo bash`.
#
# Picking the wrong one of these two is a live hazard in BOTH directions.
# Optional-where-required is the dangerous way round: dropping `sudo` from
# `sudo pip install` leaves a pattern matching every ordinary `pip install`,
# which does not bypass anything — it blocks the entire project's installs.
OPTIONAL_SUDO = rf"(?:{SUDO_INVOCATION})?"

# An optional path qualifier before a binary name: matches "/usr/bin/", "./" or
# nothing, so `sed`, `/usr/bin/sed` and `./sed` all match one pattern. `\S*`
# cannot span whitespace, so this stays inside a single token and never
# swallows a preceding argument.
OPTIONAL_PATH = r"(?:\S*/)?"

# Git global options that take their value as a SEPARATE token. Everything else
# is either self-contained (`--git-dir=<path>`) or valueless (`--no-pager`), so
# these are the only ones whose value could be mistaken for the subcommand —
# which is exactly how `git -C /path commit` read "/path" as the subcommand and
# walked past the guard. Git's global-option set is closed and documented, so an
# explicit set is accurate here rather than a guess.
GIT_GLOBAL_OPTIONS_TAKING_SEPARATE_VALUE: Final[frozenset[str]] = frozenset(
    {
        "-C",
        "-c",
        "--git-dir",
        "--work-tree",
        "--namespace",
        "--exec-path",
        "--config-env",
        "--super-prefix",
    }
)


def normalise_line_continuations(command: str) -> str:
    r"""Replace shell line continuations with a plain space.

    A backslash immediately before a newline is not part of the command — the
    shell removes it and joins the lines. Every pattern in this daemon was
    written against the joined form, so a command split across lines slipped
    past guards that would have caught it written on one line::

        git reset --hard HEAD        -> denied
        git \<newline> reset --hard  -> ALLOWED

    That predates the global-option bypass and is independent of it: ``\s+``
    simply does not match a backslash. It is also the most innocent vector of
    the set — nobody writes it to evade anything, they write it because the
    command is long.

    Normalising once, at the point commands enter the daemon, is why this is a
    function and not nine more regexes: the shell already defines the sequence
    as whitespace, so no pattern should have to know about it.

    Note: a genuinely escaped backslash at end of line (``\\`` then newline) is
    also collapsed. That is the fail-CLOSED direction — it can only cause a
    guard to look at more text, never less.
    """
    return _LINE_CONTINUATION_PATTERN.sub(" ", command)


def git_subcommand_index(tokens: Sequence[str], git_index: int) -> int | None:
    """Index of the git SUBCOMMAND, skipping any global options after ``git``.

    The token-level counterpart to :data:`GIT_INVOCATION`, for handlers that
    match on tokens rather than by regex. ``sensitive_content`` is token-based
    deliberately — "commit", "tag" and "branch" are ordinary English words, so
    a substring match would deny any sentence mentioning a branch.

    Args:
        tokens: the whitespace-split command.
        git_index: index of the ``git`` token itself.

    Returns:
        Index of the first non-option token after the global options, or None
        if the tokens run out before one appears (e.g. a bare ``git``).
    """
    index = git_index + 1
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("-"):
            return index
        if "=" in token:
            # `--git-dir=<path>` carries its value in the same token.
            index += 1
        elif token in GIT_GLOBAL_OPTIONS_TAKING_SEPARATE_VALUE:
            # `-C <path>` — skip the option AND the value it consumes.
            index += 2
        else:
            # Valueless (`--no-pager`, `--bare`, `--paginate`).
            index += 1
    return None
