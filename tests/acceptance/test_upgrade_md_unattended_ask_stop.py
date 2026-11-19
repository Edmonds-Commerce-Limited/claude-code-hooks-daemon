"""The skill's unattended upgrade stops cleanly at every 'ask the user' step (Plan 00625).

The relayed ruling (DESIGN 11a item 4): under ``--unattended`` the agent
never guesses an answer a person was meant to give. Where the script cannot
enforce that (the steps after deploy are the agent's), the skill text says it:
stop at that step and print one line. Post-upgrade tasks carry no
machine-readable "ask" marker, so the instruction is general, not a grep.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_SOURCE: Final[Path] = (
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills" / "hooks-daemon" / "upgrade.md"
)
_DEPLOYED: Final[Path] = _REPO_ROOT / ".claude" / "skills" / "hooks-daemon" / "upgrade.md"

_NOTICE: Final[str] = "AUTO-UPGRADE PAUSED:"


def _text() -> str:
    return _SOURCE.read_text(encoding="utf-8")


def test_the_one_line_notice_is_given() -> None:
    assert _NOTICE in _text()


def test_the_stop_covers_post_upgrade_tasks_and_the_optimisation_review() -> None:
    text = _text()
    section = text[text.index("**Under `--unattended`, never answer for the user.**") :]
    section = section[: section.index("\n\n")]
    assert "post-upgrade task" in section
    assert "step 9" in section
    assert "never guess" in section


def test_the_deployed_copy_matches_the_source() -> None:
    assert _DEPLOYED.read_text(encoding="utf-8") == _text()
