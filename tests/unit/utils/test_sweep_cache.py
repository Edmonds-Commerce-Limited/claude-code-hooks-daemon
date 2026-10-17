"""Tests for the SessionStart sweep result cache (Plan 00495 Task 2.6).

The cache must never serve a result for inputs that changed: every test of a
hit has a twin proving the matching edit forces a recompute.
"""

import json
import os
import subprocess
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.utils.sweep_cache import (
    SweepOutcome,
    SweepState,
    pending_context,
    run_cached_sweep,
    tree_fingerprint,
)
from claude_code_hooks_daemon.utils.secret_file_matching import resolve_configured_patterns
from tests.support.git_fixtures import git_setup_timeout

_NAME = "demo-sweep"
_LONG_WAIT = 30.0


def _protected_name() -> str:
    """A file name the live secret_file_guard config protects, read from that config."""
    return next(
        pattern for pattern in resolve_configured_patterns() if not set(pattern) & set("*?[")
    )


def _tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "A.md").write_text("alpha\n")
    return root


class TestTreeFingerprint:
    def test_unchanged_tree_has_a_stable_fingerprint(self, tmp_path: Path) -> None:
        root = _tree(tmp_path)
        assert tree_fingerprint(root, ["x"]) == tree_fingerprint(root, ["x"])

    def test_editing_a_file_changes_the_fingerprint(self, tmp_path: Path) -> None:
        root = _tree(tmp_path)
        before = tree_fingerprint(root, [])
        (root / "docs" / "A.md").write_text("alpha plus an edit\n")
        assert tree_fingerprint(root, []) != before

    def test_rewriting_a_file_with_same_size_changes_the_fingerprint(self, tmp_path: Path) -> None:
        root = _tree(tmp_path)
        target = root / "docs" / "A.md"
        before = tree_fingerprint(root, [])
        original_mtime_ns = target.stat().st_mtime_ns
        target.write_text("omega\n")
        os.utime(target, ns=(original_mtime_ns + 10**9, original_mtime_ns + 10**9))
        # Same size as "alpha\n"; only the mtime tells them apart.
        assert target.stat().st_size == len("alpha\n")
        assert tree_fingerprint(root, []) != before

    def test_adding_a_file_changes_the_fingerprint(self, tmp_path: Path) -> None:
        root = _tree(tmp_path)
        before = tree_fingerprint(root, [])
        (root / "docs" / "B.md").write_text("beta\n")
        assert tree_fingerprint(root, []) != before

    def test_deleting_a_link_target_changes_the_fingerprint(self, tmp_path: Path) -> None:
        """A dead link appears when a NON-markdown target is removed."""
        root = _tree(tmp_path)
        (root / "src").mkdir()
        target = root / "src" / "mod.py"
        target.write_text("x = 1\n")
        before = tree_fingerprint(root, [])
        target.unlink()
        assert tree_fingerprint(root, []) != before

    def test_extra_inputs_change_the_fingerprint(self, tmp_path: Path) -> None:
        root = _tree(tmp_path)
        assert tree_fingerprint(root, ["policy-a"]) != tree_fingerprint(root, ["policy-b"])

    @pytest.mark.parametrize("pruned", [".git", "untracked", "node_modules", "__pycache__"])
    def test_churn_in_a_pruned_directory_is_ignored(self, tmp_path: Path, pruned: str) -> None:
        root = _tree(tmp_path)
        (root / pruned).mkdir()
        before = tree_fingerprint(root, [])
        (root / pruned / "log.txt").write_text("noise\n")
        assert tree_fingerprint(root, []) == before

    def test_a_nested_directory_named_like_a_root_prune_is_not_pruned(self, tmp_path: Path) -> None:
        root = _tree(tmp_path)
        (root / "docs" / "untracked").mkdir()
        before = tree_fingerprint(root, [])
        (root / "docs" / "untracked" / "B.md").write_text("beta\n")
        assert tree_fingerprint(root, []) != before


def _git_project(tmp_path: Path) -> Path:
    """A git repository with a tracked doc, a source file and a gitignored build tree."""
    root = _tree(tmp_path)
    (root / "src").mkdir()
    (root / "src" / "mod.py").write_text("x = 1\n")
    (root / ".gitignore").write_text("target/\n")
    (root / "target").mkdir()
    for index in range(20):
        (root / "target" / f"artefact{index}.bin").write_text("built\n")
    subprocess.run(
        ["git", "init", str(root)], capture_output=True, check=True, timeout=git_setup_timeout()
    )
    return root


class TestGitAwareEnumeration:
    """Inside a git repository only tracked and non-ignored files are enumerated."""

    def test_a_gitignored_directory_is_never_enumerated(self, tmp_path: Path) -> None:
        root = _git_project(tmp_path)
        stated: list[str] = []
        original = Path.lstat

        def spy(self: Path) -> os.stat_result:
            stated.append(self.as_posix())
            return original(self)

        with patch.object(Path, "lstat", spy), patch("os.walk", side_effect=AssertionError):
            tree_fingerprint(root, [])

        assert stated
        assert not [path for path in stated if "/target/" in path]

    def test_editing_a_gitignored_file_does_not_move_the_fingerprint(self, tmp_path: Path) -> None:
        root = _git_project(tmp_path)
        before = tree_fingerprint(root, [])
        (root / "target" / "artefact0.bin").write_text("rebuilt with more bytes\n")
        (root / "target" / "new.bin").write_text("new\n")
        assert tree_fingerprint(root, []) == before

    def test_an_untracked_unignored_file_moves_the_fingerprint(self, tmp_path: Path) -> None:
        root = _git_project(tmp_path)
        before = tree_fingerprint(root, [])
        (root / "docs" / "B.md").write_text("beta\n")
        assert tree_fingerprint(root, []) != before

    def test_deleting_an_untracked_file_moves_the_fingerprint(self, tmp_path: Path) -> None:
        root = _git_project(tmp_path)
        before = tree_fingerprint(root, [])
        (root / "src" / "mod.py").unlink()
        assert tree_fingerprint(root, []) != before

    def test_deleting_a_tracked_file_moves_the_fingerprint(self, tmp_path: Path) -> None:
        root = _git_project(tmp_path)
        subprocess.run(
            ["git", "-C", str(root), "add", "src/mod.py"],
            capture_output=True,
            check=True,
            timeout=git_setup_timeout(),
        )
        before = tree_fingerprint(root, [])
        (root / "src" / "mod.py").unlink()
        assert tree_fingerprint(root, []) != before

    def test_pruned_locations_stay_pruned_inside_a_repository(self, tmp_path: Path) -> None:
        root = _git_project(tmp_path)
        (root / "untracked").mkdir()
        before = tree_fingerprint(root, [])
        (root / "untracked" / "log.txt").write_text("noise\n")
        assert tree_fingerprint(root, []) == before

    def test_a_protected_path_is_never_stated(self, tmp_path: Path) -> None:
        """Git's listing includes a protected file; it must not be touched at all."""
        root = _git_project(tmp_path)
        protected = _protected_name()
        (root / protected).write_text("key material\n")
        stated: list[str] = []
        original = Path.lstat

        def spy(self: Path) -> os.stat_result:
            stated.append(self.name)
            return original(self)

        with patch.object(Path, "lstat", spy):
            tree_fingerprint(root, [])

        assert "mod.py" in stated
        assert protected not in stated

    def test_editing_a_protected_file_does_not_move_the_fingerprint(self, tmp_path: Path) -> None:
        root = _git_project(tmp_path)
        protected = root / _protected_name()
        protected.write_text("key material\n")
        before = tree_fingerprint(root, [])
        protected.write_text("rotated key material\n")
        assert tree_fingerprint(root, []) == before


class TestRunCachedSweep:
    def test_miss_computes_and_caches(self, tmp_path: Path) -> None:
        calls: list[int] = []

        def compute() -> list[str]:
            calls.append(1)
            return ["finding"]

        outcome = run_cached_sweep(_NAME, tmp_path, "fp1", compute, _LONG_WAIT)

        assert outcome.state is SweepState.COMPUTED
        assert outcome.context == ["finding"]
        assert len(calls) == 1
        assert (tmp_path / "sweep-cache" / f"{_NAME}.json").is_file()

    def test_hit_serves_the_cache_without_computing(self, tmp_path: Path) -> None:
        run_cached_sweep(_NAME, tmp_path, "fp1", lambda: ["finding"], _LONG_WAIT)

        def must_not_run() -> list[str]:
            raise AssertionError("a hit must not recompute")

        outcome = run_cached_sweep(_NAME, tmp_path, "fp1", must_not_run, _LONG_WAIT)

        assert outcome.state is SweepState.CACHED
        assert outcome.context == ["finding"]

    def test_a_clean_result_is_cached_too(self, tmp_path: Path) -> None:
        run_cached_sweep(_NAME, tmp_path, "fp1", list, _LONG_WAIT)
        outcome = run_cached_sweep(_NAME, tmp_path, "fp1", lambda: ["new"], _LONG_WAIT)
        assert outcome.state is SweepState.CACHED
        assert outcome.context == []

    def test_changed_fingerprint_recomputes_and_never_serves_the_old_result(
        self, tmp_path: Path
    ) -> None:
        run_cached_sweep(_NAME, tmp_path, "fp1", lambda: ["old finding"], _LONG_WAIT)

        outcome = run_cached_sweep(_NAME, tmp_path, "fp2", lambda: ["new finding"], _LONG_WAIT)

        assert outcome.state is SweepState.COMPUTED
        assert outcome.context == ["new finding"]

    @pytest.mark.parametrize("content", ["not json at all", "[]", '{"fingerprint": 3}', ""])
    def test_an_unreadable_cache_file_is_a_miss(self, tmp_path: Path, content: str) -> None:
        cache_file = tmp_path / "sweep-cache" / f"{_NAME}.json"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text(content)

        outcome = run_cached_sweep(_NAME, tmp_path, "fp1", lambda: ["fresh"], _LONG_WAIT)

        assert outcome.state is SweepState.COMPUTED
        assert outcome.context == ["fresh"]
        assert json.loads(cache_file.read_text())["fingerprint"] == "fp1"

    def test_a_compute_error_inside_the_wait_propagates(self, tmp_path: Path) -> None:
        def boom() -> list[str]:
            raise RuntimeError("sweep exploded")

        with pytest.raises(RuntimeError, match="sweep exploded"):
            run_cached_sweep(_NAME, tmp_path, "fp1", boom, _LONG_WAIT)

        assert not (tmp_path / "sweep-cache" / f"{_NAME}.json").exists()

    def test_a_slow_sweep_is_pending_and_still_lands_in_the_cache(self, tmp_path: Path) -> None:
        release = threading.Event()
        finished = threading.Event()

        def slow() -> list[str]:
            release.wait(_LONG_WAIT)
            finished.set()
            return ["late finding"]

        outcome = run_cached_sweep(_NAME, tmp_path, "fp1", slow, 0.0)

        assert outcome.state is SweepState.PENDING
        assert outcome.context == []
        release.set()
        assert finished.wait(_LONG_WAIT)
        assert _poll_for_hit(tmp_path, "fp1") == ["late finding"]

    def test_pending_carries_the_last_known_result_for_labelled_display(
        self, tmp_path: Path
    ) -> None:
        run_cached_sweep(_NAME, tmp_path, "fp1", lambda: ["earlier finding"], _LONG_WAIT)
        release = threading.Event()

        def slow() -> list[str]:
            release.wait(_LONG_WAIT)
            return ["current finding"]

        outcome = run_cached_sweep(_NAME, tmp_path, "fp2", slow, 0.0)

        assert outcome.state is SweepState.PENDING
        assert outcome.context == []
        assert outcome.last_known == ["earlier finding"]
        release.set()
        _poll_for_hit(tmp_path, "fp2")

    def test_concurrent_requests_for_one_fingerprint_share_one_computation(
        self, tmp_path: Path
    ) -> None:
        release = threading.Event()
        calls: list[int] = []

        def slow() -> list[str]:
            calls.append(1)
            release.wait(_LONG_WAIT)
            return ["shared"]

        first = run_cached_sweep(_NAME, tmp_path, "fp1", slow, 0.0)
        second = run_cached_sweep(_NAME, tmp_path, "fp1", slow, 0.0)
        release.set()
        _poll_for_hit(tmp_path, "fp1")

        assert first.state is SweepState.PENDING
        assert second.state is SweepState.PENDING
        assert len(calls) == 1


class TestAdvisory:
    def test_a_current_result_is_its_own_context(self) -> None:
        outcome = SweepOutcome(SweepState.COMPUTED, ["finding"])
        assert outcome.advisory("Docs QA sweep", "hint") == ["finding"]

    def test_a_pending_result_is_the_pending_notice(self) -> None:
        outcome = SweepOutcome(SweepState.PENDING, [], ["old"])
        assert outcome.advisory("Docs QA sweep", "hint") == pending_context(
            "Docs QA sweep", ["old"], "hint"
        )


class TestPendingContext:
    def test_names_the_sweep_and_the_cli_hint(self) -> None:
        lines = pending_context("Docs QA sweep", [], "re-check: docs-qa --sweep")
        text = "\n".join(lines)
        assert "Docs QA sweep" in text
        assert "background" in text
        assert "re-check: docs-qa --sweep" in text

    def test_last_known_findings_are_labelled_as_possibly_stale(self) -> None:
        lines = pending_context("Docs QA sweep", ["old finding"], "hint")
        text = "\n".join(lines)
        assert "old finding" in text
        assert "may be out of date" in text

    def test_no_last_known_findings_adds_no_stale_block(self) -> None:
        text = "\n".join(pending_context("Docs QA sweep", [], "hint"))
        assert "out of date" not in text


def _poll_for_hit(cache_dir: Path, fingerprint: str) -> list[str]:
    """Wait for a background sweep to land its result in the cache file."""
    cache_file = cache_dir / "sweep-cache" / f"{_NAME}.json"
    for _ in range(int(_LONG_WAIT * 100)):
        if cache_file.is_file():
            payload = json.loads(cache_file.read_text())
            if payload["fingerprint"] == fingerprint:
                context: list[str] = payload["context"]
                return context
        threading.Event().wait(0.01)
    raise AssertionError("background sweep never reached the cache")
