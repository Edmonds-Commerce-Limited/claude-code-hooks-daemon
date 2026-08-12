"""Plan 00222: a message VALUE is inert only while the shell will not run it.

`pipe_blocker` blanks the value of `-m`/`--message`/`-F`/`--file` before it
scans for pipes, so that prose in a commit message which happens to contain the
literal characters of a pipe-to-pager is not mistaken for one. Plan 00200 added
that, and it was right — `tests/.../test_pipe_blocker_comprehensive.py`
(`TestPipeBlockerMessageBodyFalsePositive`) holds the cases it fixed, and every
one of them must keep passing.

The blanking is too broad in two independent ways.

**It hides an executing pipe.** The shell performs command substitution inside
DOUBLE quotes, so `git commit -m "$(pytest tests/ | tail -1)"` genuinely runs
pytest and pipes it. Blanking the whole value makes that invisible. The daemon
already knows this fact in another handler — `git_message_backtick` exists
*because* double quotes execute — so today two handlers in one codebase
disagree about the shell.

**It misreads an unrelated flag.** `-m` means "module" to python. Nothing
scopes the pattern to commands that actually take a message, so
`python -m pytest tests/ | tail -5` blocks correctly but reports its producer
as the redaction placeholder, and the remediation the block prints is not
runnable.

The discriminator is NOT the quote class. A quote-class rule ("blank only
single-quoted values") was tried first and rejected here: it would have
re-broken Plan 00200's deliberate double-quoted prose cases, where no `$(` or
backtick appears and the shell really does execute nothing. What separates the
cases is whether the value contains a COMMAND SUBSTITUTION.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler

# Built at runtime so this module never contains the literal characters of a
# pipe-to-pager outside a test payload — writing this file would otherwise be
# denied by the very handler it tests.
PIPE = chr(124)
TO_TAIL = f" {PIPE} tail -1"
TO_TAIL_20 = f" {PIPE} tail -20"
TO_HEAD = f" {PIPE} head -5"


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def _reason(handler: PipeBlockerHandler, command: str) -> str:
    """The block reason as text — `HookResult.reason` is optional by type."""
    return handler.handle(_bash(command)).reason or ""


@pytest.fixture
def handler() -> PipeBlockerHandler:
    return PipeBlockerHandler()


class TestSubstitutionInsideAMessageIsNotInert:
    """Double quotes do not stop the shell — they only stop word splitting."""

    def test_dollar_paren_in_a_commit_message_is_blocked(self, handler: PipeBlockerHandler) -> None:
        """`git commit -m "$(pytest ... | tail -1)"` RUNS pytest.

        This is the bypass. The value looks like a message and is treated as
        prose, but bash expands the substitution before git ever sees it, so an
        expensive producer executes and its output is truncated — exactly what
        this handler exists to prevent.
        """
        command = f'git commit -m "$(pytest tests/{TO_TAIL})"'
        assert handler.matches(_bash(command)) is True

    def test_backtick_in_a_commit_message_is_blocked(self, handler: PipeBlockerHandler) -> None:
        """Backticks substitute inside double quotes too.

        `git_message_backtick` blocks this shape for the CORRUPTION it causes;
        this handler must independently see the pipe, because the two handlers
        can be configured and disabled separately.
        """
        command = f'git commit -m "result: `pytest tests/{TO_TAIL}`"'
        assert handler.matches(_bash(command)) is True

    def test_substitution_in_a_tag_message_is_blocked(self, handler: PipeBlockerHandler) -> None:
        """`git tag -m` carries the same hazard as `git commit -m`."""
        command = f'git tag -a v1.0.0 -m "$(pytest tests/{TO_TAIL})"'
        assert handler.matches(_bash(command)) is True

    def test_long_flag_form_is_blocked_too(self, handler: PipeBlockerHandler) -> None:
        """`--message` must not be a way around the short-flag handling."""
        command = f'git commit --message "$(pytest tests/{TO_TAIL})"'
        assert handler.matches(_bash(command)) is True

    def test_whitelisted_producer_inside_a_message_stays_allowed(
        self, handler: PipeBlockerHandler
    ) -> None:
        """Control. Scanning the value must not mean blocking every value.

        A substitution whose producer is cheap is fine — the decision still
        belongs to the whitelist, not to the mere presence of a substitution.
        """
        command = f'git commit -m "$(git log --format=%H{TO_TAIL})"'
        assert handler.matches(_bash(command)) is False


class TestSingleQuotesRemainInertUnconditionally:
    """The shell performs no substitution inside single quotes, ever."""

    def test_single_quoted_prose_with_a_pipe_is_allowed(self, handler: PipeBlockerHandler) -> None:
        command = f"git commit -m 'documented that pytest{TO_TAIL_20} is blocked'"
        assert handler.matches(_bash(command)) is False

    def test_single_quoted_dollar_paren_is_literal_text(self, handler: PipeBlockerHandler) -> None:
        """`'$(pytest | tail)'` is eight-and-a-bit characters of text, not a command.

        This is the case a naive "does the value contain `$(`?" check would get
        wrong, so it is pinned separately from the prose case above.
        """
        command = f"git commit -m 'literally: $(pytest tests/{TO_TAIL})'"
        assert handler.matches(_bash(command)) is False


class TestMessageFlagIsScopedToCommandsThatTakeOne:
    """`-m` means "module" to python and "message" to git."""

    def test_python_dash_m_names_its_real_producer(self, handler: PipeBlockerHandler) -> None:
        """The block is already correct; the REASON is not.

        Reporting the producer as the redaction placeholder hands the caller a
        remediation command they cannot run, on one of the most common
        invocations in this repository.
        """
        command = f"python -m pytest tests/{TO_TAIL}"
        assert handler.matches(_bash(command)) is True
        reason = _reason(handler, command)
        assert "pytest" in reason
        assert "REDACTED" not in reason

    def test_python3_dash_m_is_treated_the_same(self, handler: PipeBlockerHandler) -> None:
        command = f"python3 -m pytest tests/{TO_HEAD}"
        assert "REDACTED" not in _reason(handler, command)

    def test_a_whitelisted_command_carrying_dash_m_is_still_allowed(
        self, handler: PipeBlockerHandler
    ) -> None:
        """Control: scoping the flag must not turn every `-m` into a block.

        `ps -m` is a real ps flag (show threads). ps is whitelisted, so the
        only way this blocks is if the scoping change made `-m` significant on
        a command that has nothing to do with messages.
        """
        command = f"ps -m -o pid,comm{TO_HEAD}"
        assert handler.matches(_bash(command)) is False


class TestPlan00200FalsePositivesStayFixed:
    """Regression lock. These are the cases the redaction was added FOR.

    Held here as well as in their original file because Plan 00222 changes the
    mechanism underneath them: a fix that closes the bypass by re-breaking
    these has fixed nothing, and this is where that would show up first.
    """

    def test_double_quoted_prose_without_substitution_is_allowed(
        self, handler: PipeBlockerHandler
    ) -> None:
        command = f'git commit -m "See: pytest tests/ 2>&1{TO_TAIL_20} is now blocked"'
        assert handler.matches(_bash(command)) is False

    def test_double_quoted_prose_with_head_is_allowed(self, handler: PipeBlockerHandler) -> None:
        command = f'git commit --message "example: docker ps{TO_HEAD}"'
        assert handler.matches(_bash(command)) is False

    def test_heredoc_message_idiom_is_allowed(self, handler: PipeBlockerHandler) -> None:
        """The repo's own multi-line commit idiom.

        This one DOES contain a substitution, so the fix cannot special-case it
        away — it has to fall out of producer attribution instead. The inner
        producer is `cat`, which is whitelisted, and that is why it is allowed.
        """
        command = (
            "git commit -m \"$(cat <<'EOF'\n"
            "Fix: something\n"
            "\n"
            f"Previously we ran pytest tests/{TO_TAIL_20} which truncated output.\n"
            "EOF\n"
            ')"'
        )
        assert handler.matches(_bash(command)) is False

    def test_a_real_pipe_after_a_message_flag_is_still_blocked(
        self, handler: PipeBlockerHandler
    ) -> None:
        command = f'git commit -m "fix" && pytest tests/{TO_TAIL_20}'
        assert handler.matches(_bash(command)) is True
