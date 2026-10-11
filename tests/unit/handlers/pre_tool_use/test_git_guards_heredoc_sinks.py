"""Heredoc bodies that are DATA to git_stash and destructive_git (ledger N400, N401).

N400: `gh pr create --body "$(cat <<'EOF' ... EOF)"` is the standard PR-body
idiom. The quoted-delimiter body is text handed to `cat`, whose output becomes
the `--body` value, so a body that DESCRIBES a blocked command is prose.

N401: `git -c k=v commit -F - <<'EOF'` takes its message from the heredoc just as
`git commit -F - <<'EOF'` does; a global option before `commit` must not make
the body code.

The command strings are written in this file rather than typed on a Bash
command line, because a live guard would deny the command line that carries them.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.git_stash import GitStashHandler


@pytest.fixture(autouse=True)
def _fresh_data_layer() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


def _input(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _gh_body(subcommand: str, option: str, body: str, closer: str = ')"') -> str:
    return f"gh {subcommand} {option} \"$(cat <<'EOF'\n{body}\nEOF\n{closer}"


#: Ordinary PR and comment bodies that DESCRIBE a blocked command. None may be denied.
_DATA_COMMANDS = [
    _gh_body("pr create --title x", "--body", "blocks git reset --hard"),
    _gh_body("pr create --title x", "-b", "blocks git reset --hard"),
    _gh_body("issue comment 5", "--body", "blocks git reset --hard"),
    _gh_body("pr create --title x", "--body", "never run git stash"),
    _gh_body("issue comment 5", "--body", "never run git stash drop"),
    _gh_body("pr create --title x", "--body", "line one\n\n- git reset --hard\n- git stash"),
    "gh pr create --title x --body=\"$(cat <<'EOF'\nblocks git reset --hard\nEOF\n)\"",
    "gh pr create --title x --body \"$(cat <<'EOF'\nblocks git reset --hard\nEOF\n)\" --base main",
    'gh pr create --title x --body "$(cat <<"EOF"\nblocks git reset --hard\nEOF\n)"',
    "git -c core.x=1 commit -F - <<'EOF'\nblocks git reset --hard\nEOF",
    "git -c user.email=a@b.c commit -F - <<'EOF'\nnever run git stash\nEOF",
    "git -c core.x=1 -c user.name=n commit -F - <<'EOF'\nblocks git reset --hard\nEOF",
    "git commit -F - <<'EOF'\nblocks git reset --hard\nEOF",
]


class TestHeredocBodyIsData:
    """A quoted heredoc body that only a body or message reads is prose."""

    @pytest.mark.parametrize("command", _DATA_COMMANDS)
    def test_destructive_git_allows(self, command: str) -> None:
        assert DestructiveGitHandler().matches(_input(command)) is False

    @pytest.mark.parametrize("command", _DATA_COMMANDS)
    def test_git_stash_allows(self, command: str) -> None:
        assert GitStashHandler().matches(_input(command)) is False


#: Commands that really run the blocked command, which must keep being denied.
_DESTRUCTIVE_STILL_DENIED = [
    # An UNQUOTED delimiter: bash expands the substitution inside the body.
    'gh pr create --title x --body "$(cat <<EOF\n$(git reset --hard)\nEOF\n)"',
    # The substitution itself is the command.
    'gh pr create --title x --body "$(git reset --hard)"',
    # A heredoc whose receiver is not `cat` runs it.
    "gh pr create --title x --body \"$(bash <<'EOF'\ngit reset --hard\nEOF\n)\"",
    # The body is not what the heredoc feeds: the option is some other flag.
    "gh pr create --title x --head \"$(bash <<'EOF'\ngit reset --hard\nEOF\n)\"",
    # A `cat` piped on into an interpreter runs the body.
    "gh pr create --title x --body \"$(cat <<'EOF' | bash\ngit reset --hard\nEOF\n)\"",
    # A real command after the body substitution still runs.
    "gh pr create --body \"$(cat <<'EOF'\nprose\nEOF\n)\" && git reset --hard",
    # A global option does not make a bash-fed heredoc safe.
    "git -c core.x=1 commit -F - <<EOF\n$(git reset --hard)\nEOF",
    "git -c core.x=1 reset --hard",
    # A `-c` that sets a key git RUNS (or a value the reader cannot place) can run the body.
    "git -c core.fsmonitor=sh commit -F - <<'EOF'\ngit reset --hard\nEOF",
    "git -c gpg.program=sh commit -F - <<'EOF'\ngit reset --hard\nEOF",
    "git -c \"$SETTING\" commit -F - <<'EOF'\ngit reset --hard\nEOF",
    "git -c core.x commit -F - <<'EOF'\ngit reset --hard\nEOF",
    # `-b` is a body flag only for gh; another command's `-b` value is not blanked.
    "git checkout -b \"$(cat <<'EOF'\nx\nEOF\n)\" && git reset --hard",
    # A gh group outside the body-bearing ones keeps its value judged.
    "gh alias set -b \"$(cat <<'EOF'\ngit reset --hard\nEOF\n)\"",
    "bash <<'EOF'\ngit -c core.x=1 reset --hard\nEOF",
]

_STASH_STILL_DENIED = [
    'gh pr create --title x --body "$(cat <<EOF\n$(git stash)\nEOF\n)"',
    'gh issue comment 5 --body "$(git stash)"',
    "git -c core.x=1 commit -F - <<EOF\n$(git stash)\nEOF",
    "gh pr create --body \"$(cat <<'EOF'\nprose\nEOF\n)\" && git stash",
]


class TestRealCommandsStayDenied:
    """The narrowing never covers a body the shell can execute."""

    @pytest.mark.parametrize("command", _DESTRUCTIVE_STILL_DENIED)
    def test_destructive_git_denies(self, command: str) -> None:
        assert DestructiveGitHandler().matches(_input(command)) is True

    @pytest.mark.parametrize("command", _STASH_STILL_DENIED)
    def test_git_stash_denies(self, command: str) -> None:
        assert GitStashHandler().matches(_input(command)) is True
