"""The acceptance method has one home and routes by ``Requires Main Thread`` (Plan 00474 N458).

The acceptance-test skill once called sub-agent execution "unreliable and
forbidden" for ALL tests, while RELEASING.md Step 12 and the generated playbook
route each test by its ``Requires Main Thread`` field. Two documents a release
reads must not give opposite instructions.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_SKILL_DIR: Final[Path] = _REPO_ROOT / ".claude" / "skills" / "acceptance-test"
_SKILL_MD: Final[Path] = _SKILL_DIR / "SKILL.md"
_SKILL_INVOKE: Final[Path] = _SKILL_DIR / "invoke.sh"
_RELEASING: Final[Path] = _REPO_ROOT / "CLAUDE" / "development" / "RELEASING.md"
_GENERATING: Final[Path] = _REPO_ROOT / "CLAUDE" / "AcceptanceTests" / "GENERATING.md"
_PLAYBOOK_GENERATOR: Final[Path] = (
    _REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "playbook_generator.py"
)

_DOCUMENTS: Final[list[Path]] = [
    _SKILL_MD,
    _SKILL_INVOKE,
    _RELEASING,
    _GENERATING,
    _PLAYBOOK_GENERATOR,
]

_OUTRIGHT_BAN: Final[re.Pattern[str]] = re.compile(
    r"sub-?agent[^.\n]{0,80}(forbidden|unreliable)"
    r"|(forbidden|unreliable)[^.\n]{0,40}sub-?agent"
    r"|main\s+thread\s+only"
    r"|NOT\s+sub-?agents",
    re.IGNORECASE,
)


@pytest.mark.parametrize("path", _DOCUMENTS, ids=lambda p: p.name)
def test_no_document_forbids_sub_agents_outright(path: Path) -> None:
    """No acceptance document bans sub-agent execution for every test."""
    match = _OUTRIGHT_BAN.search(path.read_text(encoding="utf-8"))
    assert match is None, f"{path} forbids sub-agent execution outright: {match}"


@pytest.mark.parametrize("path", [_SKILL_MD, _SKILL_INVOKE], ids=lambda p: p.name)
def test_skill_states_routing_by_requires_main_thread(path: Path) -> None:
    """The skill routes by the playbook fields."""
    text = path.read_text(encoding="utf-8")
    assert "Requires Main Thread" in text
    assert "Recommended Model" in text


def test_skill_keeps_the_v290_race_condition_lesson() -> None:
    """The reason main-thread tests stay in the main thread is recorded."""
    assert "v2.9.0" in _SKILL_MD.read_text(encoding="utf-8")


def test_releasing_step_12_points_at_generating_md() -> None:
    """RELEASING.md Step 12 names GENERATING.md as the method's home."""
    text = _RELEASING.read_text(encoding="utf-8")
    step = text.split("## Step 12:", 1)[1].split("### Scope", 1)[0]
    assert "CLAUDE/AcceptanceTests/GENERATING.md" in step
    assert "Requires Main Thread" in step


def test_skill_points_at_generating_md_as_the_home() -> None:
    """A skill is a pointer (DocumentationStrategy R7b): it names GENERATING.md as canonical."""
    text = _SKILL_MD.read_text(encoding="utf-8")
    assert "CLAUDE/AcceptanceTests/GENERATING.md" in text
    assert "canonical home of the acceptance method" not in text
