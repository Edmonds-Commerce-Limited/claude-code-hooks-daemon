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

The client's own daemon dispatch socket times out at 30s (Plan 00466 N25);
this pins each shape at a small constant multiple of what a genuinely linear
scan of 200 KB costs on this hardware, which is nowhere close.
"""

import time

from claude_code_hooks_daemon.utils.shell_segmentation import (
    strip_inert_spans,
    strip_message_bodies,
    strip_quoted_heredoc_bodies,
)

# Generous relative to a genuinely linear scan of 200 KB (milliseconds), but
# far below both the 99s/98s quadratic measurements and the 30s client
# timeout -- any regression back to quadratic blows well past this on a
# 200 KB input.
_MAX_SECONDS = 3.0

_FORCE = "--" + "force"


def _timed(fn, command: str) -> tuple[str, float]:
    start = time.perf_counter()
    result = fn(command)
    return result, time.perf_counter() - start


class TestManyRepeatedMessageFlagsAreLinear:
    """The `strip_message_bodies` half: review 2's 99s repro."""

    def test_40000_repeated_dash_m_flags_in_one_segment(self) -> None:
        command = "git commit " + "-m x " * 40_000
        result, elapsed = _timed(strip_message_bodies, command)

        assert elapsed < _MAX_SECONDS, f"took {elapsed:.2f}s, expected well under {_MAX_SECONDS}s"
        # Still correct, not just fast: every flag's value was blanked.
        assert "x" not in result
        assert result.count("-m") == 40_000

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
        command = "git commit -F - <<'EOF'\nx\nEOF\n" * 5_000
        result, elapsed = _timed(strip_quoted_heredoc_bodies, command)

        assert elapsed < _MAX_SECONDS, f"took {elapsed:.2f}s, expected well under {_MAX_SECONDS}s"
        assert result.count("HEREDOC_BODY") == 5_000
        assert "\nx\n" not in result

    def test_a_protected_string_in_the_last_of_5000_heredoc_bodies_is_still_blanked(
        self,
    ) -> None:
        command = "git commit -F - <<'EOF'\nx\nEOF\n" * 4_999 + (
            f"git commit -F - <<'EOF'\n{_FORCE}\nEOF\n"
        )
        result = strip_quoted_heredoc_bodies(command)
        assert _FORCE not in result


class TestStripInertSpansCombinedIsLinear:
    """`strip_inert_spans` composes both halves; pin the combination too."""

    def test_200kb_command_mixing_both_shapes(self) -> None:
        command = "git commit " + "-m x " * 20_000 + " && " + ("cat -F - <<'EOF'\nx\nEOF\n" * 2_500)
        result, elapsed = _timed(strip_inert_spans, command)

        assert elapsed < _MAX_SECONDS, f"took {elapsed:.2f}s, expected well under {_MAX_SECONDS}s"
        assert result
