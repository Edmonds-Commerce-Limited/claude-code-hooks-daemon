"""The warning ladder is context only: no failure of its git read may deny anything.

Plan 00619 review round: a failed park-record read (``BranchParkError``, which is
neither a ``RuntimeError`` nor an ``OSError``) escaped the ladder, and under
``daemon.strict_mode`` the handler chain turned the escape into a terminal deny of
every tool call and every prompt. The ladder must degrade to silence instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.config.models import BranchesConfig, BranchWipConfig
from claude_code_hooks_daemon.core import branch_creation, branch_ladder
from claude_code_hooks_daemon.core.branch_ladder import (
    LadderThrottle,
    PressureCache,
    ladder_notice,
    pool_pressures,
)
from claude_code_hooks_daemon.core.branch_park import BranchParkError
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.branch_pool_pressure_advisor import (
    BranchPoolPressureAdvisorHandler,
)
from claude_code_hooks_daemon.handlers.user_prompt_submit.branch_pool_pressure_prompt import (
    BranchPoolPressurePromptHandler,
)
from tests.support.ladder_repo import add_open_branches, init_repo

CONFIG = BranchesConfig(wip=BranchWipConfig(cap=10, creation_grace=2, count_remote=False))
TOOL: dict[str, Any] = {
    "session_id": "s1",
    "hook_event_name": "PreToolUse",
    "tool_name": "Read",
    "tool_input": {"file_path": "/x"},
}
PROMPT: dict[str, Any] = {"session_id": "s1", "hook_event_name": "UserPromptSubmit", "prompt": "hi"}


def _boom(_repo: Path) -> object:
    raise BranchParkError("git config --get-regexp failed: timed out")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = init_repo(tmp_path)
    add_open_branches(root, 11)
    return root


@pytest.fixture
def failing_park_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(branch_creation, "read_park_records", _boom)


class TestTypedReading:
    """A failed read is a typed result, never None, and still never raises."""

    def test_a_failed_read_is_flagged_unreadable_with_no_pressures(
        self, repo: Path, failing_park_read: None
    ) -> None:
        reading = branch_ladder.try_pool_pressures(repo, CONFIG, {})
        assert reading.unreadable is True
        assert reading.pressures == ()

    def test_a_good_read_is_readable_and_carries_the_pressures(self, repo: Path) -> None:
        reading = branch_ladder.try_pool_pressures(repo, CONFIG, {})
        assert reading.unreadable is False
        assert len(reading.pressures) == 1

    def test_a_failed_read_is_cached_for_the_failure_window(
        self, repo: Path, failing_park_read: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cache = PressureCache(ttl=10.0, failure_ttl=60.0)
        assert cache.get(repo, CONFIG, {}, clock=lambda: 0.0) == []
        calls: list[int] = []
        real = branch_ladder.try_pool_pressures

        def counted(*args: Any, **kwargs: Any) -> Any:
            calls.append(1)
            return real(*args, **kwargs)

        monkeypatch.setattr(branch_ladder, "try_pool_pressures", counted)
        assert cache.get(repo, CONFIG, {}, clock=lambda: 30.0) == []
        assert calls == []
        assert cache.get(repo, CONFIG, {}, clock=lambda: 61.0) == []
        assert calls == [1]


class TestLadderFailsOpen:
    def test_pool_pressures_is_silent_when_the_park_read_fails(
        self, repo: Path, failing_park_read: None
    ) -> None:
        assert pool_pressures(repo, CONFIG, {}) == []

    def test_ladder_notice_is_silent_when_the_park_read_fails(
        self, repo: Path, failing_park_read: None
    ) -> None:
        assert ladder_notice(repo, CONFIG, session_id=None, throttle=None) == []

    def test_ladder_notice_is_silent_on_any_unexpected_error(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(*_args: object, **_kwargs: object) -> object:
            raise ValueError("unexpected")

        monkeypatch.setattr(branch_ladder, "read_labels", explode)
        assert ladder_notice(repo, CONFIG, session_id=None, throttle=None) == []


def _handler(cls: type, repo: Path) -> Any:
    handler = cls()
    handler._branches = CONFIG
    handler._project_root_override = repo
    handler._throttle = LadderThrottle()
    handler._cache = PressureCache(ttl=0.0)
    return handler


@pytest.mark.parametrize(
    ("cls", "payload"),
    [
        (BranchPoolPressureAdvisorHandler, TOOL),
        (BranchPoolPressurePromptHandler, PROMPT),
    ],
)
class TestHandlersNeverDeny:
    @pytest.mark.parametrize("strict", [True, False])
    def test_a_failed_branch_read_allows_through_the_chain(
        self,
        cls: type,
        payload: dict[str, Any],
        strict: bool,
        repo: Path,
        failing_park_read: None,
    ) -> None:
        chain = HandlerChain()
        chain.add(_handler(cls, repo))
        result = chain.execute(payload, strict_mode=strict).result
        assert result.decision == Decision.ALLOW

    def test_matches_never_raises_whatever_the_surface_does(
        self, cls: type, payload: dict[str, Any], repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode() -> Path:
            raise RuntimeError("anything at all")

        handler = _handler(cls, repo)
        monkeypatch.setattr(handler, "_project_root", explode)
        assert handler.matches(payload) is False
        assert handler._due == []

    def test_a_working_read_still_warns_through_the_chain(
        self, cls: type, payload: dict[str, Any], repo: Path
    ) -> None:
        chain = HandlerChain()
        chain.add(_handler(cls, repo))
        result = chain.execute(payload, strict_mode=True).result
        assert result.decision == Decision.ALLOW
        assert "11 of 12" in "\n".join(result.context or [])


class TestFailureIsCached:
    def test_a_failed_reading_is_not_retried_within_the_ttl(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[int] = []

        def failing(*_args: object, **_kwargs: object) -> object:
            calls.append(1)
            raise BranchParkError("timed out")

        monkeypatch.setattr(branch_creation, "read_park_records", failing)
        now = [100.0]
        cache = PressureCache(ttl=10.0)
        for _ in range(5):
            assert cache.get(repo, CONFIG, {}, clock=lambda: now[0]) == []
            now[0] += 1.0
        assert len(calls) == 1
