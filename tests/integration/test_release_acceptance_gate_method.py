"""The release skill does not send the whole acceptance gate to parallel agents (Plan 00450).

Step 12 routes each test by its ``Requires Main Thread`` field. A release
document telling the reader to spawn parallel Haiku agents for ALL batches
contradicts that routing, because main-thread tests can never be delegated.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_SKILLS_ROOT: Final[Path] = _REPO_ROOT / ".claude" / "skills"
_RELEASE_INVOKE: Final[Path] = _SKILLS_ROOT / "release" / "invoke.sh"

_ALL_BATCHES_PARALLEL: Final[re.Pattern[str]] = re.compile(
    r"spawns?\s+parallel\s+haiku\s+agents?.{0,40}all\s+batches", re.IGNORECASE | re.DOTALL
)


def _skill_invoke_scripts() -> list[Path]:
    return sorted(_SKILLS_ROOT.glob("*/invoke.sh"))


@pytest.mark.parametrize("path", _skill_invoke_scripts(), ids=lambda p: p.parent.name)
def test_no_skill_invoke_script_spawns_parallel_agents_for_all_batches(path: Path) -> None:
    """No skill invoke.sh sends every acceptance batch to parallel Haiku agents."""
    match = _ALL_BATCHES_PARALLEL.search(path.read_text(encoding="utf-8"))
    assert match is None, f"{path} spawns parallel agents for all batches: {match}"


def test_release_skill_defers_to_step_12_routing() -> None:
    """release/invoke.sh names the Step 12 routing field as the method."""
    text = _RELEASE_INVOKE.read_text(encoding="utf-8")
    assert "RELEASING.md Step 12" in text
    assert "Requires Main Thread" in text
