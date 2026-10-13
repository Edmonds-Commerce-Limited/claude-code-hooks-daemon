"""The release procedure and the acceptance-test skill agree on how Step 12 runs (Plan 00450).

The acceptance-test skill runs every test on the main thread, sequentially, and
forbids sub-agents. A release document that tells the reader to batch the gate
across parallel Haiku agents sends them to the method the skill forbids by name.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_SKILLS_ROOT: Final[Path] = _REPO_ROOT / ".claude" / "skills"
_RELEASING: Final[Path] = _REPO_ROOT / "CLAUDE" / "development" / "RELEASING.md"
_RELEASE_AGENT: Final[Path] = _REPO_ROOT / ".claude" / "agents" / "release-agent.md"

_PARALLEL_ACCEPTANCE: Final[re.Pattern[str]] = re.compile(
    r"(spawns?\s+parallel\s+haiku|parallel\s+haiku\s+agents?"
    r"|delegated\s+to\s+parallel\s+sub-?agents?|batch\s+delegable\s+tests)",
    re.IGNORECASE,
)


def _skill_invoke_scripts() -> list[Path]:
    return sorted(_SKILLS_ROOT.glob("*/invoke.sh"))


@pytest.mark.parametrize("path", _skill_invoke_scripts(), ids=lambda p: p.parent.name)
def test_no_skill_invoke_script_delegates_acceptance_to_parallel_agents(path: Path) -> None:
    """No skill invoke.sh instructs parallel sub-agent execution of acceptance tests."""
    match = _PARALLEL_ACCEPTANCE.search(path.read_text(encoding="utf-8"))
    assert match is None, f"{path} tells the reader to run acceptance in parallel: {match}"


@pytest.mark.parametrize("path", [_RELEASING, _RELEASE_AGENT], ids=lambda p: p.name)
def test_release_documents_do_not_delegate_acceptance_to_parallel_agents(path: Path) -> None:
    """RELEASING.md and the release agent do not restate the forbidden method."""
    match = _PARALLEL_ACCEPTANCE.search(path.read_text(encoding="utf-8"))
    assert match is None, f"{path} tells the reader to run acceptance in parallel: {match}"


def test_release_skill_names_the_main_thread_method() -> None:
    """release/invoke.sh states the gate runs on the main thread, sequentially."""
    text = (_SKILLS_ROOT / "release" / "invoke.sh").read_text(encoding="utf-8").lower()
    assert "main thread" in text
    assert "sequential" in text
