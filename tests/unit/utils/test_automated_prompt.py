"""Tests for the shared machine-turn prompt test (Plan 00636 Task 2.2)."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.automated_prompt import is_automated_prompt


class TestIsAutomatedPrompt:
    @pytest.mark.parametrize(
        "prompt",
        [
            "**FAILSAFE RECOVERY CHECK (automated hourly safety net ...)**",
            "[tick:watchdog]\n**BACKGROUND WATCHDOG TICK**",
            "[tick:job:issue-sdlc]\n**ISSUE SDLC TICK**",
            "🤖 [ccy-supervisor 12:00] continue",
        ],
    )
    def test_machine_turns_are_automated(self, prompt: str) -> None:
        assert is_automated_prompt(prompt) is True

    def test_a_human_prompt_is_not(self) -> None:
        assert is_automated_prompt("please refactor the loader") is False
