"""git_stash and destructive_git judge COMMAND position, not quoted text (ledger N241, N200).

Governing ruling: CLAUDE/ARCHITECTURE.md, "Threat model: the agent is careless,
not hostile". A false positive on ordinary work is fixed by narrowing the
matcher; a literal `bash -c '...'` body stays in scope.

The command strings here are written in this file rather than typed on a Bash
command line, because a live guard would deny the command line that carries
them.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
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


#: Ordinary commands that only MENTION a guarded command. None may be denied.
_PROSE_COMMANDS = [
    "git commit -m 'document the git stash guard'",
    "grep -n 'git stash' CLAUDE/ARCHITECTURE.md",
    "cat > notes.md <<'EOF'\nnever run git stash\nEOF",
    "echo 'do not run git reset --hard'",
    "gh pr create --title x --body 'we ban git stash and git reset --hard'",
    "bash -c 'git commit -m \"document --amend\"'",
    "git commit -m 'mention git reset --hard and git commit --amend'",
    "printf '%s\\n' 'git stash is banned' > notes.txt",
    "echo 'git stash' && git status",
    "grep -rn 'git reset --hard' docs/ | wc -l",
    "gh issue create --title 'git stash bug' --body 'git stash drops work'",
]


class TestProseIsNotDenied:
    """Text in argument position is not a command in command position."""

    @pytest.mark.parametrize("command", _PROSE_COMMANDS)
    def test_git_stash_allows(self, command: str) -> None:
        assert GitStashHandler().matches(_input(command)) is False

    @pytest.mark.parametrize("command", _PROSE_COMMANDS)
    def test_destructive_git_allows(self, command: str) -> None:
        assert DestructiveGitHandler().matches(_input(command)) is False


#: Real commands, which must keep being denied.
_STASH_COMMANDS = [
    "git stash",
    "git stash push",
    "git stash push -m 'wip'",
    "bash -c 'git stash'",
    "bash -c 'git stash list; git stash'",
    "git stash list; git stash",
    "git stash list && git stash push",
    "git stash pop && git stash",
    "echo hi; git stash",
    "echo hi & git stash",
    "echo hi | git stash",
    "git status && git stash",
    "echo 'git stash' | bash",
    "echo 'git stash' | sh",
    "sudo git stash",
]

_RESET_COMMANDS = [
    "git reset --hard",
    "bash -c 'git reset --hard'",
    "git commit -m 'x' ; git reset --hard",
    "echo hi; git reset --hard HEAD~1",
    "git commit --amend",
    "bash -c 'git commit --amend'",
    "echo 'git reset --hard' | bash",
    # bash ends a single-quoted message at the next quote: a backslash does
    # not escape inside single quotes, so `git reset --hard` runs (N241).
    "git commit -m 'x\\' ; git reset --hard ; echo 'y'",
]


class TestRealCommandsAreStillDenied:
    @pytest.mark.parametrize("command", _STASH_COMMANDS)
    def test_git_stash_denies(self, command: str) -> None:
        assert GitStashHandler().matches(_input(command)) is True

    @pytest.mark.parametrize("command", _RESET_COMMANDS)
    def test_destructive_git_denies(self, command: str) -> None:
        assert DestructiveGitHandler().matches(_input(command)) is True


class TestRecoveryInOneSegmentDoesNotExemptAnother:
    """N200: judge each command segment on its own."""

    @pytest.mark.parametrize(
        "command",
        [
            "git stash list; git stash",
            "git stash list && git stash push",
            "git stash show || git stash",
        ],
    )
    def test_a_stash_after_a_recovery_form_is_denied(self, command: str) -> None:
        assert GitStashHandler().matches(_input(command)) is True

    @pytest.mark.parametrize(
        "command",
        [
            "git stash list",
            "git stash pop",
            "git stash apply && git stash list",
            "git stash list; git status",
        ],
    )
    def test_recovery_forms_alone_are_allowed(self, command: str) -> None:
        assert GitStashHandler().matches(_input(command)) is False

    def test_the_escape_hatch_still_passes_a_stash(self) -> None:
        command = 'MUST_STASH_BECAUSE="commit cannot work"; git stash'
        assert GitStashHandler().matches(_input(command)) is False


#: Both guards, each with the command it exists to deny.
_GUARDS: list[tuple[Any, str]] = [
    (GitStashHandler, "git stash"),
    (DestructiveGitHandler, "git reset --hard"),
]

#: Receivers that run, or may run, what is piped into them. A data head's text
#: is a command whenever the pipeline ends in anything but a known inert sink.
_RECEIVERS = [
    "bash",
    "fish",
    "busybox sh",
    "su -c bash",
    "(bash)",
    "at now",
    "parallel",
    "ssh host",
    "docker exec -i c sh",
    "kubectl exec -i p -- sh",
    "tee >(bash)",
    "tee log | bash",
    "python3",
]

#: Receivers that only read what is piped into them.
_INERT_RECEIVERS = ["wc -l", "tee log", "sort", "cat | wc -l"]


class TestEveryUnlistedReceiverFailsClosed:
    """M1: the receiver check is an allowlist of inert sinks, never a denylist."""

    @pytest.mark.parametrize("receiver", _RECEIVERS)
    @pytest.mark.parametrize(("handler", "destructive"), _GUARDS)
    def test_a_literal_piped_into_a_runner_is_denied(
        self, handler: Any, destructive: str, receiver: str
    ) -> None:
        command = f"echo '{destructive}' | {receiver}"
        assert handler().matches(_input(command)) is True

    @pytest.mark.parametrize("receiver", _INERT_RECEIVERS)
    @pytest.mark.parametrize(("handler", "destructive"), _GUARDS)
    def test_a_literal_piped_into_an_inert_sink_is_allowed(
        self, handler: Any, destructive: str, receiver: str
    ) -> None:
        command = f"echo '{destructive}' | {receiver}"
        assert handler().matches(_input(command)) is False


class TestRedirectOperatorsAreNotSeparators:
    """M2: the `&` of `2>&1`, `>&`, `<&`, `&>` and `&>>` ends no command."""

    @pytest.mark.parametrize("redirect", ["2>&1", "1>&2", ">&2", "&>/dev/null", "&>>log"])
    @pytest.mark.parametrize(("handler", "destructive"), _GUARDS)
    def test_a_redirected_literal_piped_into_a_shell_is_denied(
        self, handler: Any, destructive: str, redirect: str
    ) -> None:
        command = f"echo '{destructive}' {redirect} | bash"
        assert handler().matches(_input(command)) is True

    @pytest.mark.parametrize(("handler", "destructive"), _GUARDS)
    def test_a_redirect_alone_is_not_a_command(self, handler: Any, destructive: str) -> None:
        assert handler().matches(_input("git status 2>&1")) is False

    @pytest.mark.parametrize(("handler", "destructive"), _GUARDS)
    def test_a_lone_ampersand_still_separates(self, handler: Any, destructive: str) -> None:
        assert handler().matches(_input(f"echo hi & {destructive}")) is True


class TestRgPreRunsItsValue:
    """S1: `rg --pre CMD` runs CMD for each file."""

    @pytest.mark.parametrize("flag", ["--pre 'git stash'", "--pre='git stash'"])
    def test_rg_with_pre_is_not_a_data_head(self, flag: str) -> None:
        assert GitStashHandler().matches(_input(f"rg {flag} x")) is True

    def test_rg_without_pre_is_still_data(self) -> None:
        assert GitStashHandler().matches(_input("rg 'git stash' docs")) is False


class TestAcceptanceCommandsNeverExecute:
    """M3: an acceptance command runs through the real Bash tool, so it must parse only."""

    @pytest.mark.parametrize("handler_class", [GitStashHandler, DestructiveGitHandler])
    def test_every_wrapped_acceptance_command_is_parse_only_and_still_denied(
        self, handler_class: Any
    ) -> None:
        wrapped = [
            test
            for test in handler_class().get_acceptance_tests()
            if test.command.startswith("bash")
        ]

        assert wrapped
        for test in wrapped:
            assert test.command.startswith("bash -n -c "), test.title
            if test.expected_decision == Decision.DENY:
                assert handler_class().matches(_input(test.command)) is True, test.title
