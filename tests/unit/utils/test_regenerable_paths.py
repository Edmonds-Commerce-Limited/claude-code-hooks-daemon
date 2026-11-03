"""Tests for the regenerable-store matcher (Plan 00558 Task 3.1)."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.regenerable_paths import (
    DEFAULT_REGENERABLE_STORES,
    NEVER_REGENERABLE,
    is_regenerable,
    never_regenerable_violations,
)


class TestDefaults:
    @pytest.mark.parametrize(
        "entry",
        [
            "untracked/venv-x-py313/",
            "untracked/qa/",
            "untracked/qa/report.json",
            "untracked/docs-qa/",
            "untracked/branch-inventory/cache.json",
            "untracked/daemon-1234.sock",
            "untracked/events-today.jsonl",
            "src/pkg/__pycache__/",
            "src/pkg/__pycache__/mod.pyc",
            ".pytest_cache/",
            ".mypy_cache/",
            ".ruff_cache/",
            ".claude/hooks-daemon/",
            ".claude/hooks-daemon/venv/bin/python",
            "src/claude_code_hooks_daemon.egg-info/",
            "untracked/.venv-bootstrap-py313/",
            "untracked/.venv-bootstrap.log",
            "untracked/lsp-venv/",
            "untracked/repair.log",
            "untracked/repair.txt",
            ".coverage",
            "untracked/.python-cmd-cache",
            "untracked/context-sidecar/",
            "untracked/logs/",
            "untracked/logs/daemon.log",
            "untracked/acceptance/",
            ".CLAUDE.md.pre-inject",
        ],
    )
    def test_default_stores_are_regenerable(self, entry: str) -> None:
        assert is_regenerable(entry, DEFAULT_REGENERABLE_STORES) is True

    @pytest.mark.parametrize(
        "entry",
        [
            "untracked/scratch/",
            "untracked/notes.md",
            "untracked/",
            "secret.env",
            "untracked/qa",
            "untracked/lsp-venv",
            "src/x.egg-info",
            ".claude/settings.local.json",
            "nested/untracked/qa/",
        ],
    )
    def test_anything_else_blocks(self, entry: str) -> None:
        assert is_regenerable(entry, DEFAULT_REGENERABLE_STORES) is False

    def test_defaults_never_cover_scratch(self) -> None:
        assert never_regenerable_violations(DEFAULT_REGENERABLE_STORES) == []


class TestPatterns:
    def test_a_slashless_name_matches_at_any_depth(self) -> None:
        assert is_regenerable("a/b/build/", ["build/"]) is True
        assert is_regenerable("a/b/build/x.o", ["build/"]) is True

    def test_an_anchored_pattern_matches_only_from_the_root(self) -> None:
        assert is_regenerable("cache/x", ["cache/"]) is True
        assert is_regenerable("a/b/c/", ["a/b/"]) is True
        assert is_regenerable("z/a/b/", ["a/b/"]) is False

    def test_a_file_pattern_matches_a_file_or_a_directory(self) -> None:
        assert is_regenerable("logs/run.log", ["logs/*.log"]) is True
        assert is_regenerable("logs/run.log/", ["logs/*.log"]) is True

    def test_star_never_crosses_a_slash(self) -> None:
        assert is_regenerable("a/b/c", ["a/*"]) is True
        assert is_regenerable("a/b/c", ["*/c"]) is False

    def test_a_leading_slash_anchors(self) -> None:
        assert is_regenerable("build/", ["/build/"]) is True
        assert is_regenerable("x/build/", ["/build/"]) is False

    def test_an_empty_list_keeps_everything(self) -> None:
        assert is_regenerable("untracked/qa/", []) is False


class TestNeverRegenerable:
    @pytest.mark.parametrize(
        "pattern",
        ["untracked/scratch/", "untracked/", "untracked/*/", "*", "untracked/s*", "scratch/"],
    )
    def test_a_pattern_covering_scratch_is_reported(self, pattern: str) -> None:
        assert never_regenerable_violations(["untracked/qa/", pattern]) == [pattern]

    def test_the_protected_path_is_scratch(self) -> None:
        assert NEVER_REGENERABLE == "untracked/scratch/"
