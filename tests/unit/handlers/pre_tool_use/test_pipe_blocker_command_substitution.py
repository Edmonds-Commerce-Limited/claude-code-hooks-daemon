"""Plan 00221: a pipe inside a command substitution belongs to the INNER command.

`pipe_blocker` finds the pipe, then reads the PRODUCER — the command whose
output is being truncated — and classifies that producer. Producer extraction
takes the text to the left of the pipe and keeps the last chain segment, which
is correct at the top level and wrong inside a command substitution: the text
to the left then starts with the OUTER command, so the OUTER command is what
gets classified.

That is a laundering route, not a cosmetic mis-label. `echo` is whitelisted
because echoing is cheap, so `echo $(pytest tests/ | head -1)` was ALLOWED
while the command actually being truncated was `pytest`. Any expensive command
can be wrapped this way. Confirmed against the live daemon through the
production forwarder before these tests were written.

Two of the four substitution shapes already denied before this fix, but by
accident rather than by understanding: `FOO="$(pytest ... | head -1)"`
extracts `FOO="$(pytest`, which matches no whitelist entry. The decision was
right and the reported producer was wrong, so those blocks named the wrong
command as expensive.

The rule after this fix is the SAME rule, pointed at the right text: classify
the innermost substitution's command. A whitelisted inner producer therefore
stays allowed — correct attribution is not blanket blocking.
"""

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler

# A producer the blacklist already knows is expensive, and one the universal
# whitelist already knows is cheap. Both are pre-existing classifications:
# this plan changes WHICH text is classified, never the classifications.
EXPENSIVE_PRODUCER = "pytest tests/"
WHITELISTED_PRODUCER = "git log --format=%H"


def _bash(command: str) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


# Every way a shell can run a command and substitute its output. A pipe in ANY
# of them is a real pipe with a real producer, so each must classify the INNER
# command. Kept as one table so a shape that goes unhandled fails loudly here
# rather than passing silently — the gap that let `echo $(...)` through was
# precisely a shape nothing asserted about.
#
# The outer command is deliberately whitelisted (`echo`, `ps`) in the shapes
# where one exists: that is what made the bypass invisible.
SUBSTITUTION_WRAPPERS: tuple[tuple[str, str], ...] = (
    ("dollar-paren argument to a whitelisted command", "echo $({producer} | head -1)"),
    ("dollar-paren in a quoted assignment", 'FOO="$({producer} | head -1)"'),
    ("dollar-paren in a bare assignment", "FOO=$({producer} | head -1)"),
    ("backtick in an assignment", "FOO=`{producer} | head -1`"),
    ("backtick argument to a whitelisted command", "echo `{producer} | head -1`"),
    ("nested dollar-paren", "echo $(echo $({producer} | head -1))"),
    ("substitution inside a longer argument list", "ps -o etime= -p $({producer} | head -1)"),
)


class TestSubstitutionLaunderingIsBlocked:
    """The bypass: a whitelisted outer command hiding an expensive producer."""

    @pytest.mark.parametrize(
        "description,wrapper",
        SUBSTITUTION_WRAPPERS,
        ids=[description for description, _ in SUBSTITUTION_WRAPPERS],
    )
    def test_expensive_producer_is_blocked_in_every_substitution_shape(
        self, description: str, wrapper: str
    ) -> None:
        handler = PipeBlockerHandler()
        command = wrapper.format(producer=EXPENSIVE_PRODUCER)
        assert handler.matches(_bash(command)), f"{description} launders the producer: {command}"

    def test_the_exact_field_shape_is_blocked(self) -> None:
        """The shape probed against the live daemon and found ALLOWED."""
        handler = PipeBlockerHandler()
        assert handler.matches(_bash("echo $(pytest tests/ | head -1)"))


class TestWhitelistedInnerProducerIsStillAllowed:
    """Correct attribution must not become blanket blocking.

    If every substitution simply denied, `$(git log ... | head -1)` — an
    ordinary idiom for taking one value from a cheap, streaming command —
    would break, and the handler would be reaching for the whitelist that
    already exists to answer exactly this question.
    """

    @pytest.mark.parametrize(
        "description,wrapper",
        SUBSTITUTION_WRAPPERS,
        ids=[description for description, _ in SUBSTITUTION_WRAPPERS],
    )
    def test_whitelisted_producer_is_allowed_in_every_substitution_shape(
        self, description: str, wrapper: str
    ) -> None:
        handler = PipeBlockerHandler()
        command = wrapper.format(producer=WHITELISTED_PRODUCER)
        assert not handler.matches(
            _bash(command)
        ), f"{description} wrongly blocks a whitelisted producer: {command}"


class TestTopLevelBehaviourIsUnchanged:
    """Positive controls: the pre-existing rule must survive the change."""

    def test_top_level_expensive_pipe_still_blocked(self) -> None:
        handler = PipeBlockerHandler()
        assert handler.matches(_bash(f"{EXPENSIVE_PRODUCER} | head -1"))

    def test_top_level_whitelisted_pipe_still_allowed(self) -> None:
        handler = PipeBlockerHandler()
        assert not handler.matches(_bash(f"{WHITELISTED_PRODUCER} | head -1"))

    def test_chain_segmentation_still_takes_the_last_segment(self) -> None:
        handler = PipeBlockerHandler()
        assert not handler.matches(_bash("pytest tests/ && git log | head -1"))


class TestEveryPipeInTheCommandIsClassified:
    """The same root cause as substitution laundering: the handler asked its
    questions of the command AS A WHOLE instead of of each pipe.

    `_pipe_pattern.search` returns the FIRST match only, so exactly one pipe
    per command was ever classified. A cheap first pipe therefore shadowed an
    expensive second one, and prefixing anything with `git log | head -1 &&`
    was enough to launder it — no substitution required.

    The `tail -f` / `head -c` exemptions had the identical shape: they were
    searched across the WHOLE command, so appending `&& tail -f /dev/null`
    exempted a pipe that had nothing to do with following a file.
    """

    def test_expensive_second_pipe_is_not_shadowed_by_cheap_first(self) -> None:
        handler = PipeBlockerHandler()
        assert handler.matches(
            _bash(f"{WHITELISTED_PRODUCER} | head -2 && {EXPENSIVE_PRODUCER} | head -1")
        )

    def test_shadowing_also_fails_across_a_semicolon(self) -> None:
        handler = PipeBlockerHandler()
        assert handler.matches(
            _bash(f"{WHITELISTED_PRODUCER} | head -2 ; {EXPENSIVE_PRODUCER} | head -1")
        )

    def test_shadowing_combined_with_substitution_laundering(self) -> None:
        handler = PipeBlockerHandler()
        assert handler.matches(
            _bash(f"{WHITELISTED_PRODUCER} | head -2 && echo $({EXPENSIVE_PRODUCER} | head -1)")
        )

    def test_all_cheap_pipes_are_still_allowed(self) -> None:
        """Positive control: classifying every pipe must not mean denying
        every multi-pipe command."""
        handler = PipeBlockerHandler()
        assert not handler.matches(
            _bash(f"{WHITELISTED_PRODUCER} | head -2 && git status | head -1")
        )

    def test_unrelated_tail_follow_does_not_exempt_an_expensive_pipe(self) -> None:
        """`&& tail -f x` used to disable the handler for the whole command."""
        handler = PipeBlockerHandler()
        assert handler.matches(_bash(f"{EXPENSIVE_PRODUCER} | head -1 && tail -f /var/log/x"))

    def test_unrelated_head_bytes_does_not_exempt_an_expensive_pipe(self) -> None:
        handler = PipeBlockerHandler()
        assert handler.matches(_bash(f"{EXPENSIVE_PRODUCER} | head -1 && head -c 10 /etc/hostname"))

    def test_genuine_tail_follow_pipe_is_still_exempt(self) -> None:
        """The exemption itself is real and must survive: following a stream
        is not truncation, so nothing is lost."""
        handler = PipeBlockerHandler()
        assert not handler.matches(_bash(f"{EXPENSIVE_PRODUCER} | tail -f"))

    def test_genuine_head_bytes_pipe_is_still_exempt(self) -> None:
        handler = PipeBlockerHandler()
        assert not handler.matches(_bash(f"{EXPENSIVE_PRODUCER} | head -c 100"))

    def test_reason_names_the_offending_pipe_not_the_first_one(self) -> None:
        handler = PipeBlockerHandler()
        result = handler.handle(
            _bash(f"{WHITELISTED_PRODUCER} | head -2 && {EXPENSIVE_PRODUCER} | head -1")
        )
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "pytest" in result.reason


class TestNonSubstitutingTextIsInert:
    """Single quotes suppress substitution, so nothing runs and nothing is
    truncated. Blocking there would be blocking a string literal."""

    def test_single_quoted_pipe_text_is_not_a_pipe(self) -> None:
        handler = PipeBlockerHandler()
        assert not handler.matches(_bash("echo 'pytest tests/ | head -1'"))

    def test_single_quoted_dollar_paren_is_not_a_substitution(self) -> None:
        handler = PipeBlockerHandler()
        assert not handler.matches(_bash("echo '$(pytest tests/ | head -1)'"))


class TestBlockMessageNamesTheInnerProducer:
    """The decision was already right for the assignment shapes; the REPORTED
    producer was not. A block that names `FOO="$(pytest` as the expensive
    command tells the agent to whitelist a variable assignment."""

    def test_reason_names_the_inner_producer_not_the_outer_command(self) -> None:
        handler = PipeBlockerHandler()
        result = handler.handle(_bash("echo $(pytest tests/ | head -1)"))
        assert result.decision == Decision.DENY
        assert result.reason is not None
        assert "pytest" in result.reason

    def test_suggested_whitelist_entry_names_the_inner_producer(self) -> None:
        """The suggestion must be a command name. `- "^FOO=\\b"` is not one,
        and whitelisting it would re-open the bypass for every producer
        wrapped the same way.

        Scoped to the SUGGESTION, not the whole message: the `COMMAND:` line
        echoes the original text verbatim and is right to do so — the agent
        needs to see what it actually typed.
        """
        handler = PipeBlockerHandler()
        result = handler.handle(_bash('FOO="$(some_unknown_tool --run | head -1)"'))
        assert result.reason is not None
        assert '"^some_unknown_tool\\\\b"' in result.reason
        assert "^FOO=" not in result.reason
