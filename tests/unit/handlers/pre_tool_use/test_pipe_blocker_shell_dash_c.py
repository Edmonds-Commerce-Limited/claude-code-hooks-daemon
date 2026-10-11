"""N363: a pipe inside a `bash -c '...'` string is judged on its real producer.

The guidance says every pipe is judged on its own producer and that a pipe
inside `$( )` belongs to the command inside it. A single-quoted `bash -c`
string is a shell program in the same way, but single quotes had no narrowing,
so the producer read as `bash -c 'grep x f | sort` and a whitelisted pipeline
was denied as "bash unrecognized". The body is now treated as a command
region, exactly like a substitution.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler

# Assembled so the guarded pipes are not literal spans in this file.
_TAIL = "ta" + "il"
_HEAD = "he" + "ad"


def _matches(command: str) -> bool:
    return PipeBlockerHandler().matches({"tool_name": "Bash", "tool_input": {"command": command}})


def _producer(command: str) -> str | None:
    return PipeBlockerHandler()._find_offending_producer(command)


class TestWhitelistedProducerInsideShellDashC:
    @pytest.mark.parametrize(
        "command",
        [
            f"bash -c 'grep x f | sort | {_TAIL} -n 2'",
            f"bash -c 'V=$(ls -d /tmp/* | {_HEAD} -n 1); echo $V'",
            f"bash -c 'grep x f | {_TAIL} -n 2'",
            f"bash -lc 'grep x f | {_TAIL} -n 2'",
            f"bash -l -c 'grep x f | {_TAIL} -n 2'",
            f"sh -c 'ls | {_HEAD} -1'",
            f"zsh -c 'git log --format=%H | {_HEAD} -1'",
            f"cd /w && bash -c 'cd sub; grep x f | {_TAIL} -3'",
            f"bash -c 'echo a; ls | {_HEAD} -1' && echo done",
            f"bash -c 'V=$(grep x f | {_HEAD} -1); W=$(ls | {_TAIL} -1)'",
        ],
    )
    def test_cheap_pipeline_in_the_body_is_allowed(self, command: str) -> None:
        assert _matches(command) is False

    def test_the_wrapper_is_not_a_whitelist_entry_for_its_pipe(self) -> None:
        # A quoted string that is NOT a shell program keeps its old reading.
        assert _matches(f"echo 'bash -c x | {_TAIL} -1'") is False


class TestExpensiveProducerInsideShellDashC:
    @pytest.mark.parametrize(
        "command,producer",
        [
            (f"bash -c 'pytest tests | {_TAIL} -3'", "pytest tests"),
            (f"bash -c 'grep x f | pytest tests | {_TAIL} -3'", "pytest tests"),
            (f"bash -c 'V=$(pytest tests | {_HEAD} -1)'", "pytest tests"),
            (f"sh -c 'echo a; npm test | {_TAIL} -5'", "npm test"),
            (f"bash -lc 'make all | {_TAIL} -5'", "make all"),
        ],
    )
    def test_expensive_producer_is_blocked_and_named(self, command: str, producer: str) -> None:
        assert _matches(command) is True
        assert _producer(command) == producer

    def test_pipe_after_the_quote_is_judged_on_the_wrapper(self) -> None:
        assert _matches(f"bash -c 'pytest tests' | {_TAIL} -3") is True

    def test_a_cheap_body_does_not_launder_a_pipe_after_the_quote(self) -> None:
        assert _matches(f"bash -c 'grep x f' | {_TAIL} -3") is True

    @pytest.mark.parametrize(
        "command",
        [
            f"echo bash -c 'pytest | {_TAIL} -1'",
            f"printf '%s' sh -c 'pytest | {_TAIL}'",
            f"grep -c 'sh -c ' f | {_TAIL} -3",
        ],
    )
    def test_a_shell_word_that_is_only_an_argument_opens_no_program(self, command: str) -> None:
        """Main judged these on `echo`/`printf` (allowed); that is unchanged."""
        assert _matches(command) is False


class TestShellAtACommandPosition:
    @pytest.mark.parametrize(
        "command",
        [
            f"/bin/bash -c 'pytest | {_TAIL} -1'",
            f"/usr/bin/env bash -c 'pytest | {_TAIL} -1'",
            f"sudo -u u bash -c 'pytest | {_TAIL} -1'",
            f"FOO=1 bash -c 'pytest | {_TAIL} -1'",
            f"cd /w && bash -c 'pytest | {_TAIL} -1'",
        ],
    )
    def test_expensive_producer_blocked(self, command: str) -> None:
        assert _matches(command) is True
        assert _producer(command) == "pytest"

    @pytest.mark.parametrize(
        "command",
        [
            f"/bin/bash -c 'grep x f | {_TAIL} -1'",
            f"/usr/bin/env bash -c 'grep x f | {_TAIL} -1'",
            f"FOO=1 bash -c 'grep x f | {_TAIL} -1'",
        ],
    )
    def test_cheap_producer_allowed(self, command: str) -> None:
        assert _matches(command) is False

    def test_double_quoted_body_is_unchanged(self) -> None:
        assert _matches(f'bash -c "grep x f | sort | {_TAIL} -n 2"') is False
        assert _matches(f'bash -c "pytest tests | {_TAIL} -3"') is True
