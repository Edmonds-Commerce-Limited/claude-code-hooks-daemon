"""Tests for the shared quarantine-agent relevance predicate (Plan 00330)."""

from __future__ import annotations

from pathlib import Path

from claude_code_hooks_daemon.core.relevance import RelevanceContext
from claude_code_hooks_daemon.handlers.utils.quarantine import (
    QUARANTINE_AGENT_NAME,
    quarantine_agent_relevance,
)


def _context(root: Path) -> RelevanceContext:
    return RelevanceContext(project_root=root, languages=frozenset())


def test_agent_name_is_the_shipped_template() -> None:
    assert QUARANTINE_AGENT_NAME == "hooks-daemon-opus-security"


def test_deployed_agent_is_relevant(tmp_path: Path) -> None:
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / f"{QUARANTINE_AGENT_NAME}.md").write_text("---\nname: x\n---\n")
    verdict = quarantine_agent_relevance(_context(tmp_path))
    assert verdict.applicable is True
    assert QUARANTINE_AGENT_NAME in verdict.reason


def test_absent_agent_is_not_applicable(tmp_path: Path) -> None:
    verdict = quarantine_agent_relevance(_context(tmp_path))
    assert verdict.applicable is False
    assert QUARANTINE_AGENT_NAME in verdict.reason
