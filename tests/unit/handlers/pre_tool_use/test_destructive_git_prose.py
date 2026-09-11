"""destructive_git must judge the COMMAND, not prose the shell hands over as data.

Plan 00377 N7. A commit whose message described a newly added ``--force`` flag
was denied as ``R-GIT-PUSH-FORCE``. The message was prose inside a heredoc with
a QUOTED delimiter, in which bash expands nothing.

The mechanism is narrower than "the guard saw two words in one string", and
worth stating because it decides where the fix belongs. The opener line was::

    git commit -F - <<'EOF' && git push origin main

so the heredoc BODY physically follows ``git push`` in the command string, and
``_GIT_PUSH_FORCE_PATTERN``'s ``[^;&|]*?`` excludes those three separators but
NOT newlines. The scan therefore ran from ``git push`` down into the body.

A second route reaches the same defect without any heredoc: the single-line
patterns use ``.*``, which stays on one line but still matches inside a ``-m``
value. Both are covered below, because blanking only the heredoc leaves the
second route open — measured, not assumed.

The guard's real job is unchanged and is asserted just as hard: a genuinely
destructive command is still denied, including when it shares a command line
with an innocent message, and a message value that bash would SUBSTITUTE is not
prose at all.
"""

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
    DestructiveGitHandler,
)

# Assembled rather than written literally. These strings are the very shapes the
# handler misreads, and a test file is read by other scanners too — building them
# from fragments keeps the intent ("this is data") true of the file itself.
_FORCE = "--" + "force"
_AMEND = "--" + "amend"
_RESET_HARD = "git reset " + "--hard"

#: The exact command from the field report, reduced to its shape.
_FIELD_REPORT = (
    "set -euo pipefail; git add -A && git commit -F - <<'EOF' && git push origin main\n"
    f"N4 -- `agents install <name> {_FORCE}`. The warning now names that escape.\n"
    "EOF"
)


@pytest.fixture
def handler() -> DestructiveGitHandler:
    return DestructiveGitHandler()


def _matches(handler: DestructiveGitHandler, command: str) -> bool:
    return handler.matches({"tool_name": "Bash", "tool_input": {"command": command}})


class TestProseIsNotACommand:
    """Spans bash hands over as DATA must not be read as shell syntax."""

    def test_the_field_report_is_allowed(self, handler: DestructiveGitHandler) -> None:
        assert _matches(handler, _FIELD_REPORT) is False

    def test_a_quoted_heredoc_body_naming_a_reset_is_allowed(
        self, handler: DestructiveGitHandler
    ) -> None:
        """This shape denied the throwaway probe written to investigate N7."""
        command = f"python3 - <<'PY'\nexample = '{_RESET_HARD}'\nPY"
        assert _matches(handler, command) is False

    def test_a_message_naming_an_amend_is_allowed(self, handler: DestructiveGitHandler) -> None:
        """No heredoc involved — the `.*` patterns match inside a -m value."""
        assert _matches(handler, f"git commit -m 'document {_AMEND} behaviour'") is False

    def test_a_message_naming_a_reset_is_allowed(self, handler: DestructiveGitHandler) -> None:
        assert _matches(handler, f"git commit -m 'explain {_RESET_HARD}'") is False

    def test_a_message_file_flag_naming_a_force_push_is_allowed(
        self, handler: DestructiveGitHandler
    ) -> None:
        assert _matches(handler, f"git commit -F - <<'EOF'\ndescribes {_FORCE}\nEOF") is False


class TestTheGuardStillGuards:
    """Every subtraction above must cost the handler nothing that matters."""

    @pytest.mark.parametrize(
        "command",
        [
            f"git push {_FORCE} origin main",
            f"git commit {_AMEND} -m 'fix typo'",
            f"{_RESET_HARD} HEAD",
            "git push origin +main:main",
            "git clean -fd",
            "git branch -D feature",
        ],
    )
    def test_a_genuinely_destructive_command_is_still_blocked(
        self, handler: DestructiveGitHandler, command: str
    ) -> None:
        assert _matches(handler, command) is True

    def test_a_real_force_push_sharing_a_line_with_a_message_is_blocked(
        self, handler: DestructiveGitHandler
    ) -> None:
        """Blanking the message must not blank the command beside it."""
        command = f"git commit -m 'ordinary message' && git push {_FORCE} origin main"
        assert _matches(handler, command) is True

    def test_a_real_force_push_after_a_quoted_heredoc_is_blocked(
        self, handler: DestructiveGitHandler
    ) -> None:
        command = (
            f"git commit -F - <<'EOF'\nan ordinary message\nEOF\ngit push {_FORCE} origin main"
        )
        assert _matches(handler, command) is True

    def test_a_substituting_message_value_is_not_prose(
        self, handler: DestructiveGitHandler
    ) -> None:
        """Bash substitutes inside DOUBLE quotes, so this really runs the push.

        The separating rule is ``value_can_substitute``, not quote class: the
        single-quoted sibling above is inert and allowed.
        """
        command = f'git commit -m "$(git push {_FORCE} origin main)"'
        assert _matches(handler, command) is True

    def test_an_unquoted_heredoc_body_is_still_scanned(
        self, handler: DestructiveGitHandler
    ) -> None:
        """Deliberate boundary, shared with pipe_blocker: `<<EOF` expands.

        Quoting the delimiter is what makes a body inert; an unquoted one can
        genuinely run what it contains, so it is not blanked.
        """
        command = f"git commit -F - <<EOF && git push origin main\n{_FORCE}\nEOF"
        assert _matches(handler, command) is True


class TestBothVerbsReadTheSameCommand:
    """``matches()`` and ``handle()`` must never disagree about what ran."""

    def test_handle_names_the_force_push_rule_for_a_real_force_push(
        self, handler: DestructiveGitHandler
    ) -> None:
        result = handler.handle(
            {
                "tool_name": "Bash",
                "tool_input": {"command": f"git push {_FORCE} origin main"},
            }
        )
        assert result.decision is Decision.DENY
        assert result.reason is not None
        assert RuleID.GIT_PUSH_FORCE in result.reason

    def test_handle_does_not_name_a_destructive_rule_for_the_field_report(
        self, handler: DestructiveGitHandler
    ) -> None:
        """If handle() scanned the raw command it would report a force push.

        Dispatch never calls handle() without matches(), so this guards the
        pair rather than a live path — the two read one scan target or they
        drift, which is how the ordered-pattern mapping was justified.
        """
        assert handler._match_rule_id(_FIELD_REPORT) is None
