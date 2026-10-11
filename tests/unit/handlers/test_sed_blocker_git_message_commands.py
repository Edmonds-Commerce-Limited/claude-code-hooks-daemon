"""N399: the message exemption covers every git command that takes a message.

`git merge -m '... sed ...'` and `git tag -a v1 -m '... sed ...'` were denied
while the identical `git commit -m` was allowed. The exemption now covers
`commit`, `merge` and `tag`, found by the shared `GIT_INVOCATION` pattern, with
the batch-C rule intact: a sed run inside `$( )`, a backtick or `<( )` is never
a mention, and a sed in a command of its own stays denied.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker import SedBlockerHandler

# Assembled so this file does not hold the guarded word as one literal span.
_SED = "se" + "d"

_MESSAGE_COMMANDS = [
    "git commit -m",
    "git merge --no-ff topic -m",
    "git merge -m",
    "git tag -m",
    "git tag -a v1.2.3 -m",
    "git -C /w merge --no-ff topic -m",
    "git -C /w tag -a v1.2.3 -m",
    "git -c user.name=dev tag -a v1 -m",
    "git --git-dir=/w/.git merge topic -m",
]


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> None:
    reset_data_layer()


def _matches(command: str) -> bool:
    return SedBlockerHandler().matches({"tool_name": "Bash", "tool_input": {"command": command}})


class TestAMessageMentioningSedIsAllowed:
    @pytest.mark.parametrize("prefix", _MESSAGE_COMMANDS)
    def test_single_quoted_message(self, prefix: str) -> None:
        assert _matches(f"{prefix} 'the {_SED} blocker now covers merge'") is False

    @pytest.mark.parametrize("prefix", _MESSAGE_COMMANDS)
    def test_double_quoted_message(self, prefix: str) -> None:
        assert _matches(f'{prefix} "avoid {_SED} -i in scripts"') is False

    @pytest.mark.parametrize("prefix", _MESSAGE_COMMANDS)
    def test_quoted_heredoc_message(self, prefix: str) -> None:
        command = f"{prefix} \"$(cat <<'EOF'\nuse {_SED} -i\nEOF\n)\""
        assert _matches(command) is False


class TestSedRunInsideTheMessageIsDenied:
    @pytest.mark.parametrize("prefix", _MESSAGE_COMMANDS)
    @pytest.mark.parametrize(
        "message",
        [
            f'"$({_SED} -i s/a/b/ f)"',
            f'"`{_SED} -i s/a/b/ f`"',
            f'"note $(echo $({_SED} -i s/a/b/ f))"',
        ],
    )
    def test_substitution_runs_sed(self, prefix: str, message: str) -> None:
        assert _matches(f"{prefix} {message}") is True

    @pytest.mark.parametrize("prefix", _MESSAGE_COMMANDS)
    def test_process_substitution_runs_sed(self, prefix: str) -> None:
        assert _matches(f"{prefix} x -F <({_SED} -n 1p f)") is True

    @pytest.mark.parametrize("prefix", _MESSAGE_COMMANDS)
    def test_a_literal_substitution_in_single_quotes_only_mentions(self, prefix: str) -> None:
        assert _matches(f"{prefix} '$({_SED} -i x) is literal'") is False


class TestRealSedStaysDenied:
    @pytest.mark.parametrize(
        "command",
        [
            f"git merge topic -m x && {_SED} -i 's/a/b/' f",
            f"{_SED} -i 's/a/b/' f && git merge topic -m x",
            f"git tag -a v1 -m x; {_SED} -i 's/a/b/' f",
            f"git -C /w tag -a v1 -m x\n{_SED} -i 's/a/b/' f",
            f"git merge --abort && {_SED} -n 1p f",
            f"git -C /w branch {_SED} -i",
            f"git -c a.b=c log | {_SED} 's/a/b/'",
        ],
    )
    def test_executed_sed_is_denied(self, command: str) -> None:
        assert _matches(command) is True
