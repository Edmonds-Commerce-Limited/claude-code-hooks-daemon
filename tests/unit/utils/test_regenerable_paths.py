"""Tests for the regenerable-store matcher (Plan 00558 Task 3.1)."""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.regenerable_paths import (
    DEFAULT_REGENERABLE_STORES,
    NEVER_REGENERABLE,
    is_regenerable,
    lock_regenerated_dirs,
    never_regenerable_violations,
    under_any,
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
            "untracked/spend-ledger/",
            "untracked/spend-ledger/00000000-0000-0000-0000-000000000000/unmeasured/x.json",
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


def _no_read(_path: str) -> str | None:
    return None


class TestLockRegeneratedDirs:
    def test_nested_composer_pair_yields_vendor_dir(self) -> None:
        committed = ["app/api/composer.json", "app/api/composer.lock", "app/api/src/a.php"]
        assert "app/api/vendor/" in lock_regenerated_dirs(committed, _no_read)

    def test_manifest_without_lock_yields_nothing(self) -> None:
        assert lock_regenerated_dirs(["app/composer.json"], _no_read) == ()

    def test_lock_without_manifest_yields_nothing(self) -> None:
        assert lock_regenerated_dirs(["app/composer.lock"], _no_read) == ()

    @pytest.mark.parametrize("lock", ["package-lock.json", "yarn.lock", "pnpm-lock.yaml"])
    def test_node_modules_at_depth_three_with_any_lock(self, lock: str) -> None:
        committed = ["a/b/c/package.json", f"a/b/c/{lock}"]
        assert lock_regenerated_dirs(committed, _no_read) == ("a/b/c/node_modules/",)

    @pytest.mark.parametrize(
        ("files", "expected"),
        [
            (["Gemfile", "Gemfile.lock"], "vendor/bundle/"),
            (["Cargo.toml", "Cargo.lock"], "target/"),
            (["pyproject.toml", "uv.lock"], ".venv/"),
            (["pyproject.toml", "poetry.lock"], ".venv/"),
        ],
    )
    def test_other_managers(self, files: list[str], expected: str) -> None:
        assert expected in lock_regenerated_dirs(files, _no_read)

    def test_composer_dirs_are_read_from_the_committed_manifest(self) -> None:
        def read(path: str) -> str | None:
            assert path == "web/composer.json"
            return '{"config": {"bin-dir": "bin", "vendor-dir": "libs"}}'

        dirs = lock_regenerated_dirs(["web/composer.json", "web/composer.lock"], read)
        assert "web/bin/" in dirs
        assert "web/libs/" in dirs

    @pytest.mark.parametrize(
        "text", ["not json", "[]", '{"config": {"bin-dir": "../x", "vendor-dir": 3}}']
    )
    def test_odd_composer_config_falls_back_to_defaults(self, text: str) -> None:
        committed = ["composer.json", "composer.lock"]
        assert lock_regenerated_dirs(committed, lambda _p: text) == ("vendor/", "vendor/bin/")

    def test_a_dir_under_the_never_regenerable_path_is_dropped(self) -> None:
        committed = [f"{NEVER_REGENERABLE}composer.json", f"{NEVER_REGENERABLE}composer.lock"]
        assert lock_regenerated_dirs(committed, _no_read) == ()

    def test_a_dir_with_a_committed_file_inside_is_dropped(self) -> None:
        committed = ["composer.json", "composer.lock", "vendor/keep.txt"]
        assert lock_regenerated_dirs(committed, _no_read) == ("vendor/bin/",)


class TestUnderAny:
    def test_prefix_match_on_directory_boundary(self) -> None:
        assert under_any("a/vendor/x/y.php", ["a/vendor/"])
        assert under_any("a/vendor/", ["a/vendor/"])
        assert not under_any("a/vendors/", ["a/vendor/"])
        assert not under_any("b/vendor/", ["a/vendor/"])
