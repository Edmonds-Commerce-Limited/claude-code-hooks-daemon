"""Plan 00271 Task 1.7 — contract-staleness SessionStart advisory.

Sibling of ``version_check``: when the installed Claude Code version exceeds
``contracts/claude-code-hooks/META.json``'s
``last_audited_claude_code_version``, advise running the refresh procedure so
the vendored contract cannot rot silently (Decision 3: advisory, never
auto-refresh — extraction from prose docs must be verified, not trusted).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.session_start.contract_staleness import (
    ContractStalenessHandler,
)


def _hook_input(source: str = "startup") -> dict[str, Any]:
    return {"hook_event_name": "SessionStart", "source": source}


@pytest.fixture
def handler(tmp_path: Path) -> ContractStalenessHandler:
    h = ContractStalenessHandler()
    h.meta_path = tmp_path / "META.json"
    h.meta_path.write_text(
        json.dumps(
            {
                "last_audited_claude_code_version": "2.1.246",
                "refresh_procedure": "docs/guides/HOOK-CONTRACT-REFRESH.md",
            }
        )
    )
    return h


class TestInit:
    def test_identity(self) -> None:
        h = ContractStalenessHandler()
        assert h.handler_id == HandlerID.CONTRACT_STALENESS
        assert h.priority == Priority.CONTRACT_STALENESS
        assert h.terminal is False

    def test_meta_path_defaults_to_vendored_contract(self) -> None:
        h = ContractStalenessHandler()
        assert h.meta_path.name == "META.json"
        assert h.meta_path.parent.name == "claude-code-hooks"


class TestMatches:
    def test_matches_new_session(self, handler: ContractStalenessHandler) -> None:
        assert handler.matches(_hook_input()) is True

    def test_skips_resume_session(self, handler: ContractStalenessHandler) -> None:
        assert handler.matches(_hook_input(source="resume")) is False

    def test_skips_other_events(self, handler: ContractStalenessHandler) -> None:
        assert handler.matches({"hook_event_name": "Stop"}) is False

    def test_skips_none_input(self, handler: ContractStalenessHandler) -> None:
        assert handler.matches(None) is False

    def test_respects_disabled_config(self, handler: ContractStalenessHandler) -> None:
        handler.configure({"enabled": False})
        assert handler.matches(_hook_input()) is False


class TestHandle:
    def test_silent_when_installed_matches_audited(
        self, handler: ContractStalenessHandler
    ) -> None:
        handler.installed_version_reader = lambda: "2.1.246"
        result = handler.handle(_hook_input())
        assert result.decision == Decision.ALLOW
        assert result.context == []

    def test_silent_when_installed_older(self, handler: ContractStalenessHandler) -> None:
        handler.installed_version_reader = lambda: "2.1.200"
        assert handler.handle(_hook_input()).context == []

    def test_advises_when_installed_newer(self, handler: ContractStalenessHandler) -> None:
        handler.installed_version_reader = lambda: "2.2.0"
        result = handler.handle(_hook_input())
        assert result.decision == Decision.ALLOW
        text = "\n".join(result.context)
        assert "2.1.246" in text
        assert "2.2.0" in text
        assert "HOOK-CONTRACT-REFRESH.md" in text

    def test_silent_when_version_unreadable(self, handler: ContractStalenessHandler) -> None:
        handler.installed_version_reader = lambda: None
        assert handler.handle(_hook_input()).context == []

    def test_silent_when_meta_missing(self, tmp_path: Path) -> None:
        h = ContractStalenessHandler()
        h.meta_path = tmp_path / "absent" / "META.json"
        h.installed_version_reader = lambda: "9.9.9"
        assert h.handle(_hook_input()).context == []

    def test_silent_when_meta_malformed(self, tmp_path: Path) -> None:
        h = ContractStalenessHandler()
        h.meta_path = tmp_path / "META.json"
        h.meta_path.write_text("not json")
        h.installed_version_reader = lambda: "9.9.9"
        assert h.handle(_hook_input()).context == []

    def test_non_numeric_versions_stay_silent(self, handler: ContractStalenessHandler) -> None:
        handler.installed_version_reader = lambda: "dev-build"
        assert handler.handle(_hook_input()).context == []


class TestVersionParsing:
    def test_parses_claude_version_output(self) -> None:
        h = ContractStalenessHandler()
        assert h.parse_version_output("2.1.246 (Claude Code)") == "2.1.246"

    def test_rejects_garbage(self) -> None:
        h = ContractStalenessHandler()
        assert h.parse_version_output("no version here") is None


class TestContract:
    def test_guidance_and_acceptance_hooks(self) -> None:
        h = ContractStalenessHandler()
        assert h.get_claude_md() is None
        assert isinstance(h.get_acceptance_tests(), list)
