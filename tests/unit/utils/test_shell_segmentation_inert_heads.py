"""``is_wholly_inert_command`` -- the inert-head exemption.

Plan 00408 Task 3.3, graduated from Plan 00407 N12. ``echo 'git merge x'`` and
``bash -c 'git merge x'`` are structurally identical -- a command with a quoted
argument -- so nothing in the TEXT separates them. Only knowing that ``echo``
does not EXECUTE its argument does, which is an allowlist of command heads.

The exemption is deliberately WHOLE-COMMAND. A per-segment version was built
first and a review walked past it three ways (an escaped ``#``, ``$_``, and a
``trap``/``BASH_ALIASES`` rebinding), each through a later segment. Every bash
feature that reaches across segments is another such bypass, so the predicate
now answers only for one simple command with nothing around it, and every
other command is judged exactly as it was before the exemption existed.
"""

import pytest

from claude_code_hooks_daemon.utils.shell_segmentation import (
    INERT_COMMAND_HEADS,
    is_wholly_inert_command,
)
from tests.scaling import SIZE_FACTOR, SUPERLINEAR_RATIO, scaling_ratio
from tests.support.inert_head_shapes import (
    INERT_SHAPES,
    NOT_INERT_SHAPES,
    REVIEW_SHAPES,
    STILL_JUDGED_SHAPES,
    fill,
)

_MERGE = "git merge feature/x"


class TestTheAllowlistItself:
    def test_the_four_inert_heads_and_nothing_else(self) -> None:
        assert frozenset({"echo", "printf", ":", "true"}) == INERT_COMMAND_HEADS


class TestOneBareInertCommandIsInert:
    @pytest.mark.parametrize("template", INERT_SHAPES)
    def test_the_shape_is_inert(self, template: str) -> None:
        assert is_wholly_inert_command(fill(template, _MERGE)) is True

    @pytest.mark.parametrize("head", sorted(INERT_COMMAND_HEADS))
    def test_each_head_is_inert(self, head: str) -> None:
        assert is_wholly_inert_command(f"{head} '{_MERGE}'") is True


class TestEverythingElseIsNot:
    """The DENY-preservation matrix: none of these reaches the exemption."""

    @pytest.mark.parametrize("template", NOT_INERT_SHAPES)
    def test_the_shape_is_not_inert(self, template: str) -> None:
        assert is_wholly_inert_command(fill(template, _MERGE)) is False

    def test_the_review_and_still_judged_lists_are_carried(self) -> None:
        """The round-1 review's shapes are part of the matrix, not beside it."""
        assert set(REVIEW_SHAPES) | set(STILL_JUDGED_SHAPES) <= set(NOT_INERT_SHAPES)

    @pytest.mark.parametrize("command", ["", "   ", "echo", "echo\t", "true", "ls 'x'"])
    def test_no_argument_or_no_inert_head_is_not_inert(self, command: str) -> None:
        """Nothing to exempt: the head must be followed by a blank and more text."""
        assert is_wholly_inert_command(command) is False

    @pytest.mark.parametrize("head", ["echox", "printf2", "::", "trueish", "Echo"])
    def test_a_head_is_matched_as_a_whole_word(self, head: str) -> None:
        assert is_wholly_inert_command(f"{head} '{_MERGE}'") is False

    @pytest.mark.parametrize("char", list(";&|\n\r()<>{}`$~*?[!"))
    def test_each_refused_unquoted_character(self, char: str) -> None:
        """One character per refusal, so dropping any one of them turns RED."""
        assert is_wholly_inert_command(f"echo a{char}b '{_MERGE}'") is False

    @pytest.mark.parametrize("char", ["$", "`", "!"])
    def test_each_refused_double_quoted_character(self, char: str) -> None:
        assert is_wholly_inert_command(f"echo \"a{char}b\" '{_MERGE}'") is False

    @pytest.mark.parametrize("char", list(';&|()<>{}`$~*?[!#"'))
    def test_single_quotes_make_every_character_literal(self, char: str) -> None:
        assert is_wholly_inert_command(f"echo 'a{char}b' '{_MERGE}'") is True

    @pytest.mark.parametrize("char", list(";&|()<>{}`$~*?[!#'\"\\"))
    def test_a_backslash_makes_the_next_character_literal(self, char: str) -> None:
        assert is_wholly_inert_command(f"echo a\\{char}b '{_MERGE}'") is True

    def test_an_embedded_nul_is_not_inert(self) -> None:
        """A NUL inside the argument is not a character bash treats as literal
        text in any useful sense -- withhold the exemption rather than assume
        it behaves like an ordinary byte."""
        assert is_wholly_inert_command(f"echo x\x00; {_MERGE}") is False

    @pytest.mark.parametrize("option", ["-v", '-"v"', "-'v'", "-\\v", "--", "-x"])
    def test_printf_takes_no_option(self, option: str) -> None:
        assert is_wholly_inert_command(f"printf {option} x '{_MERGE}'") is False

    @pytest.mark.parametrize("option", ["-v", "-e", "-n", "-E"])
    def test_echo_options_only_shape_output(self, option: str) -> None:
        assert is_wholly_inert_command(f"echo {option} '{_MERGE}'") is True


class TestTheScanStaysLinear:
    """This module's scans have gone quadratic before (Plan 00466 N25)."""

    @pytest.mark.parametrize("unit", ["'git merge x' ", 'a\\;b "c\\$d" '])
    def test_cost_grows_linearly_with_argument_count(self, unit: str) -> None:
        count = 2000

        def work_at(size: int) -> bool:
            return is_wholly_inert_command("echo " + unit * size)

        ratio = scaling_ratio(work_at, count, "echo " + unit * (SIZE_FACTOR * count))
        assert ratio < SUPERLINEAR_RATIO, f"{ratio:.0f}x for {SIZE_FACTOR}x arguments"
