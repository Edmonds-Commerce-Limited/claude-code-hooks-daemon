"""The router's ``To disable:`` footer is the only one a deny carries (Plan 00484 G4).

A handler that printed its own line as well showed two different disable
instructions in one message, and only one of them asked for a reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_HANDLERS = Path(__file__).resolve().parents[3] / "src/claude_code_hooks_daemon/handlers"


@pytest.mark.parametrize(
    "module",
    [
        "write_clobber_guard",
        "github_auto_close_keywords",
        "git_message_backtick",
        "error_hiding_blocker",
        "security_antipattern",
    ],
)
def test_the_handler_prints_no_disable_footer_of_its_own(module: str) -> None:
    source = (_HANDLERS / "pre_tool_use" / f"{module}.py").read_text(encoding="utf-8")
    assert "To disable" not in source
