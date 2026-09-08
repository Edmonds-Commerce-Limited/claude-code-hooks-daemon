"""Tests for Handler.get_relevance() — Plan 00330 Phase 2.

Design contract (PLAN.md Decision 1):
  - Handler base class has get_relevance(context) -> Relevance
  - Default is "always relevant" and the method is NOT abstract
  - Conditional handlers override it to name what they need
  - It is independent of get_default_enabled(): a default-off handler is
    relevant wherever its precondition holds
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.relevance import Relevance, RelevanceContext
from claude_code_hooks_daemon.handlers.post_tool_use.goal_injection import GoalInjectionHandler
from claude_code_hooks_daemon.handlers.post_tool_use.validate_eslint_on_write import (
    ValidateEslintOnWriteHandler,
)
from claude_code_hooks_daemon.handlers.pre_compact.compaction_signal import (
    CompactionSignalHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.flaggable_content_channel_guard import (
    FlaggableContentChannelGuardHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.flaggable_work_advisor import (
    FlaggableWorkAdvisorHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.global_npm_advisor import (
    GlobalNpmAdvisorHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.lsp_enforcement import (
    LspEnforcementHandler,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.npm_command import NpmCommandHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.quarantine_artefact_read_guard import (
    QuarantineArtefactReadGuardHandler,
)
from claude_code_hooks_daemon.handlers.session_start.model_fallback_detector import (
    ModelFallbackDetectorHandler,
)
from claude_code_hooks_daemon.handlers.session_start.tool_disable_advisor import (
    ToolDisableAdvisorHandler,
)


class _PlainHandler(Handler):
    """Does not override get_relevance — always relevant."""

    def __init__(self) -> None:
        super().__init__(handler_id=HandlerID.TEST_SERVER, priority=Priority.TEST_HANDLER)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        return []


def _context(root: Path, *languages: str) -> RelevanceContext:
    return RelevanceContext(project_root=root, languages=frozenset(languages))


class TestBaseContract:
    def test_default_is_always_relevant(self, tmp_path: Path) -> None:
        verdict = _PlainHandler().get_relevance(_context(tmp_path))
        assert isinstance(verdict, Relevance)
        assert verdict.applicable is True

    def test_is_not_abstract(self) -> None:
        assert not getattr(Handler.get_relevance, "__isabstractmethod__", False)

    def test_signature_takes_a_context(self) -> None:
        params = list(inspect.signature(Handler.get_relevance).parameters)
        assert params == ["self", "context"]


class TestLspEnforcement:
    def test_relevant_when_env_var_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ENABLE_LSP_TOOL", "1")
        assert LspEnforcementHandler().get_relevance(_context(tmp_path)).applicable is True

    def test_relevant_when_settings_json_sets_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ENABLE_LSP_TOOL", raising=False)
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text('{"env": {"ENABLE_LSP_TOOL": "1"}}')
        assert LspEnforcementHandler().get_relevance(_context(tmp_path)).applicable is True

    def test_not_applicable_without_an_lsp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ENABLE_LSP_TOOL", raising=False)
        verdict = LspEnforcementHandler().get_relevance(_context(tmp_path))
        assert verdict.applicable is False
        assert "ENABLE_LSP_TOOL" in verdict.reason

    def test_malformed_settings_json_is_not_an_lsp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ENABLE_LSP_TOOL", raising=False)
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text("{not json")
        assert LspEnforcementHandler().get_relevance(_context(tmp_path)).applicable is False


_NPM_FACTORIES: list[Callable[[Path], Handler]] = [
    lambda root: NpmCommandHandler(project_root=root),
    lambda root: GlobalNpmAdvisorHandler(),
]


@pytest.mark.parametrize("factory", _NPM_FACTORIES, ids=["npm_command", "global_npm_advisor"])
class TestNpmHandlers:
    def test_relevant_with_package_json(
        self, factory: Callable[[Path], Handler], tmp_path: Path
    ) -> None:
        (tmp_path / "package.json").write_text("{}")
        assert factory(tmp_path).get_relevance(_context(tmp_path)).applicable is True

    def test_not_applicable_without_package_json(
        self, factory: Callable[[Path], Handler], tmp_path: Path
    ) -> None:
        verdict = factory(tmp_path).get_relevance(_context(tmp_path))
        assert verdict.applicable is False
        assert "package.json" in verdict.reason


class TestEslintOnWrite:
    def test_relevant_for_typescript(self, tmp_path: Path) -> None:
        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
        assert handler.get_relevance(_context(tmp_path, "typescript")).applicable is True

    def test_not_applicable_without_js_or_ts(self, tmp_path: Path) -> None:
        handler = ValidateEslintOnWriteHandler(workspace_root=tmp_path)
        assert handler.get_relevance(_context(tmp_path, "python")).applicable is False


@pytest.mark.parametrize(
    "handler_cls",
    [
        GoalInjectionHandler,
        CompactionSignalHandler,
        ModelFallbackDetectorHandler,
        ToolDisableAdvisorHandler,
    ],
)
class TestCcySupervisorHandlers:
    def test_relevant_when_supervisor_armed(
        self, handler_cls: type[Handler], tmp_path: Path
    ) -> None:
        ccy = tmp_path / ".claude" / "ccy"
        ccy.mkdir(parents=True)
        (ccy / "ccy.env").write_text(
            'export CCY_CLAUDE_WRAPPER="$PWD/.claude/ccy/claude-supervise.py"\n'
        )
        assert handler_cls().get_relevance(_context(tmp_path)).applicable is True

    def test_not_applicable_without_supervisor(
        self, handler_cls: type[Handler], tmp_path: Path
    ) -> None:
        verdict = handler_cls().get_relevance(_context(tmp_path))
        assert verdict.applicable is False
        assert "supervisor" in verdict.reason


@pytest.mark.parametrize(
    "handler_cls",
    [
        FlaggableWorkAdvisorHandler,
        FlaggableContentChannelGuardHandler,
        QuarantineArtefactReadGuardHandler,
    ],
)
class TestFlaggableContentTrio:
    def test_relevant_when_quarantine_agent_deployed(
        self, handler_cls: type[Handler], tmp_path: Path
    ) -> None:
        agents = tmp_path / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "hooks-daemon-opus-security.md").write_text("---\nname: x\n---\n")
        assert handler_cls().get_relevance(_context(tmp_path)).applicable is True

    def test_not_applicable_without_quarantine_agent(
        self, handler_cls: type[Handler], tmp_path: Path
    ) -> None:
        verdict = handler_cls().get_relevance(_context(tmp_path))
        assert verdict.applicable is False
        assert "hooks-daemon-opus-security" in verdict.reason
