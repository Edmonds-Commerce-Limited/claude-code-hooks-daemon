"""``strip_inert_spans`` must be near-linear in command length (Plan 00466 N25).

The guard-defects security review 2 measured ``destructive_git`` (which calls
``strip_inert_spans`` on every command) at 99s on a 200 KB ``git commit``
carrying 40000 repeated ``-m x`` flags, and 98s on a 200 KB command carrying
5000 quoted-delimiter heredocs — both from a single top-level command with NO
chain separator, so every one of those matches shared the same top-level
segment.

The root cause in each case was the same shape: a per-match helper re-derived
information about the segment PRECEDING the match by slicing or rescanning
``command[:match_start]`` — a slice/scan whose cost grows with the match's
position — instead of computing it incrementally as matches are visited in
their guaranteed left-to-right order. With one slow helper called once per
match, and match count roughly proportional to command length, the total cost
was quadratic.

Each shape is pinned by GROWTH: its CPU cost at the review's size against the
cost at an eighth of it (``tests/scaling.py``). A wall-clock bound failed
under host load while passing alone, and said nothing about growth (00466
N222).
"""

from collections.abc import Callable

import pytest

from claude_code_hooks_daemon.utils.heredoc_operators import scan_heredocs
from claude_code_hooks_daemon.utils.shell_segmentation import (
    heredoc_consumers,
    known_variables,
    no_earlier_segment_may_rebind,
    strip_inert_spans,
    strip_message_bodies,
    strip_quoted_heredoc_bodies,
)
from tests.scaling import SIZE_FACTOR, SUPERLINEAR_RATIO, scaling_ratio

_FORCE = "--" + "force"


def _assert_grows_linearly(
    strip: Callable[[str], object], command_at: Callable[[int], str], large_n: int
) -> None:
    small_n = large_n // SIZE_FACTOR
    ratio = scaling_ratio(
        lambda n: strip(command_at(n)), small_n, command_at(SIZE_FACTOR * small_n)
    )
    assert ratio <= SUPERLINEAR_RATIO, f"cost grew {ratio:.0f}x for {SIZE_FACTOR}x input"


def _message_flags(count: int) -> str:
    return "git commit " + "-m x " * count


def _quoted_heredocs(count: int) -> str:
    return "git commit -F - <<'EOF'\nx\nEOF\n" * count


def _both_shapes(count: int) -> str:
    return "git commit " + "-m x " * (count * 8) + " && " + ("cat -F - <<'EOF'\nx\nEOF\n" * count)


class TestManyRepeatedMessageFlagsAreLinear:
    """The `strip_message_bodies` half: review 2's 99s repro."""

    def test_40000_repeated_dash_m_flags_in_one_segment(self) -> None:
        result = strip_message_bodies(_message_flags(40_000))

        # Still correct, not just fast: every flag's value was blanked.
        assert "x" not in result
        assert result.count("-m") == 40_000
        _assert_grows_linearly(strip_message_bodies, _message_flags, 40_000)

    def test_a_protected_string_in_the_last_of_40000_messages_is_still_blanked(
        self,
    ) -> None:
        """Correctness at the position quadratic cost would hide worst: the END."""
        command = "git commit " + "-m x " * 39_999 + f"-m '{_FORCE}'"
        result = strip_message_bodies(command)
        assert _FORCE not in result


class TestManyQuotedHeredocsAreLinear:
    """The `strip_quoted_heredoc_bodies` half: review 2's 98s repro."""

    def test_5000_quoted_delimiter_heredocs_in_one_command(self) -> None:
        """No ``git commit`` can rebind a command name (N214), so every body
        stays blankable (Plan 00466 N101 round 13)."""
        result = strip_quoted_heredoc_bodies(_quoted_heredocs(5_000))

        assert result.count("HEREDOC_BODY") == 5_000
        assert "\nx\n" not in result
        _assert_grows_linearly(strip_quoted_heredoc_bodies, _quoted_heredocs, 5_000)

    def test_a_protected_string_in_the_last_of_5000_heredoc_bodies_is_still_blanked(
        self,
    ) -> None:
        command = "cat <<'EOF'\nx\nEOF\n" * 4_999 + (f"git commit -F - <<'EOF'\n{_FORCE}\nEOF\n")
        result = strip_quoted_heredoc_bodies(command)
        assert _FORCE not in result


class TestStripInertSpansCombinedIsLinear:
    """`strip_inert_spans` composes both halves; pin the combination too."""

    def test_200kb_command_mixing_both_shapes(self) -> None:
        assert strip_inert_spans(_both_shapes(2_500))
        _assert_grows_linearly(strip_inert_spans, _both_shapes, 2_500)


class TestRoundTwelveHelpersAreLinear:
    """Plan 00466 N101 round 12: ``known_variables``, the N214 inert prefix
    and ``heredoc_consumers`` scale linearly. A per-statement regex that ran
    to the end of the text made 40,000 assignment statements hang."""

    @pytest.mark.parametrize(
        "build",
        [
            lambda n: "a=b; " * n + 'cat > "$a"',
            lambda n: "".join(f"a{index}=b; " for index in range(n)) + "x",
            lambda n: "echo x; " * n,
            lambda n: "cat <<'EOF'\nx\nEOF\n" * n,
            lambda n: "$PY <<'EOF'\nx\nEOF\n" * n,
            lambda n: "echo $(date) \"$(x `y`)\" 'q'; " * n,
            lambda n: "echo " + "$(x " * n + ")" * n,
            lambda n: "cat <<E\n$HOME\nE\n" * n,
            lambda n: "true" + "\n" * (8 * n),
            lambda n: "true;" + " \t" * (8 * n) + "x",
            lambda n: "echo " + "'" * (8 * n),
        ],
        ids=[
            "assignments",
            "distinct-names",
            "commands",
            "heredocs",
            "variable-receivers",
            "substitutions",
            "nested-substitutions",
            "unquoted-heredocs",
            "newline-run",
            "blank-run",
            "quote-run",
        ],
    )
    @pytest.mark.parametrize(
        "fn",
        [
            known_variables,
            lambda command: no_earlier_segment_may_rebind(command, len(command)),
            lambda command: heredoc_consumers(command, scan_heredocs(command).heredocs),
        ],
        ids=["known_variables", "no_earlier_segment_may_rebind", "heredoc_consumers"],
    )
    def test_the_cost_grows_linearly(
        self, fn: Callable[[str], object], build: Callable[[int], str]
    ) -> None:
        _assert_grows_linearly(fn, build, 400 * SIZE_FACTOR)
