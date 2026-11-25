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
from tests.unit.core.test_branch_reject import _ledger_line

from claude_code_hooks_daemon.config.models import (
    BranchesConfig,
    HandlerConfig,
    HandlersConfig,
    fold_handler_aliases,
)
from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    Timeout,
)
from claude_code_hooks_daemon.core import Decision, branch_ladder
from claude_code_hooks_daemon.core.branch_creation import LABELS_RELATIVE_PATH, read_labels
from claude_code_hooks_daemon.core.branch_inventory import BranchInventoryError, build_inventory
from claude_code_hooks_daemon.core.branch_park import (
    BranchParkError,
    park_branch,
    read_park_record,
)
from claude_code_hooks_daemon.core.branch_reject import (
    RejectStore,
    append_ledger,
    build_digest,
    mark_digest_read,
)
from claude_code_hooks_daemon.handlers.session_start.branch_sweep import BranchSweepHandler

_ROOT = "claude_code_hooks_daemon.handlers.session_start.branch_sweep.ProjectContext.project_root"
_BUILD = "claude_code_hooks_daemon.handlers.session_start.branch_sweep.build_inventory"
_DIGEST = "claude_code_hooks_daemon.handlers.session_start.branch_sweep.build_digest"
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

    def test_an_ended_park_is_announced_once_at_session_start(self, repo: Path) -> None:
        _git(repo, "checkout", "-q", "-b", "waits")
        _commit(repo, "waits")
        _git(repo, "checkout", "-q", "main")
        park_branch(repo, "waits", reason="blocked on review", remote="origin")
        # A tip that does not descend from the parked commit ends the park.
        rewritten = subprocess.run(
            ["git", "commit-tree", "main^{tree}", "-p", "main", "-m", "rewritten"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            timeout=Timeout.GIT_COMMIT,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "t",
                "GIT_AUTHOR_EMAIL": "t@example.com",
                "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.com",
            },
        ).stdout.strip()
        _git(repo, "update-ref", "refs/heads/waits", rewritten)
        handler = BranchSweepHandler()
        assert "Park cleared: waits (blocked on review)" in _run(handler, repo, _new())
        assert "Park cleared: waits (blocked on review)" not in _run(handler, repo, _new())
        assert read_park_record(repo, "waits") is None

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


class TestPoolPressureReport:
    """Plan 00594 Task 4.2: session start lists every blocker plus the preflight report."""

    def _two_open(self, repo: Path) -> None:
        for name in ("a", "b"):
            _git(repo, "checkout", "-q", "-b", name)
            _commit(repo, name)
            _git(repo, "checkout", "-q", "main")

    def _handler(self, **pools: Any) -> BranchSweepHandler:
        handler = BranchSweepHandler()
        handler._branches = BranchesConfig.model_validate({"default": "main", **pools})
        return handler

    def test_lists_the_pool_blocker_with_its_fix(self, repo: Path) -> None:
        self._two_open(repo)
        text = "\n".join(_run(self._handler(wip={"cap": 1}), repo, _new()))
        assert "BRANCH POOLS" in text
        assert "Open work branches: 2 (cap 1;" in text
        assert "branch-park" in text

    def test_a_new_session_states_the_open_work_cap_once(self, repo: Path) -> None:
        self._two_open(repo)
        text = "\n".join(_run(self._handler(wip={"cap": 1}), repo, _new()))
        assert "Open work branches: 2 (cap 1;" in text
        assert "Open work: 2 of 1" not in text

    def test_lists_every_blocker_not_only_the_first(self, repo: Path) -> None:
        self._two_open(repo)
        _git(repo, "branch", "done", "main")
        handler = self._handler(wip={"cap": 1}, merged={"cap": 1})
        text = "\n".join(_run(handler, repo, _new()))
        assert "Open work branches" in text
        assert "Merged branches" in text

    def test_silent_when_no_pool_is_full(self, repo: Path) -> None:
        self._two_open(repo)
        text = "\n".join(_run(BranchSweepHandler(), repo, _new()))
        assert "BRANCH POOLS" not in text

    def test_names_no_rename_or_foreign_delete(self, repo: Path) -> None:
        self._two_open(repo)
        text = "\n".join(_run(self._handler(wip={"cap": 1}), repo, _new())).lower()
        assert "rename" not in text
        assert "branch -m" not in text


class TestPoolLadderAtSessionStart:
    """Plan 00619 Task 1.3: session start reports the warning ladder, below the block."""

    def _two_open(self, repo: Path) -> None:
        for name in ("a", "b"):
            _git(repo, "checkout", "-q", "-b", name)
            _commit(repo, name)
            _git(repo, "checkout", "-q", "main")

    def _handler(self, **pools: Any) -> BranchSweepHandler:
        handler = BranchSweepHandler()
        handler._branches = BranchesConfig.model_validate({"default": "main", **pools})
        return handler

    def test_a_pool_at_the_warn_level_is_reported_without_a_block(self, repo: Path) -> None:
        self._two_open(repo)
        handler = self._handler(wip={"cap": 3, "creation_grace": 0})
        text = "\n".join(_run(handler, repo, _new()))
        assert "BRANCH POOL WARNING" in text
        assert "2 of 3" in text
        assert "BRANCH POOLS (same report" not in text

    def test_a_failed_ladder_read_keeps_the_rest_of_the_summary(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_args: object, **_kwargs: object) -> object:
            raise BranchParkError("git config --get-regexp failed: timed out")

        _git(repo, "checkout", "-q", "-b", "lost")
        _commit(repo, "lost", days_ago=10)
        _git(repo, "checkout", "-q", "main")
        monkeypatch.setattr(branch_ladder, "read_pools", boom)
        text = "\n".join(_run(self._handler(wip={"cap": 3}), repo, _new()))
        assert "CONTAINED NOWHERE: lost" in text
        assert "BRANCH POOL" not in text

    def test_a_resumed_session_is_told_too(self, repo: Path, tmp_path: Path) -> None:
        self._two_open(repo)
        handler = self._handler(wip={"cap": 3, "creation_grace": 0})
        text = "\n".join(_run(handler, repo, _resume(tmp_path)))
        assert "BRANCH POOL WARNING" in text

    def test_silent_below_the_warn_level(self, repo: Path) -> None:
        self._two_open(repo)
        text = "\n".join(_run(self._handler(wip={"cap": 10}), repo, _new()))
        assert "BRANCH POOL" not in text


class TestRejectDigestCount:
    """Plan 00620 Task 2.3: the count of removals not yet digested, read-only, fail open."""

    def _ledger(self, repo: Path) -> Path:
        return repo / BranchesConfig().reject.ledger_path

    def _store(self, repo: Path) -> RejectStore:
        return RejectStore(repo / BranchesConfig().reject.state_dir)

    def _record(self, repo: Path, *branches: str) -> None:
        for branch in branches:
            append_ledger(self._ledger(repo), _ledger_line(branch=branch))

    def _count_lines(self, repo: Path) -> list[str]:
        with patch(_BUILD, side_effect=BranchInventoryError("no inventory")):
            return _run(BranchSweepHandler(), repo, _new())

    def test_the_count_shows_even_when_the_inventory_fails(self, repo: Path) -> None:
        self._record(repo, "gone-a", "gone-b")
        text = "\n".join(self._count_lines(repo))
        assert "2 removal(s)" in text
        assert "branch-reject digest" in text

    def test_nothing_undigested_is_silent(self, repo: Path) -> None:
        assert self._count_lines(repo) == []

    def test_entries_marked_read_are_not_counted(self, repo: Path) -> None:
        self._record(repo, "gone")
        config = BranchesConfig().reject
        store = self._store(repo)
        digest = build_digest(self._ledger(repo), store, now=time.time(), config=config)
        mark_digest_read(store, digest, now=time.time())
        assert self._count_lines(repo) == []

    def test_a_damaged_ledger_is_loud(self, repo: Path) -> None:
        ledger = self._ledger(repo)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text("not json\n", encoding="utf-8")
        text = "\n".join(self._count_lines(repo))
        assert "unreadable" in text
        assert "branch-reject digest" in text

    @pytest.mark.parametrize("target", ["ledger", "watermark"])
    def test_bytes_that_are_not_utf8_are_loud(self, repo: Path, target: str) -> None:
        self._record(repo, "gone")
        path = self._ledger(repo) if target == "ledger" else self._store(repo).digest_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xfe\n")
        assert "unreadable" in "\n".join(self._count_lines(repo))

    def test_an_unexpected_failure_is_loud_and_never_raises(self, repo: Path) -> None:
        self._record(repo, "gone")
        with patch(_DIGEST, side_effect=OSError("disk gone")):
            text = "\n".join(self._count_lines(repo))
        assert "unreadable" in text

    def test_a_damaged_watermark_is_loud(self, repo: Path) -> None:
        self._record(repo, "gone")
        path = self._store(repo).digest_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{", encoding="utf-8")
        assert "unreadable" in "\n".join(self._count_lines(repo))

    def test_outside_a_repository_it_is_silent(self, tmp_path: Path) -> None:
        ledger = self._ledger(tmp_path)
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text("not json\n", encoding="utf-8")
        assert self._count_lines(tmp_path) == []

    def test_listing_writes_nothing(self, repo: Path) -> None:
        self._record(repo, "gone")
        self._count_lines(repo)
        assert not self._store(repo).digest_path.exists()

    def test_a_resumed_session_is_told_too(self, repo: Path, tmp_path: Path) -> None:
        self._record(repo, "gone")
        with patch(_BUILD, side_effect=BranchInventoryError("no inventory")):
            text = "\n".join(_run(BranchSweepHandler(), repo, _resume(tmp_path)))
        assert "1 removal(s)" in text

    def test_claude_md_names_the_digest_count(self) -> None:
        text = BranchSweepHandler().get_claude_md() or ""
        assert "branch-reject digest" in text
