"""The router's ``To disable:`` footer is the only one a deny carries (Plan 00484 G4).

A handler that printed its own line as well showed two different disable
instructions in one message, and only one of them asked for a reason. Every
handler source is checked, so a new handler that adds its own footer fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_HANDLERS = Path(__file__).resolve().parents[3] / "src/claude_code_hooks_daemon/handlers"
_HANDLER_SOURCES = sorted(_HANDLERS.glob("**/*.py"))


def test_the_glob_finds_the_handler_sources() -> None:
    assert len(_HANDLER_SOURCES) > 50
    assert _HANDLERS / "pre_tool_use" / "write_clobber_guard.py" in _HANDLER_SOURCES


@pytest.mark.parametrize(
    "source_path", _HANDLER_SOURCES, ids=lambda path: str(path.relative_to(_HANDLERS))
)
def test_the_handler_prints_no_disable_footer_of_its_own(source_path: Path) -> None:
    assert "To disable" not in source_path.read_text(encoding="utf-8")
