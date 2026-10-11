"""A shell comment runs to the end of the LINE: operators inside it do not split (N407 residual).

The command-position segment splitter used to cut a line at `|`, `;` or `&&`
before the comment was removed, so `ls # note | sudo pip install x` read the
text after the `#` as a second command.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.gh_issue_comments import GhIssueCommentsHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.git_stash import GitStashHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.github_auto_close_keywords import (
    GithubAutoCloseKeywordsHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.pip_break_system import PipBreakSystemHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.sudo_pip import SudoPipHandler
from claude_code_hooks_daemon.utils.command_position import (
    _REDIRECT_AMPERSAND,
    SEGMENT_SEPARATORS,
    command_position_code_segments,
    command_position_code_segments_with_separators,
    command_position_segments,
    segment_spans,
)
from claude_code_hooks_daemon.utils.shell_segmentation import split_unquoted_spans

_CORPUS = Path(__file__).resolve().parents[2] / "fixtures" / "ordinary_command_corpus.yaml"


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _denied_by_either(command: str) -> bool:
    event = _bash(command)
    return PipBreakSystemHandler().matches(event) or SudoPipHandler().matches(event)


def _code(command: str) -> list[str]:
    return [s.strip() for s in command_position_code_segments(command) if s.strip()]


class TestOperatorsInsideACommentDoNotSplit:
    @pytest.mark.parametrize(
        "command",
        [
            "ls # note | sudo pip install x",
            "ls # note ; sudo pip install x",
            "ls # note && sudo pip install x",
            "ls # note || sudo pip install x",
            "ls # note & sudo pip install x",
            "true # export PIP_BREAK_SYSTEM_PACKAGES=1 && pip install x",
            "true  #note;pip install --break-system-packages x",
        ],
    )
    def test_comment_text_is_not_a_command(self, command: str) -> None:
        assert len(segment_spans(command)) == 1
        assert len(_code(command)) == 1
        assert not _denied_by_either(command)

    def test_the_commands_before_the_comment_still_split(self) -> None:
        assert _code("a && b # c && d | e") == ["a", "b"]

    def test_separator_pairing_ignores_the_comment(self) -> None:
        got = command_position_code_segments_with_separators("a; b # c | d && e")
        assert [(sep, seg.strip()) for sep, seg in got] == [("", "a"), (";", "b")]

    def test_a_whole_line_comment_is_one_segment(self) -> None:
        assert len(segment_spans("# a | b ; c && d")) == 1

    def test_judging_guards_see_the_comment_as_part_of_one_segment(self) -> None:
        assert command_position_segments("ls # a ; b") == ["ls # a ; b"]


class TestANewlineEndsTheComment:
    @pytest.mark.parametrize(
        "command",
        [
            "# note\nsudo pip install x",
            "ls # note | x\nsudo pip install x",
            "ls # note && x\npip install --break-system-packages x",
            "true # a\n# b\nsudo pip install x",
        ],
    )
    def test_a_real_command_on_the_next_line_still_denies(self, command: str) -> None:
        assert _denied_by_either(command)

    def test_the_next_line_is_its_own_segment(self) -> None:
        assert _code("ls # a | b\npwd") == ["ls", "pwd"]


class TestNotAComment:
    @pytest.mark.parametrize(
        "command",
        [
            "echo '#' && sudo pip install x",
            'echo "#" ; sudo pip install x',
            "echo '# x' | sudo pip install x",
            "echo a#b && sudo pip install x",
            "echo $# && sudo pip install x",
            "echo ${#x} && sudo pip install x",
            "echo ${#x}; sudo pip install x",
            "x=a#b; sudo pip install x",
            "echo \\# && sudo pip install x",
        ],
    )
    def test_a_hash_that_is_not_a_comment_leaves_the_real_operator_live(self, command: str) -> None:
        assert _denied_by_either(command)
        assert len(segment_spans(command)) >= 2

    def test_a_hash_inside_a_quoted_string_holding_an_operator_is_one_word(self) -> None:
        assert len(segment_spans("echo 'a # b | c'")) == 1

    def test_a_quoted_heredoc_body_is_inert_and_a_hash_in_it_is_not_a_comment(self) -> None:
        command = "cat > n.md <<'EOF'\n# heading | sudo pip install x\nEOF\nsudo pip install y"
        assert _denied_by_either(command)
        assert not _denied_by_either("cat > n.md <<'EOF'\n# sudo pip install x\nEOF")

    def test_an_executed_heredoc_body_line_with_a_hash_word_later_still_denies(self) -> None:
        command = "bash <<'EOF'\necho '#'\nsudo pip install x\nEOF"
        assert _denied_by_either(command)

    def test_a_hash_in_a_heredoc_body_does_not_hide_the_next_command_on_its_line(self) -> None:
        command = "bash <<EOF\nls a#b && sudo pip install x\nEOF"
        assert _denied_by_either(command)


_DOUBTFUL_PREFIXES = [
    "grep -rn issue\\ #42 docs/",
    "grep -n TODO\\ #12 src/x.py",
    "rg Fixes\\ #7",
    "printf 'x' a\\ #",
    "echo a\\;#",
    "echo a\\|#",
    "echo a\\&#",
    "echo a\\(#",
    "echo a\\>#",
    "echo a\\\t#",
    "echo a\\\n#",
    "echo $(echo a)#",
    "cat <(echo a)#",
    "echo $((1))#",
    "echo ${x:-a #b}",
    "echo `echo #`",
]
_REAL_COMMANDS = [
    "git reset --hard",
    "sudo pip install x",
    "pip install --break-system-packages x",
    "gh issue view 5",
    "git commit -m 'Fixes #12'",
    "git stash",
]


def _any_guard_denies(command: str) -> bool:
    event = _bash(command)
    guards = (
        DestructiveGitHandler(),
        SudoPipHandler(),
        PipBreakSystemHandler(),
        GhIssueCommentsHandler(),
        GithubAutoCloseKeywordsHandler(),
        GitStashHandler(),
    )
    return any(guard.matches(event) for guard in guards)


class TestDoubtfulHashIsNeverAComment:
    """A `#` that bash reads as part of a word (escaped, after a substitution, inside
    `${}` or backticks) must not swallow the real command after it."""

    @pytest.mark.parametrize("prefix", _DOUBTFUL_PREFIXES)
    @pytest.mark.parametrize("real", _REAL_COMMANDS)
    @pytest.mark.parametrize("sep", ["; ", " && "])
    def test_the_real_command_after_it_still_denies(self, prefix: str, real: str, sep: str) -> None:
        assert _any_guard_denies(prefix + sep + real)

    @pytest.mark.parametrize("prefix", _DOUBTFUL_PREFIXES)
    def test_each_named_guard_denies_its_own_command(self, prefix: str) -> None:
        guarded = [
            (DestructiveGitHandler(), "git reset --hard"),
            (SudoPipHandler(), "sudo pip install x"),
            (PipBreakSystemHandler(), "pip install --break-system-packages x"),
        ]
        for guard, real in guarded:
            assert guard.matches(_bash(prefix + "; " + real)), (prefix, real)

    @pytest.mark.parametrize("prefix", _DOUBTFUL_PREFIXES)
    def test_the_line_is_split_after_the_doubtful_hash(self, prefix: str) -> None:
        assert len(segment_spans(prefix + "; git reset --hard")) >= 2

    def test_a_backslash_newline_before_hash_continues_the_word(self) -> None:
        assert len(segment_spans("echo a\\\n#; git reset --hard")) == 2

    def test_a_real_comment_after_a_closed_substitution_still_swallows(self) -> None:
        assert len(segment_spans("x=$(date) # note | y && z")) == 1
        assert len(segment_spans("echo ${x:-a} # note | y")) == 1
        assert len(segment_spans("echo `date` # note | y")) == 1


class TestNoChangeForCommandsWithoutAComment:
    def test_whole_corpus_hash_free_segments_match_the_comment_blind_splitter(self) -> None:
        # For a command with no `#` at all the comment-aware splitter and the
        # shared comment-blind one must agree on every span.
        rows = yaml.safe_load(_CORPUS.read_text(encoding="utf-8"))["rows"]
        checked = 0
        for row in rows:
            command = row["command"]
            if "#" in command:
                continue
            checked += 1
            masked = _REDIRECT_AMPERSAND.sub(lambda match: match.group().replace("&", "_"), command)
            assert segment_spans(command) == split_unquoted_spans(
                masked, SEGMENT_SEPARATORS
            ), command
        assert checked > 100

    def test_whole_corpus_with_a_hash_differs_only_inside_a_comment(self) -> None:
        rows = yaml.safe_load(_CORPUS.read_text(encoding="utf-8"))["rows"]
        for row in rows:
            command = row["command"]
            new = segment_spans(command)
            # Every new span boundary is an old one (comment-aware splitting only removes).
            old = {end for _, end in split_unquoted_spans(command, SEGMENT_SEPARATORS)}
            assert {end for _, end in new} <= old | {len(command)}, command

    def test_shared_splitter_is_unchanged_by_default(self) -> None:
        spans = split_unquoted_spans("ls # a | b", SEGMENT_SEPARATORS)
        assert len(spans) == 2
