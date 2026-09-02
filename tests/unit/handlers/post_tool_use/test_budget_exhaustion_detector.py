"""Tests for BudgetExhaustionDetectorHandler - budget-exhaustion advisory.

Covers: web-search budget refusal fixture (field-confirmed shape, Plan 00315
BUDGETS.md), generic budget/exhausted/quota/limit-reached shapes, precision
(no firing on Read/Grep/Glob tool responses, no firing on the ceiling number
alone, no firing on ordinary prose mentioning "budget"), the occurrence
ledger, and config options (excluded_tools, extra_patterns).
"""

import json
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.post_tool_use.budget_exhaustion_detector import (
    BudgetExhaustionDetectorHandler,
)


@pytest.fixture
def handler() -> BudgetExhaustionDetectorHandler:
    """Create a fresh handler instance for each test."""
    return BudgetExhaustionDetectorHandler()


def _tool_input(tool_name: str, tool_response: Any, session_id: str = "sess-1") -> dict[str, Any]:
    """Build a PostToolUse hook input with the given tool name/response."""
    return {
        "tool_name": tool_name,
        "tool_input": {},
        "tool_response": tool_response,
        "session_id": session_id,
    }


# ─── Web-search budget fixture (Plan 00315 BUDGETS.md, field-confirmed) ──────


class TestWebSearchBudgetFixture:
    """The pinned field-confirmed web-search budget refusal shape."""

    _FIXTURE = (
        "Web search was not performed: this session has used its web search "
        "budget (200 of 200 WebSearch calls). Continue with the information "
        "already gathered instead of issuing more searches. If more searches "
        "are genuinely needed, raise CLAUDE_CODE_MAX_WEB_SEARCHES"
    )

    def test_matches_web_search_budget_fixture(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        hook_input = _tool_input("WebSearch", {"content": self._FIXTURE})
        assert handler.matches(hook_input) is True

    def test_never_keys_on_the_ceiling_number_alone(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """The bare number '200' with no budget/exhaustion wording must not fire."""
        hook_input = _tool_input("WebSearch", {"content": "Found 200 results across 200 pages."})
        assert handler.matches(hook_input) is False

    def test_advisory_names_matched_fragment_and_demands_prominent_reporting(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        hook_input = _tool_input("WebSearch", {"content": self._FIXTURE})
        result = handler.handle(hook_input)

        assert result.decision == Decision.ALLOW
        assert result.context
        combined = "\n".join(result.context)
        assert "BUDGET EXHAUSTED" in combined
        assert "🚨" in combined
        assert "Web search was not performed" in combined
        assert "not" in combined.lower() and "retry" in combined.lower()


# ─── Generic budget-exhaustion pattern family ────────────────────────────────


class TestGenericBudgetShapes:
    @pytest.mark.parametrize(
        "content",
        [
            "Error: budget exhausted for this operation.",
            "Request denied: quota exceeded for this resource.",
            "budget limit reached; no further calls permitted this session.",
            "This tool's budget has been used up for the session.",
        ],
    )
    def test_matches_generic_exhaustion_shapes(
        self, handler: BudgetExhaustionDetectorHandler, content: str
    ) -> None:
        hook_input = _tool_input("Bash", {"stdout": content, "stderr": ""})
        assert handler.matches(hook_input) is True

    def test_does_not_match_ordinary_prose_mentioning_budget(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        """Near-miss: 'budget' appears but with no exhaustion/quota context."""
        hook_input = _tool_input(
            "Bash",
            {"stdout": "Updated the project budget planning spreadsheet.", "stderr": ""},
        )
        assert handler.matches(hook_input) is False


# ─── Precision: excluded tools ───────────────────────────────────────────────


class TestExcludedToolsByDefault:
    @pytest.mark.parametrize("tool_name", ["Read", "Grep", "Glob"])
    def test_default_excluded_tools_never_fire(
        self, handler: BudgetExhaustionDetectorHandler, tool_name: str
    ) -> None:
        """File-content tools are excluded by default so reading a file that
        merely discusses budget exhaustion in its prose never fires."""
        hook_input = _tool_input(
            tool_name,
            {"content": "budget exhausted: this session has used its web search budget"},
        )
        assert handler.matches(hook_input) is False

    def test_excluded_tools_configurable(self, handler: BudgetExhaustionDetectorHandler) -> None:
        handler._excluded_tools = ["Bash"]
        hook_input = _tool_input(
            "Bash", {"stdout": "budget exhausted for this session", "stderr": ""}
        )
        assert handler.matches(hook_input) is False


class TestExtraPatterns:
    def test_extra_patterns_are_additive(self, handler: BudgetExhaustionDetectorHandler) -> None:
        handler._extra_patterns = [r"custom budget ceiling hit"]
        hook_input = _tool_input(
            "Bash", {"stdout": "custom budget ceiling hit today", "stderr": ""}
        )
        assert handler.matches(hook_input) is True


# ─── Never blocks ─────────────────────────────────────────────────────────────


class TestNeverBlocks:
    def test_decision_is_always_allow(self, handler: BudgetExhaustionDetectorHandler) -> None:
        hook_input = _tool_input(
            "Bash", {"stdout": "quota exceeded for this operation", "stderr": ""}
        )
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW


# ─── Occurrence ledger (Task 2.2) ────────────────────────────────────────────


class TestOccurrenceLedger:
    def test_detection_appends_one_json_line(
        self,
        handler: BudgetExhaustionDetectorHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from claude_code_hooks_daemon.core.project_context import ProjectContext

        monkeypatch.setattr(ProjectContext, "daemon_untracked_dir", staticmethod(lambda: tmp_path))

        hook_input = _tool_input(
            "Bash",
            {"stdout": "quota exceeded for this operation", "stderr": ""},
            session_id="sess-ledger",
        )
        handler.handle(hook_input)

        ledger_path = tmp_path / "budget-exhaustion-events.jsonl"
        assert ledger_path.exists()
        lines = [ln for ln in ledger_path.read_text().splitlines() if ln.strip()]
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["session_id"] == "sess-ledger"
        assert record["tool_name"] == "Bash"
        assert "timestamp" in record
        assert "quota exceeded" in record["matched_fragment"]

    def test_ledger_write_failure_is_fail_open(
        self,
        handler: BudgetExhaustionDetectorHandler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A ledger write error must never raise -- the advisory still returns."""
        from claude_code_hooks_daemon.core.project_context import ProjectContext

        def _raise() -> Path:
            raise RuntimeError("no project context")

        monkeypatch.setattr(ProjectContext, "daemon_untracked_dir", staticmethod(_raise))

        hook_input = _tool_input(
            "Bash", {"stdout": "quota exceeded for this operation", "stderr": ""}
        )
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW


# ─── Handler metadata ────────────────────────────────────────────────────────


class TestHandlerMetadata:
    def test_default_enabled_true(self, handler: BudgetExhaustionDetectorHandler) -> None:
        assert handler.get_default_enabled() is True

    def test_claude_md_mentions_budgets(self, handler: BudgetExhaustionDetectorHandler) -> None:
        guidance = handler.get_claude_md()
        assert guidance is not None
        assert "budget" in guidance.lower()

    def test_acceptance_tests_include_advisory_and_near_miss(
        self, handler: BudgetExhaustionDetectorHandler
    ) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) >= 2
