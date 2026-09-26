"""``blank_inert_command_arguments`` -- the inert-head allowlist.

Plan 00408 Task 3.3, graduated from Plan 00407 N12. ``echo 'git merge x'`` and
``bash -c 'git merge x'`` are structurally identical -- a command with a quoted
argument -- so nothing in the TEXT separates them. Only knowing that ``echo``
does not EXECUTE its argument does, which is an allowlist of command heads.

An allowlist, per N7's rule: a missing entry costs a false positive, a wrong
entry costs a guard. So every shape that COULD reach an executor keeps its
text, and only the plain, bare, unpiped, unredirected inert head loses it.
"""

import pytest

from claude_code_hooks_daemon.utils.shell_segmentation import (
    INERT_COMMAND_HEADS,
    blank_inert_command_arguments,
)
from tests.scaling import SIZE_FACTOR, SUPERLINEAR_RATIO, scaling_ratio
from tests.support.inert_head_shapes import ESCAPE_SHAPES, INERT_SHAPES, fill

_MERGE = "git merge feature/x"


class TestTheAllowlistItself:
    def test_the_four_inert_heads_and_nothing_else(self) -> None:
        assert frozenset({"echo", "printf", ":", "true"}) == INERT_COMMAND_HEADS


class TestAnInertHeadLosesItsArguments:
    @pytest.mark.parametrize("template", INERT_SHAPES)
    def test_the_argument_is_blanked(self, template: str) -> None:
        assert _MERGE not in blank_inert_command_arguments(fill(template, _MERGE))

    def test_an_unquoted_argument_is_blanked_too(self) -> None:
        assert _MERGE not in blank_inert_command_arguments(f"echo {_MERGE}")

    def test_the_head_and_the_length_survive(self) -> None:
        """Offsets are kept so a caller re-slicing the result stays aligned."""
        command = f"echo '{_MERGE}'"
        blanked = blank_inert_command_arguments(command)
        assert blanked.startswith("echo")
        assert len(blanked) == len(command)

    def test_a_command_with_no_inert_head_is_returned_unchanged(self) -> None:
        command = f"ls && {_MERGE}"
        assert blank_inert_command_arguments(command) == command

    def test_a_bare_head_with_no_arguments_is_unchanged(self) -> None:
        assert blank_inert_command_arguments("echo") == "echo"
        assert blank_inert_command_arguments("") == ""


class TestEveryEscapeShapeKeepsItsText:
    """The DENY-preservation matrix: each of these can run the named command."""

    @pytest.mark.parametrize("template", ESCAPE_SHAPES)
    def test_the_command_text_survives(self, template: str) -> None:
        assert _MERGE in blank_inert_command_arguments(fill(template, _MERGE))


class TestTheScanStaysLinear:
    """This module's scans have gone quadratic before (Plan 00466 N25).

    Blanking segment by segment with a fresh slice of the whole command per
    segment is the shape that did it, so the two inputs below are the ones
    that would expose it: many exempt segments, and many that are not.
    """

    @pytest.mark.parametrize(
        "segment",
        [f"echo '{_MERGE}'; ", f"ls -la '{_MERGE}' && "],
    )
    def test_cost_grows_linearly_with_segment_count(self, segment: str) -> None:
        segments = 2000

        def work_at(count: int) -> str:
            return blank_inert_command_arguments(segment * count)

        ratio = scaling_ratio(work_at, segments, segment * (SIZE_FACTOR * segments))
        assert ratio < SUPERLINEAR_RATIO, f"{ratio:.0f}x for {SIZE_FACTOR}x segments"
