"""destructive_git and git_stash judge the git COMMAND, segment by segment.

Plan 00483 Task 3.2, batch (b). The threat model is "the agent is careless, not
hostile" (CLAUDE/ARCHITECTURE.md): an ordinary command, or text that only
MENTIONS a dangerous command, is allowed, and every real invocation stays
denied, alone or chained after another command.

The mechanisms that denied ordinary work were three: a pattern whose ``.*`` ran
across a command separator into the NEXT command, a flag test that matched a
substring of an operand (``build-final``), and a quoted argument of one command
(``git log --grep='...'``, ``awk '/.../'``) read as a second command.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import DestructiveGitHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.git_stash import GitStashHandler


def _event(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _denied(command: str) -> bool:
    event = _event(command)
    return DestructiveGitHandler().matches(event) or GitStashHandler().matches(event)


ORDINARY = [
    "git clean -nd build-final/",
    "git clean -n && rm -f foo.txt",
    "git checkout main && git log -- src/x.py",
    "git restore --source=HEAD~1 --staged src/x.py",
    "git restore src/x.py --staged",
    "git restore -S src/x.py",
    "git reset HEAD src/x.py && ls --hard",
    "git log --grep='git reset --hard'",
    "git log --grep 'git reset --hard' --oneline",
    "git log -S'git stash'",
    "awk '/git stash/ {print}' f",
    "git stash --help",
    "git stash -h",
    "cat <<'EOF'\ngit reset --hard\nEOF",
    "gh pr comment 1 --body-file - <<'EOF'\nrun git reset --hard first\nEOF",
    "gh issue create --title t --body-file - <<'EOF'\ngit stash is blocked\nEOF",
    "while read line; do echo \"$line\"; done <<'EOF'\ngit reset --hard\ngit stash\nEOF",
    "while IFS= read -r c; do echo \"$c\"; done <<'EOF'\ngit reset --hard\nEOF",
    "git log --format='git reset --hard %H' --oneline",
    "git log --pretty='git stash %H'",
    "git grep -n 'git stash' src",
    "git log -G'git stash'",
]


@pytest.mark.parametrize("command", ORDINARY)
def test_ordinary_command_is_allowed(command: str) -> None:
    assert not _denied(command)


DANGEROUS = [
    "git clean -fd",
    "git clean -f",
    "git clean -df",
    "git clean --force",
    "git clean -d -f",
    "git clean -nfd",
    "git checkout -- f",
    "git checkout main -- f",
    "git restore f",
    "git restore --source=HEAD~1 src/x.py",
    "git restore -s HEAD~1 src/x.py",
    "git restore --staged --worktree f",
    "git restore -SW f",
    "git reset --hard",
    "git reset --hard HEAD~1",
    "git -C /repo reset --hard",
    "git stash",
    "git stash push",
    "git stash -u",
    "git -C /repo stash",
    "bash -c 'git reset --hard'",
    "sudo git reset --hard",
    "env X=1 git stash",
    "eval 'git reset --hard'",
    "git log --grep='x' && git reset --hard",
    "awk '/x/ {print}' f && git stash",
    "git stash --help && git stash",
    # N383: a quoted or escaped global-option value with a blank in it.
    "git -C 'my dir' reset --hard",
    'git -C "my dir" reset --hard',
    "git -C my\\ dir reset --hard",
    "git -C 'my dir' stash",
    'git -C "my dir" stash push',
    "git -C my\\ dir stash",
    "git -C 'my dir' clean -fd",
    "git -C 'my dir' checkout -- f",
    "git -c 'user.name=A B' reset --hard",
    "git -c user.name='A B' reset --hard",
    "git -c 'user.name=A B' stash",
]


@pytest.mark.parametrize("command", DANGEROUS)
def test_real_invocation_stays_denied(command: str) -> None:
    assert _denied(command)


@pytest.mark.parametrize("command", DANGEROUS)
@pytest.mark.parametrize("lead", ["x && ", "x ; ", "x || ", "(", "ls | "])
def test_real_invocation_stays_denied_after_another_command(lead: str, command: str) -> None:
    assert _denied(lead + command)


@pytest.mark.parametrize(
    "command",
    [
        "git clean -nd build-final/ && git clean -fd",
        "git checkout main && git log -- x && git checkout -- f",
        "while read l; do echo $l; done <<'EOF'\nx\nEOF\ngit reset --hard",
        "git log -c alias.n='!git reset --hard' n",
        "git -c alias.nuke='!git reset --hard' nuke",
        "bash <<'EOF'\ngit reset --hard\nEOF",
        "gh api x --input - <<'EOF' | bash\ngit reset --hard\nEOF",
        "while read c; do eval \"$c\"; done <<'EOF'\ngit reset --hard\nEOF",
        "while read c; do bash -c \"$c\"; done <<'EOF'\ngit stash\nEOF",
        "while read c; do $c; done <<'EOF'\ngit stash\nEOF",
        # Review r1 B1: a quoted argument of a git command that RUNS it.
        "git submodule foreach --recursive 'git reset --hard && git clean -fdx'",
        "git submodule foreach 'git stash'",
        'git submodule foreach "git reset --hard"',
        "git rebase -i --exec 'git clean -fd'",
        "git rebase -x 'git stash'",
        "git bisect run bash -c 'git stash && make'",
        # Review r1 S1: a `=!` alias body is runnable.
        "git -c 'alias.n=!git reset --hard' n",
        # Review r1 S2: the loop runs the line it read.
        "while read l; do echo \"$($l)\"; done <<'EOF'\ngit stash\nEOF",
        "while read l; do echo `$l`; done <<'EOF'\ngit stash\nEOF",
        # Review r1 NIT: piping the format string into a shell runs it.
        "git log --format='git reset --hard %H' | sh",
        "git log --grep='git stash' | bash",
    ],
)
def test_a_second_real_command_or_an_executing_receiver_stays_denied(command: str) -> None:
    assert _denied(command)
