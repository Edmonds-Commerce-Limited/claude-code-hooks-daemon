"""The branch sweep SessionStart summary (Plan 00558 Task 2.3).

Real temporary git repositories; the report text itself is pinned in
``tests/unit/core/test_branch_sweep.py``, so these tests cover what the
handler adds: the source split, the cap and the legacy fallback, the
deprecation line, the budget and the fail-silent paths.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import (
    BranchesConfig,
    HandlerConfig,
    HandlersConfig,
    fold_handler_aliases,
)
from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.branch_creation import LABELS_RELATIVE_PATH, read_labels
from claude_code_hooks_daemon.core.branch_inventory import BranchInventoryError, build_inventory
from claude_code_hooks_daemon.handlers.session_start.branch_sweep import BranchSweepHandler

_ROOT = "claude_code_hooks_daemon.handlers.session_start.branch_sweep.ProjectContext.project_root"
_BUILD = "claude_code_hooks_daemon.handlers.session_start.branch_sweep.build_inventory"
DAY = 86_400


def _git(cwd: Path, *args: str, days_ago: float = 0) -> None:
    stamp = f"@{int(time.time() - days_ago * DAY)} +0000"
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp},
    )


def _commit(repo: Path, name: str, days_ago: float = 0) -> None:
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name, days_ago=days_ago)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(tmp_path, "base", days_ago=40)
    return tmp_path


def _new() -> dict[str, Any]:
    return {HookInputField.HOOK_EVENT_NAME: "SessionStart", "source": "startup"}


def _resume(tmp_path: Path) -> dict[str, Any]:
    transcript = tmp_path / "t.jsonl"
    transcript.write_text('{"type": "user"}\n' * 3)
    return {**_new(), HookInputField.TRANSCRIPT_PATH: str(transcript), "source": "resume"}


def _run(handler: BranchSweepHandler, repo: Path, hook_input: dict[str, Any]) -> list[str]:
    with patch(_ROOT, return_value=repo):
        result = handler.handle(hook_input)
    assert result.decision == Decision.ALLOW
    return list(result.context)


class TestIdentity:
    def test_ids_and_priority(self) -> None:
        handler = BranchSweepHandler()
        assert handler.handler_id == HandlerID.BRANCH_SWEEP
        assert HandlerID.BRANCH_SWEEP.config_key == "branch_sweep"
        assert handler.priority == Priority.BRANCH_SWEEP
        assert handler.terminal is False
        assert HandlerTag.ADVISORY in handler.tags

    def test_matches_every_source(self, tmp_path: Path) -> None:
        handler = BranchSweepHandler()
        assert handler.matches(_new())
        assert handler.matches(_resume(tmp_path))


class TestSummary:
    def test_clean_repository_is_silent(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "fresh")
        _commit(repo, "fresh")
        _git(repo, "checkout", "-q", "main")
        assert _run(BranchSweepHandler(), repo, _new()) == []

    def test_writes_the_labels_snapshot_for_the_creation_guard(self, repo: Path) -> None:
        _git(repo, "branch", "done", "main")
        _git(repo, "checkout", "-q", "-b", "open")
        _commit(repo, "open")
        _git(repo, "checkout", "-q", "main")
        _run(BranchSweepHandler(), repo, _new())
        labels = read_labels(repo / LABELS_RELATIVE_PATH)
        assert labels["done"]["group"] == "merged"
        assert labels["done"]["action"]
        assert labels["open"]["group"] == "live"

    def test_unpushed_dormant_branch_is_loud_on_resume_too(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "lost")
        _commit(repo, "lost", days_ago=10)
        _git(repo, "checkout", "-q", "main")
        handler = BranchSweepHandler()
        for hook_input in (_new(), _resume(repo)):
            text = "\n".join(_run(handler, repo, hook_input))
            assert "CONTAINED NOWHERE: lost" in text

    def test_cap_falls_back_to_the_legacy_option(self, repo: Path) -> None:
        for name in ("a", "b"):
            _git(repo, "checkout", "-q", "-b", name, "main")
            _commit(repo, name)
        _git(repo, "checkout", "-q", "main")
        handler = BranchSweepHandler()
        handler._max_open_branches = 2
        text = "\n".join(_run(handler, repo, _new()))
        assert "Open work: 2 of 2" in text
        assert "Deprecated" in text

    def test_explicit_cap_silences_the_deprecation(self, repo: Path) -> None:
        handler = BranchSweepHandler()
        handler._max_open_branches = 2
        handler._branches = BranchesConfig.model_validate({"wip": {"cap": 5}})
        assert _run(handler, repo, _new()) == []

    def test_not_a_repository_is_silent(self, tmp_path: Path) -> None:
        assert _run(BranchSweepHandler(), tmp_path, _new()) == []

    def test_inventory_failure_is_silent(self, repo: Path) -> None:
        with patch(_BUILD, side_effect=BranchInventoryError("boom")):
            assert _run(BranchSweepHandler(), repo, _new()) == []

    def test_project_context_uninitialised_uses_cwd(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(repo)
        with patch(_ROOT, side_effect=RuntimeError("no context")):
            assert BranchSweepHandler().handle(_new()).context == []

    def test_inventory_uses_the_configured_budget(self, repo: Path) -> None:
        handler = BranchSweepHandler()
        handler._branches = BranchesConfig.model_validate({"sweep": {"budget_ms": 0}})
        with patch(_BUILD, wraps=build_inventory) as spy:
            _run(handler, repo, _new())
        assert spy.call_args.args[1].sweep.budget_ms == 0


class TestAlias:
    def test_old_key_disables_the_new_handler(self) -> None:
        config = HandlersConfig.model_validate(
            {"session_start": {"branch_count_advisor": {"enabled": False}}}
        )
        assert set(config.session_start) == {"branch_sweep"}
        assert config.session_start["branch_sweep"].enabled is False

    def test_old_options_reach_the_new_handler(self) -> None:
        config = HandlersConfig.model_validate(
            {"session_start": {"branch_count_advisor": {"options": {"max_open_branches": 4}}}}
        )
        assert config.session_start["branch_sweep"].options == {"max_open_branches": 4}

    def test_either_key_disabling_wins(self) -> None:
        config = HandlersConfig.model_validate(
            {
                "session_start": {
                    "branch_count_advisor": {"enabled": False, "options": {"a": 1}},
                    "branch_sweep": {"enabled": True, "options": {"b": 2}},
                }
            }
        )
        block = config.session_start["branch_sweep"]
        assert block.enabled is False
        assert block.options == {"a": 1, "b": 2}

    def test_bare_old_key_is_an_enabled_block(self) -> None:
        config = HandlersConfig.model_validate({"session_start": {"branch_count_advisor": None}})
        assert set(config.session_start) == {"branch_sweep"}
        assert config.session_start["branch_sweep"].enabled is True

    def test_coerced_blocks_fold_to_a_handler_config(self) -> None:
        folded = fold_handler_aliases(
            "session_start",
            {
                "branch_count_advisor": HandlerConfig(enabled=False),
                "other": HandlerConfig(),
            },
        )
        assert set(folded) == {"branch_sweep", "other"}
        assert isinstance(folded["branch_sweep"], HandlerConfig)
        assert folded["branch_sweep"].enabled is False

    def test_no_alias_present_returns_the_mapping_unchanged(self) -> None:
        handlers: dict[str, Any] = {"other": {}}
        assert fold_handler_aliases("session_start", handlers) is handlers

    def test_a_non_mapping_old_block_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must be a mapping"):
            fold_handler_aliases("session_start", {"branch_count_advisor": 3})


class TestDocs:
    def test_claude_md_names_the_verb_and_the_keys(self) -> None:
        text = BranchSweepHandler().get_claude_md() or ""
        assert "branch-sweep" in text
        assert "branches.wip.cap" in text
        assert "branch_count_advisor" in text

    def test_acceptance_tests(self) -> None:
        tests = BranchSweepHandler().get_acceptance_tests()
        assert tests
        assert all(t.expected_decision == Decision.ALLOW for t in tests)


class TestClaudeMdNotices:
    """Plan 00594 round 2: the CLAUDE.md block notice is asked for at each SessionStart."""

    def test_shown_on_the_very_first_session_start(self, repo: Path) -> None:
        handler = BranchSweepHandler()
        handler.claude_md_notices = lambda: ["CLAUDE.md hooks-daemon block is stale on main"]
        text = "\n".join(_run(handler, repo, _new()))
        assert "CLAUDE.md hooks-daemon block is stale on main" in text

    def test_disappears_once_the_condition_is_fixed(self, repo: Path) -> None:
        notices = ["block is stale"]
        handler = BranchSweepHandler()
        handler.claude_md_notices = lambda: list(notices)
        assert "block is stale" in "\n".join(_run(handler, repo, _new()))
        notices.clear()
        assert "block is stale" not in "\n".join(_run(handler, repo, _new()))

    def test_shown_even_when_the_branch_inventory_cannot_run(self, repo: Path) -> None:
        handler = BranchSweepHandler()
        handler.claude_md_notices = lambda: ["block is stale"]
        with patch(_BUILD, side_effect=BranchInventoryError("no repository")):
            assert "block is stale" in "\n".join(_run(handler, repo, _new()))

    def test_a_failing_provider_does_not_break_the_summary(self, repo: Path) -> None:
        def broken() -> list[str]:
            raise OSError("unreadable")

        handler = BranchSweepHandler()
        handler.claude_md_notices = broken
        assert _run(handler, repo, _new()) == []

    def test_silent_without_a_provider(self, repo: Path) -> None:
        assert _run(BranchSweepHandler(), repo, _new()) == []
