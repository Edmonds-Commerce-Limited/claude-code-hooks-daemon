"""The shared body of the two branch pool ladder handlers (Plan 00619)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.support.ladder_repo import add_open_branches, init_repo

from claude_code_hooks_daemon.config.models import BranchesConfig, BranchWipConfig
from claude_code_hooks_daemon.core.branch_ladder import LadderThrottle, PressureCache
from claude_code_hooks_daemon.handlers.utils.branch_ladder_surface import BranchLadderSurface

CONFIG = BranchesConfig(wip=BranchWipConfig(cap=10, creation_grace=2, count_remote=False))


def _surface(root: Path | None) -> BranchLadderSurface:
    surface = BranchLadderSurface()
    surface._branches = CONFIG
    surface._project_root_override = root
    surface._throttle = LadderThrottle()
    surface._cache = PressureCache(ttl=0.0)
    return surface


class TestBranchLadderSurface:
    def test_due_lines_are_collected_for_a_full_pool(self, tmp_path: Path) -> None:
        root = init_repo(tmp_path)
        add_open_branches(root, 11)
        surface = _surface(root)
        assert surface.ladder_matches({"session_id": "s"}) is True
        assert "11 of 12" in "\n".join(surface._due)

    def test_a_non_string_session_id_is_treated_as_no_session(self, tmp_path: Path) -> None:
        root = init_repo(tmp_path)
        add_open_branches(root, 9)
        assert _surface(root).ladder_matches({"session_id": 7}) is True

    def test_any_error_is_silence_and_clears_the_due_lines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        surface = _surface(init_repo(tmp_path))
        surface._due = ["stale"]

        def explode() -> Path:
            raise RuntimeError("no")

        monkeypatch.setattr(surface, "_project_root", explode)
        assert surface.ladder_matches({}) is False
        assert surface._due == []

    def test_the_project_root_falls_back_to_the_working_directory(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.chdir(tmp_path)
        assert _surface(None)._project_root() == Path.cwd()
