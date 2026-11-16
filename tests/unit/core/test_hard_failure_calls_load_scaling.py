"""Git calls that gate a hard failure follow host load (Plan 00474 N622).

Class: a hard failure gated on a fixed wall-clock budget for a git call whose
duration follows host load or repository size. Each call below is a base scaled
by load and bounded by a ceiling its own caller can afford, and an idle host
keeps the base.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import branch_keep, branch_park, claude_md_injector
from claude_code_hooks_daemon.daemon import branch_safety
from claude_code_hooks_daemon.utils import protected_file_index
from claude_code_hooks_daemon.utils.git_repo import run_git

_SATURATED = (700.0, 700.0, 700.0)
_IDLE = (0.0, 0.0, 0.0)
_LOAD_PATH = "claude_code_hooks_daemon.utils.load_scaling.os.getloadavg"


def _ok(args: tuple[str, ...]) -> Any:
    return subprocess.CompletedProcess(["git", *args], 0, "", "")


def _recorder(sink: dict[str, float]) -> Any:
    def fake_run_git(cwd: Path, *args: str, timeout: float = 0, **_: Any) -> Any:
        sink[args[0]] = timeout
        return _ok(args)

    return fake_run_git


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


class TestAutoCommit:
    @pytest.mark.parametrize(
        ("load", "expected"),
        [(_SATURATED, Timeout.GIT_COMMIT_MAX), (_IDLE, Timeout.GIT_COMMIT)],
    )
    def test_add_and_commit_follow_load(
        self, tmp_path: Path, load: tuple[float, float, float], expected: float
    ) -> None:
        _git(tmp_path, "init", "-q", "-b", "main")
        _git(tmp_path, "config", "user.email", "t@t.t")
        _git(tmp_path, "config", "user.name", "t")
        (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
        _git(tmp_path, "add", "-A")
        _git(tmp_path, "commit", "-q", "-m", "init")
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("hello\n", encoding="utf-8")

        seen: dict[str, float] = {}
        real_run_git = run_git

        def recording(
            cwd: Path, *args: str, timeout: float = Timeout.GIT_CONTEXT, **kw: Any
        ) -> Any:
            if timeout > Timeout.GIT_CONTEXT:
                seen[args[0]] = timeout
            return real_run_git(cwd, *args, timeout=timeout, **kw)

        with (
            patch.object(claude_md_injector, "run_git", recording),
            patch(_LOAD_PATH, return_value=load),
        ):
            claude_md_injector.ClaudeMdInjector._auto_commit_if_dirty(claude_md)
        assert seen == {"add": expected, "commit": expected}


class TestParkAndKeepRemoteCalls:
    def test_keep_fetch_and_push_scale_to_the_ceiling(self, tmp_path: Path) -> None:
        seen: dict[str, float] = {}
        with (
            patch.object(branch_keep, "run_git", _recorder(seen)),
            patch(_LOAD_PATH, return_value=_SATURATED),
        ):
            assert branch_keep.fetch_keeps(tmp_path, "origin") is None
            assert branch_keep._push(tmp_path, "origin") is None
        assert seen == {
            "fetch": Timeout.GIT_FETCH_SESSION_MAX,
            "push": Timeout.GIT_FETCH_SESSION_MAX,
        }

    def test_keep_calls_keep_their_base_on_an_idle_host(self, tmp_path: Path) -> None:
        seen: dict[str, float] = {}
        with (
            patch.object(branch_keep, "run_git", _recorder(seen)),
            patch(_LOAD_PATH, return_value=_IDLE),
        ):
            branch_keep.fetch_keeps(tmp_path, "origin")
        assert seen == {"fetch": Timeout.GIT_FETCH_SESSION}

    def test_a_remote_only_park_push_scales_to_the_ceiling(self, tmp_path: Path) -> None:
        seen: dict[str, float] = {}
        with (
            patch.object(branch_park, "run_git", _recorder(seen)),
            patch.object(branch_park, "_write_park_commit", return_value="n" * 40),
            patch.object(branch_park, "_refuse_same_reason"),
            patch(_LOAD_PATH, return_value=_SATURATED),
        ):
            branch_park._park_remote_only(
                tmp_path, "b", "origin", "refs/remotes/origin/b", "o" * 40, "why", clear=False
            )
        assert seen["push"] == Timeout.GIT_FETCH_SESSION_MAX


class TestRemoteBranchDelete:
    def test_the_lease_push_scales_to_the_ceiling(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.core import branch_cleanup

        seen: dict[str, float] = {}
        with (
            patch.object(branch_cleanup, "run_git", _recorder(seen)),
            patch(_LOAD_PATH, return_value=_SATURATED),
        ):
            branch_cleanup._push_deletes(tmp_path, "origin", {"b": "a" * 40})
        assert seen == {"push": Timeout.GIT_FETCH_SESSION_MAX}


class TestBranchSafetyWalks:
    def test_the_default_walk_budget_scales_to_the_ceiling(self, tmp_path: Path) -> None:
        seen: dict[str, float] = {}
        with (
            patch.object(branch_safety, "run_git", _recorder(seen)),
            patch(_LOAD_PATH, return_value=_SATURATED),
        ):
            branch_safety._git(tmp_path, "rev-list", "--objects", "x")
            assert branch_safety.cherry_unique_shas(tmp_path, "a", "b") == []
        assert seen == {
            "rev-list": Timeout.GIT_BRANCH_SAFETY_MAX,
            "cherry": Timeout.GIT_BRANCH_SAFETY_MAX,
        }

    def test_an_idle_host_keeps_the_base(self, tmp_path: Path) -> None:
        seen: dict[str, float] = {}
        with (
            patch.object(branch_safety, "run_git", _recorder(seen)),
            patch(_LOAD_PATH, return_value=_IDLE),
        ):
            branch_safety._git(tmp_path, "rev-list", "x")
        assert seen == {"rev-list": Timeout.GIT_BRANCH_SAFETY}

    def test_an_explicit_timeout_is_honoured(self, tmp_path: Path) -> None:
        seen: dict[str, float] = {}
        with (
            patch.object(branch_safety, "run_git", _recorder(seen)),
            patch(_LOAD_PATH, return_value=_SATURATED),
        ):
            branch_safety._git(tmp_path, "rev-list", "x", timeout=7)
        assert seen == {"rev-list": 7}


class TestProtectedIndexBuild:
    def test_the_index_build_scales_to_the_ceiling(self, tmp_path: Path) -> None:
        captured: dict[str, float] = {}

        def fake_scan(root: Path, *, timeout: float, pathspecs: Any) -> None:
            captured["timeout"] = timeout

        with (
            patch("claude_code_hooks_daemon.utils.git_file_states.scan_git_file_states", fake_scan),
            patch(_LOAD_PATH, return_value=_SATURATED),
        ):
            assert protected_file_index.build_index(tmp_path, ("notes/*.txt",)) is None
        assert captured["timeout"] == Timeout.INDEX_BUILD_GIT_MAX


class TestCeilingsAreAboveTheirBases:
    @pytest.mark.parametrize(
        ("base", "ceiling"),
        [
            (Timeout.GIT_COMMIT, Timeout.GIT_COMMIT_MAX),
            (Timeout.GIT_FETCH_SESSION, Timeout.GIT_FETCH_SESSION_MAX),
            (Timeout.GIT_BRANCH_SAFETY, Timeout.GIT_BRANCH_SAFETY_MAX),
            (Timeout.INDEX_BUILD_GIT, Timeout.INDEX_BUILD_GIT_MAX),
        ],
    )
    def test_ceiling_exceeds_base(self, base: float, ceiling: float) -> None:
        assert ceiling > base
