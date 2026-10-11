"""The `sh -c` head strip in pip_break_system must stay linear on a long word.

An unanchored `(?:\\S*/)?` prefix is retried from every offset inside one
whitespace-free run, so `$($($(...` nested a few thousand deep cost O(n^2).
"""

from __future__ import annotations

import re
import time

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.pip_break_system import (
    _SHELL_C_HEAD,
    _leading_assignment,
)

#: The pattern as it was before the run-start anchor; the anchored one must
#: strip exactly the same span on every input.
_UNANCHORED = re.compile(r"(?:\S*/)?(?:ba|da|z)?sh\s+-\w*c\s+['\"]?\s*")


class TestShellCHeadSemantics:
    """Anchoring the prefix at a run start must not change what is stripped."""

    @pytest.mark.parametrize(
        "text",
        [
            "bash -c 'pip install x'",
            "/bin/bash -c pip install x",
            "echo /usr/bin/zsh -lc 'a'",
            "a/b sh -c x",
            "q/sh -c y",
            "xsh/ssh -c y",
            "ssh -c aes host",
            'a/b/c/dash -c "pip install"',
            "no shell here",
            "",
            "$(" * 20 + "sh -c x" + ")" * 20,
            "$(/bin/sh -c x)",
        ],
    )
    def test_strips_same_span_as_unanchored_pattern(self, text: str) -> None:
        """Same result as the pre-anchor pattern."""
        assert _SHELL_C_HEAD.sub("", text, count=1) == _UNANCHORED.sub("", text, count=1)

    def test_path_prefixed_shell_is_removed_with_its_path(self) -> None:
        """The path is part of the stripped head."""
        assert _SHELL_C_HEAD.sub("", "/bin/bash -c pip install x", count=1) == "pip install x"


class TestShellCHeadLinear:
    """Cost grows linearly with the length of a single long word."""

    @staticmethod
    def _cost(depth: int) -> float:
        word = "$(" * depth + "true" + ")" * depth
        best = float("inf")
        for _ in range(3):
            start = time.perf_counter()
            _leading_assignment(word)
            best = min(best, time.perf_counter() - start)
        return best

    def test_long_substitution_word_is_not_quadratic(self) -> None:
        """8x the input must cost far less than the 64x a quadratic scan would."""
        small = self._cost(1_000)
        large = self._cost(8_000)
        assert large < max(small, 1e-4) * 24
