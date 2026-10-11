"""Shared reading of `gh issue view` / `gh pr view` for the comment guards (ledger N408).

`gh_issue_comments` and `gh_pr_comments` ask one question: does a command RUN
`gh <noun> view` without asking for the comments? Answering it over the raw
string denied a command that only mentioned the view (an echo, a grep pattern,
a message), cut the view at a `|` inside a quoted `--jq` value, and did not
read `--json=comments`.

The command is therefore read per COMMAND-POSITION segment
(:func:`command_position_segments`), which already blanks data heads, message
bodies and quoted heredoc bodies and reads a literal `bash -c` body, and the
segment's flags are read as shell words, so quotes decide where a value ends.
"""

from __future__ import annotations

import re

from claude_code_hooks_daemon.utils.command_position import command_position_code_segments
from claude_code_hooks_daemon.utils.shell_segmentation import resolve_shell_word, shell_word_spans

_COMMENTS_FLAG = "--comments"
_COMMENTS_SHORT_FLAG = "-c"
#: Flags after which the view fetches no comments to miss: help text, or the browser.
_NO_FETCH_FLAGS = frozenset({"--help", "-h", "--web", "-w"})
_JSON_FLAG = "--json"
_COMMENTS_FIELD = "comments"


def _view_pattern(noun: str) -> re.Pattern[str]:
    return re.compile(rf"\bgh\s+{noun}\s+view\b", re.IGNORECASE)


def _asks_for_comments(view: str) -> bool:
    """Whether the words of one view segment carry `--comments` or a `comments` JSON field."""
    words = [resolve_shell_word(view[start:end]) for start, end in shell_word_spans(view)]
    for index, word in enumerate(words):
        if word is None:
            continue
        if word in _NO_FETCH_FLAGS or word in (_COMMENTS_FLAG, _COMMENTS_SHORT_FLAG):
            return True
        if word.startswith(_COMMENTS_FLAG + "="):
            # A boolean flag: `--comments=false` is the one spelling that declines.
            if word[len(_COMMENTS_FLAG) + 1 :].lower() != "false":
                return True
        fields: str | None = None
        if word == _JSON_FLAG:
            fields = words[index + 1] if index + 1 < len(words) else None
        elif word.startswith(_JSON_FLAG + "="):
            fields = word[len(_JSON_FLAG) + 1 :]
        if fields is not None and _COMMENTS_FIELD in fields.split(","):
            return True
    return False


def uncommented_view_segment(command: str, noun: str) -> str | None:
    """The first run `gh <noun> view` segment that does not ask for comments, or None.

    Returned from the `gh` word on, as it appears in the command-position view.
    """
    pattern = _view_pattern(noun)
    for segment in command_position_code_segments(command):
        match = pattern.search(segment)
        if match is None:
            continue
        view = segment[match.start() :]
        if not _asks_for_comments(view):
            return view
    return None


def suggest_with_comments(command: str, view: str) -> str:
    """``command`` with the comment request added to the view segment ``view``.

    A `--json` field list gains `,comments`; any other view gains `--comments`
    (inserted before the whitespace that separates it from a chained command).
    ``view`` is spliced where it appears in the command; a view read out of a
    `bash -c` body or otherwise not found verbatim is returned fixed on its own.
    """
    trimmed = view.rstrip()
    trailing_ws = view[len(trimmed) :]
    fixed = _with_comments(trimmed) + trailing_ws
    if view in command:
        return command.replace(view, fixed, 1)
    return fixed.strip()


def _with_comments(view: str) -> str:
    spans = shell_word_spans(view)
    for index, (start, end) in enumerate(spans):
        word = resolve_shell_word(view[start:end])
        if word is None:
            continue
        if word.startswith(_JSON_FLAG + "="):
            return view[:end] + ",comments" + view[end:]
        if word == _JSON_FLAG and index + 1 < len(spans):
            value_end = spans[index + 1][1]
            return view[:value_end] + ",comments" + view[value_end:]
    return f"{view} {_COMMENTS_FLAG}"
