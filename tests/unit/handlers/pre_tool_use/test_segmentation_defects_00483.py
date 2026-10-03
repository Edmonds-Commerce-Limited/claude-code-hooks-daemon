"""Plan 00483 Task 3.1: shell-segmentation defects N85, N48, N87, N93 (ledger 00466).

Each case goes through the real handler. Destructive spellings are assembled from
fragments so this file does not itself contain the commands under test.
"""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.project_containment import (
    ProjectContainmentHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker import SedBlockerHandler
from claude_code_hooks_daemon.utils.shell_segmentation import resolve_shell_word

_RESET_HARD = "git reset " + "--hard"
_SED_I = "se" + "d -i 's/a/b/' f.txt"


def _bash(command: str) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


@pytest.fixture
def _root() -> Iterator[None]:
    with patch("claude_code_hooks_daemon.core.project_context.ProjectContext.project_root") as m:
        m.return_value = Path("/repo")
        yield


class TestN85BackslashQuoteInSingleQuotes:
    """A backslash is literal in single quotes, so `\\'` closes the quote."""

    def test_command_after_closed_quote_is_seen(self) -> None:
        command = f"git commit -m 'a\\'; {_RESET_HARD}; echo 'x'"
        assert DestructiveGitHandler().matches(_bash(command)) is True

    def test_message_with_backslash_quote_is_still_prose(self) -> None:
        command = f'git commit -m "it\\\'s about {_RESET_HARD}"'
        assert DestructiveGitHandler().matches(_bash(command)) is False


class TestN48NewlineSeparatesCommitFromSed:
    def test_sed_after_newline_is_denied(self) -> None:
        assert SedBlockerHandler().matches(_bash(f"git commit -m x\n{_SED_I}")) is True

    def test_sed_after_semicolon_is_denied(self) -> None:
        assert SedBlockerHandler().matches(_bash(f"git commit -m x; {_SED_I}")) is True

    def test_sed_after_message_mention_is_denied(self) -> None:
        command = f"git commit -m 'about sed' && {_SED_I}"
        assert SedBlockerHandler().matches(_bash(command)) is True

    def test_sed_in_multiline_message_is_allowed(self) -> None:
        assert SedBlockerHandler().matches(_bash('git commit -m "line one\nsed blocker"')) is False

    def test_sed_in_quoted_heredoc_message_is_allowed(self) -> None:
        command = "git commit -F - <<'EOF'\nBlock sed\nEOF"
        assert SedBlockerHandler().matches(_bash(command)) is False

    def test_sed_in_command_substitution_heredoc_message_is_allowed(self) -> None:
        command = "git commit -m \"$(cat <<'EOF'\nBlock sed\nEOF\n)\""
        assert SedBlockerHandler().matches(_bash(command)) is False

    def test_semicolon_inside_message_is_allowed(self) -> None:
        assert SedBlockerHandler().matches(_bash("git commit -m 'fix; sed guard'")) is False


class TestN87AnsiCBodyIsDecoded:
    def test_newline_escape_separates_commands(self) -> None:
        command = f"bash -c $'echo a\\n{_RESET_HARD}'"
        assert DestructiveGitHandler().matches(_bash(command)) is True

    def test_ansi_c_prose_stays_prose(self) -> None:
        command = f"bash -c $'echo about {_RESET_HARD}'"
        assert DestructiveGitHandler().matches(_bash(command)) is False

    @pytest.mark.parametrize(
        ("word", "expected"),
        [
            ("$'a\\nb'", "a\nb"),
            ("x$'\\x41'y", "xAy"),
            ("$'it\\'s'", "it's"),
            ("$'unterminated", None),
        ],
    )
    def test_resolve_shell_word_decodes_ansi_c(self, word: str, expected: str | None) -> None:
        assert resolve_shell_word(word) == expected


@pytest.mark.usefixtures("_root")
class TestN93EvalBodyIsACommand:
    def test_eval_redirect_outside_project_is_denied(self) -> None:
        assert ProjectContainmentHandler().matches(_bash("eval 'echo x > /opt/zz.txt'")) is True

    def test_eval_unquoted_arguments_are_joined(self) -> None:
        assert ProjectContainmentHandler().matches(_bash("eval echo x '>' /opt/zz.txt")) is True

    def test_eval_inside_project_is_allowed(self) -> None:
        assert ProjectContainmentHandler().matches(_bash("eval 'echo x > /repo/a.txt'")) is False

    def test_eval_of_a_variable_is_out_of_scope(self) -> None:
        assert ProjectContainmentHandler().matches(_bash('eval "$CMD"')) is False

    def test_eval_of_a_substitution_is_allowed(self) -> None:
        assert ProjectContainmentHandler().matches(_bash('eval "$(ssh-agent -s)"')) is False
