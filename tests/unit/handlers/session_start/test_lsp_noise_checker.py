"""Tests for LspNoiseCheckerHandler (Plan 00368 Task 2.2, every supported language).

The handler is a thin orchestrator with ZERO language-specific logic (owner
ruling: this must not be Python-only). Per-language behaviour lives in, and
is tested by, tests/unit/strategies/lsp_noise/test_*_strategy.py; these
tests cover only ORCHESTRATION - relevance across languages, aggregation of
every relevant strategy's exclude/stale findings, and the resident guidance
and acceptance-test surface - using fake strategies plus the real registry
for the identity/coverage checks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

import psutil
import pytest

from claude_code_hooks_daemon.constants import DaemonPath
from claude_code_hooks_daemon.constants.layout import CORE_VENDORED_BUILD_DIR_NAMES
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.project_layout import ProjectLayout
from claude_code_hooks_daemon.core.relevance import RelevanceContext
from claude_code_hooks_daemon.handlers.session_start.lsp_noise_checker import (
    LspNoiseCheckerHandler,
    RunningServer,
    required_excludes,
    running_language_servers,
)
from claude_code_hooks_daemon.strategies.lsp_noise.registry import LspNoiseStrategyRegistry

_NEW_SESSION = {"hook_event_name": "SessionStart", "source": "startup"}


@dataclass
class _FakeStrategy:
    """A minimal LspNoiseStrategy double for orchestration-level tests."""

    name: str
    relevant: bool
    finding: list[str] = field(default_factory=list)
    config_path: Path | None = None
    processes: tuple[str, ...] = ()

    @property
    def language_name(self) -> str:
        return self.name

    @property
    def process_names(self) -> tuple[str, ...]:
        return self.processes

    def is_relevant(self, context: RelevanceContext) -> bool:
        return self.relevant

    def exclude_finding(
        self, root: Path, required: frozenset[str]
    ) -> tuple[list[str], Path | None]:
        return self.finding, self.config_path

    def get_acceptance_tests(self) -> list[Any]:
        return []


def _registry(*strategies: _FakeStrategy) -> LspNoiseStrategyRegistry:
    registry = LspNoiseStrategyRegistry()
    for strategy in strategies:
        registry.register(strategy)
    return registry


@pytest.fixture
def handler() -> LspNoiseCheckerHandler:
    return LspNoiseCheckerHandler()


def _run(handler: LspNoiseCheckerHandler, root: Path) -> list[str]:
    with patch.object(handler, "_get_project_root", return_value=root):
        result = handler.handle(_NEW_SESSION)
    assert result.decision == Decision.ALLOW
    return result.context


# ── Identity ───────────────────────────────────────────────────────


class TestIdentity:
    def test_name_priority_and_advisory_shape(self, handler: LspNoiseCheckerHandler) -> None:
        assert handler.name == "lsp-noise-checker"
        assert handler.priority == 69
        assert handler.terminal is False
        assert "advisory" in handler.tags
        assert "non-terminal" in handler.tags

    def test_enabled_by_default(self, handler: LspNoiseCheckerHandler) -> None:
        assert handler.get_default_enabled() is True

    def test_declares_both_rules(self, handler: LspNoiseCheckerHandler) -> None:
        ids = {rule.rule_id for rule in handler.get_rules()}
        assert ids == {RuleID.LSP_CONFIG_EXCLUDE, RuleID.LSP_SERVER_STALE}
        for rule in handler.get_rules():
            assert rule.verbose.strip()
            assert rule.fix.strip()

    def test_claude_md_names_every_language_and_the_principle(
        self, handler: LspNoiseCheckerHandler
    ) -> None:
        text = handler.get_claude_md()
        assert text is not None
        for language in handler._registry.language_names:
            assert language in text
        assert "signal" in text.lower()
        assert RuleID.LSP_CONFIG_EXCLUDE in text
        assert RuleID.LSP_SERVER_STALE in text

    def test_acceptance_tests_cover_every_registered_language(
        self, handler: LspNoiseCheckerHandler
    ) -> None:
        tests = handler.get_acceptance_tests()
        joined = " ".join(" ".join(t.expected_message_patterns) for t in tests)
        for language in handler._registry.language_names:
            assert any(part in joined for part in language.split("/")), language


# ── Matching and relevance (orchestration only) ─────────────────────


class TestMatches:
    def test_matches_when_any_strategy_is_relevant(
        self, handler: LspNoiseCheckerHandler, tmp_path: Path
    ) -> None:
        handler._registry = _registry(
            _FakeStrategy("A", relevant=True), _FakeStrategy("B", relevant=False)
        )
        with patch.object(handler, "_get_project_root", return_value=tmp_path):
            assert handler.matches(_NEW_SESSION) is True

    def test_does_not_match_when_no_strategy_is_relevant(
        self, handler: LspNoiseCheckerHandler, tmp_path: Path
    ) -> None:
        handler._registry = _registry(_FakeStrategy("A", relevant=False))
        with patch.object(handler, "_get_project_root", return_value=tmp_path):
            assert handler.matches(_NEW_SESSION) is False

    def test_resume_does_not_match(self, handler: LspNoiseCheckerHandler, tmp_path: Path) -> None:
        handler._registry = _registry(_FakeStrategy("A", relevant=True))
        transcript = tmp_path / "t.jsonl"
        transcript.write_text("x" * 200, encoding="utf-8")
        hook_input = {**_NEW_SESSION, "transcript_path": str(transcript)}
        with patch.object(handler, "_get_project_root", return_value=tmp_path):
            assert handler.matches(hook_input) is False

    def test_no_project_root_is_silent(self, handler: LspNoiseCheckerHandler) -> None:
        with patch.object(handler, "_get_project_root", return_value=None):
            assert handler.matches(_NEW_SESSION) is False

    def test_relevance_follows_any_strategy(
        self, handler: LspNoiseCheckerHandler, tmp_path: Path
    ) -> None:
        handler._registry = _registry(_FakeStrategy("A", relevant=True))
        assert handler.get_relevance(RelevanceContext.probe(tmp_path)).applicable
        handler._registry = _registry(_FakeStrategy("A", relevant=False))
        assert not handler.get_relevance(RelevanceContext.probe(tmp_path)).applicable

    def test_real_registry_matches_a_go_only_project(
        self, handler: LspNoiseCheckerHandler, tmp_path: Path
    ) -> None:
        """End-to-end sanity: a non-Python language alone is enough to match."""
        (tmp_path / "go.mod").write_text("module example.com/x\n", encoding="utf-8")
        with patch.object(handler, "_get_project_root", return_value=tmp_path):
            assert handler.matches(_NEW_SESSION) is True


# ── Orchestration: aggregating across every relevant strategy ───────


class TestHandleAggregatesAcrossStrategies:
    def test_exclude_findings_from_every_relevant_strategy_are_concatenated(
        self, handler: LspNoiseCheckerHandler, tmp_path: Path
    ) -> None:
        handler._registry = _registry(
            _FakeStrategy("A", relevant=True, finding=["a-finding"]),
            _FakeStrategy("B", relevant=True, finding=["b-finding"]),
            _FakeStrategy("C", relevant=False, finding=["c-finding-must-not-appear"]),
        )
        lines = _run(handler, tmp_path)
        assert "a-finding" in lines
        assert "b-finding" in lines
        assert "c-finding-must-not-appear" not in lines

    def test_process_reader_is_called_once_with_the_union_of_process_names(
        self, handler: LspNoiseCheckerHandler, tmp_path: Path
    ) -> None:
        calls: list[frozenset[str]] = []

        def fake_reader(names: frozenset[str]) -> list[RunningServer]:
            calls.append(names)
            return []

        handler.process_reader = fake_reader
        cfg_a, cfg_b = tmp_path / "a.cfg", tmp_path / "b.cfg"
        cfg_a.write_text("x", encoding="utf-8")
        cfg_b.write_text("x", encoding="utf-8")
        handler._registry = _registry(
            _FakeStrategy("A", relevant=True, config_path=cfg_a, processes=("proc-a",)),
            _FakeStrategy("B", relevant=True, config_path=cfg_b, processes=("proc-b",)),
        )
        _run(handler, tmp_path)
        assert calls == [frozenset({"proc-a", "proc-b"})]

    def test_process_reader_is_not_called_when_nothing_is_relevant(
        self, handler: LspNoiseCheckerHandler, tmp_path: Path
    ) -> None:
        calls: list[frozenset[str]] = []
        handler.process_reader = lambda names: calls.append(names) or []
        handler._registry = _registry(_FakeStrategy("A", relevant=False))
        _run(handler, tmp_path)
        assert calls == []

    def test_stale_finding_only_matches_its_own_strategys_process_names(
        self, handler: LspNoiseCheckerHandler, tmp_path: Path
    ) -> None:
        cfg = tmp_path / "a.cfg"
        cfg.write_text("x", encoding="utf-8")
        cfg_mtime = cfg.stat().st_mtime
        handler._registry = _registry(
            _FakeStrategy("A", relevant=True, config_path=cfg, processes=("proc-a",))
        )
        handler.process_reader = lambda names: [
            RunningServer(pid=1, started_at=cfg_mtime - 10, matched_names=frozenset({"proc-a"})),
            RunningServer(pid=2, started_at=cfg_mtime - 10, matched_names=frozenset({"proc-b"})),
        ]
        lines = _run(handler, tmp_path)
        text = "\n".join(lines)
        assert RuleID.LSP_SERVER_STALE in text
        assert "(pid 1)" in text
        assert "pid 2" not in text

    def test_no_config_path_means_no_staleness_check(
        self, handler: LspNoiseCheckerHandler, tmp_path: Path
    ) -> None:
        handler._registry = _registry(
            _FakeStrategy("A", relevant=True, config_path=None, processes=("proc-a",))
        )
        handler.process_reader = lambda names: [
            RunningServer(pid=1, started_at=0.0, matched_names=frozenset({"proc-a"}))
        ]
        lines = _run(handler, tmp_path)
        assert RuleID.LSP_SERVER_STALE not in "\n".join(lines)


# ── The derived required-exclude set (language-agnostic, unchanged) ─


class TestRequiredExcludes:
    def test_is_derived_from_daemon_knowledge(self) -> None:
        from dataclasses import replace

        layout = replace(
            ProjectLayout.built_in_default(), plan_dir="docs/plans", remote_docs_dir="vendored"
        )
        required = required_excludes(layout)
        assert DaemonPath.UNTRACKED_DIR in required
        assert "docs/plans" in required
        assert "vendored" in required
        for name in CORE_VENDORED_BUILD_DIR_NAMES:
            assert f"**/{name}" in required

    def test_no_layout_falls_back_to_built_in_defaults(self) -> None:
        required = required_excludes(None)
        default = ProjectLayout.built_in_default()
        assert default.plan_dir in required
        assert default.remote_docs_dir in required


# ── The process scan ─────────────────────────────────────────────────


_PROCESS_ITER = (
    "claude_code_hooks_daemon.handlers.session_start.lsp_noise_checker.psutil.process_iter"
)


class TestProcessScan:
    def test_default_reader_finds_a_matching_process_by_cmdline(self) -> None:
        class _Proc:
            def __init__(self, pid: int, cmdline: list[str], created: float) -> None:
                self.info = {"pid": pid, "cmdline": cmdline, "create_time": created}

        table = [
            _Proc(10, ["node", "/x/bin/pyright-langserver", "--stdio"], 100.0),
            _Proc(11, ["python", "daemon.py"], 200.0),
            _Proc(12, [], 300.0),
        ]
        with patch(_PROCESS_ITER, return_value=table):
            found = running_language_servers(frozenset({"pyright-langserver"}))
        assert found == [
            RunningServer(pid=10, started_at=100.0, matched_names=frozenset({"pyright-langserver"}))
        ]

    def test_a_process_can_match_multiple_known_names_at_once(self) -> None:
        class _Proc:
            def __init__(self, pid: int, cmdline: list[str], created: float) -> None:
                self.info = {"pid": pid, "cmdline": cmdline, "create_time": created}

        table = [_Proc(1, ["gopls", "serve"], 5.0)]
        with patch(_PROCESS_ITER, return_value=table):
            found = running_language_servers(frozenset({"gopls", "rust-analyzer"}))
        assert found == [RunningServer(pid=1, started_at=5.0, matched_names=frozenset({"gopls"}))]

    def test_scan_survives_a_vanished_process(self) -> None:
        class _Gone:
            @property
            def info(self) -> dict[str, object]:
                raise psutil.NoSuchProcess(99)

        with patch(_PROCESS_ITER, return_value=[_Gone()]):
            assert running_language_servers(frozenset({"pyright-langserver"})) == []
