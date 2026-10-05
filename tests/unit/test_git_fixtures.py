"""Tests for ``tests.support.git_fixtures``: the load-scaled budget for fixture git setup (N95)."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from tests.support.git_fixtures import GIT_SETUP_BASE_SECONDS, git_setup_timeout


class TestGitSetupTimeout:
    def test_the_idle_budget_is_well_above_the_hook_path_budget(self) -> None:
        assert GIT_SETUP_BASE_SECONDS > Timeout.GIT_CONTEXT

    def test_an_idle_host_gets_the_base_budget(self) -> None:
        got = git_setup_timeout(load_averages=(0.0, 0.0, 0.0), cpu_count=8)
        assert got == GIT_SETUP_BASE_SECONDS

    def test_a_loaded_host_gets_a_longer_budget(self) -> None:
        got = git_setup_timeout(load_averages=(24.0, 24.0, 0.0), cpu_count=8)
        assert got == pytest.approx(GIT_SETUP_BASE_SECONDS * 3)

    def test_the_host_is_read_when_nothing_is_passed(self) -> None:
        assert git_setup_timeout() >= GIT_SETUP_BASE_SECONDS


class TestSharedFixturesDoNotBorrowTheHookBudget:
    """Shared git fixtures must not run setup under the production 5 s budget."""

    @pytest.mark.parametrize("relative", ["tests/conftest.py", "tests/support/git_fixtures.py"])
    def test_shared_fixture_modules_do_not_use_the_hook_path_budget(self, relative: str) -> None:
        source = (Path(__file__).resolve().parents[2] / relative).read_text(encoding="utf-8")
        assert "Timeout.GIT_CONTEXT" not in source
