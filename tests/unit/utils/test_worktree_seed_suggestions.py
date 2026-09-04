"""Tests for worktree seed suggestions and config drift (Plan 00267 Phase 4).

No shipped default can know which git-ignored local files a given project has,
so suggestions are derived by scanning the repository. Git itself decides what
is ignored — reimplementing ``.gitignore`` semantics would drift from the tool
that actually governs the answer.

Suggestions are REPORTED, never written. The project owns its config.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core.worktree_seed import (
    DEFAULT_SEED_MODE,
    SEED_MODE_COPY,
    SEED_MODE_SYMLINK,
    SeedEntry,
)
from claude_code_hooks_daemon.utils.worktree_seed_suggestions import (
    _EXCLUDED_DIRECTORY_NAMES,
    diff_seed_config,
    suggest_seed_entries,
)


def _init_repo(root: Path, gitignore: str) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    (root / ".gitignore").write_text(gitignore, encoding="utf-8")
    (root / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    _init_repo(
        root,
        # The non-config entries at the end mirror what a real scan of this
        # repository turns up alongside the genuine candidates, so the
        # exclusion side of the heuristics is exercised against real shapes.
        ".env.local\n.env.test.local\nsettings.local.json\n"
        "node_modules/\ndist/\n*.log\n"
        "*.env\n*.secret\n*.lock\ncoverage.xml\n.coverage\n",
    )
    return root


class TestSuggestSeedEntries:
    def test_clean_repo_suggests_nothing(self, repo: Path) -> None:
        assert suggest_seed_entries(repo) == []

    def test_ignored_env_file_is_suggested(self, repo: Path) -> None:
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")

        assert suggest_seed_entries(repo) == [SeedEntry(path=".env.local", mode=DEFAULT_SEED_MODE)]

    def test_several_ignored_local_files_are_all_suggested(self, repo: Path) -> None:
        (repo / ".env.local").write_text("A=1\n", encoding="utf-8")
        (repo / ".env.test.local").write_text("B=2\n", encoding="utf-8")
        (repo / "settings.local.json").write_text("{}\n", encoding="utf-8")

        suggested = {entry.path for entry in suggest_seed_entries(repo)}
        assert suggested == {".env.local", ".env.test.local", "settings.local.json"}

    def test_tracked_file_is_never_suggested(self, repo: Path) -> None:
        """Git already provides tracked files in every worktree checkout."""
        tracked = repo / ".env.example"
        tracked.write_text("SECRET=\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", ".env.example"], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "add example"], check=True)

        assert suggest_seed_entries(repo) == []

    def test_untracked_but_unignored_file_is_not_suggested(self, repo: Path) -> None:
        """Not ignored means git will not withhold it — nothing to seed.

        The name matches a local-config shape deliberately: the fixture ignores
        ``settings.local.json`` exactly, not by glob, so this sibling is the
        candidate shape WITHOUT the ignored status, which is the one thing under
        test here.
        """
        (repo / "settings.local.yaml").write_text("x: 1\n", encoding="utf-8")
        assert suggest_seed_entries(repo) == []

    def test_ignored_but_uninteresting_file_is_not_suggested(self, repo: Path) -> None:
        """Being ignored is necessary, not sufficient — a log is not local config."""
        (repo / "debug.log").write_text("noise\n", encoding="utf-8")
        assert suggest_seed_entries(repo) == []

    def test_dependency_and_build_directories_are_excluded(self, repo: Path) -> None:
        for excluded in ("node_modules", "dist"):
            directory = repo / excluded
            directory.mkdir()
            (directory / ".env.local").write_text("nested\n", encoding="utf-8")

        assert suggest_seed_entries(repo) == []

    def test_a_declared_vendor_dir_is_excluded(self, repo: Path) -> None:
        """Plan 00331: the exclusion set was the canonical constant unioned
        with seed's own extras at module scope, so a declared
        `layout.vendor_dirs` never reached it -- and a vendored ansible role
        tree (commonly gitignored) got suggested as a seed candidate.

        `roles` is not in the canonical set, so a test using `node_modules`
        or `dist` (above) would pass without the fix.
        """
        directory = repo / "roles"
        directory.mkdir()
        (directory / ".env.local").write_text("nested\n", encoding="utf-8")

        assert suggest_seed_entries(repo, vendor_dirs=frozenset({"roles"})) == []

    def test_an_undeclared_dir_of_that_name_is_still_suggested(self, repo: Path) -> None:
        """The exclusion must come from the DECLARATION, not from the name."""
        directory = repo / "roles"
        directory.mkdir()
        (directory / ".env.local").write_text("nested\n", encoding="utf-8")

        assert [entry.path for entry in suggest_seed_entries(repo)] == ["roles/.env.local"]

    def test_a_declaration_does_not_displace_the_built_ins(self, repo: Path) -> None:
        """Seed's own extras (`.git`, caches, `untracked`) are not part of the
        vendor axis and must survive a `mode: replace` vendor declaration."""
        directory = repo / "node_modules"
        directory.mkdir()
        (directory / ".env.local").write_text("nested\n", encoding="utf-8")

        entries = suggest_seed_entries(repo, vendor_dirs=frozenset({"node_modules", "roles"}))
        assert entries == []

    def test_excluded_directory_names_has_exact_membership(self) -> None:
        """Plan 00288 Task 3.2: core plus seed's own tool-cache/VCS/daemon
        extras (measurement doc §3)."""
        assert _EXCLUDED_DIRECTORY_NAMES == frozenset(
            {
                # Core (11 names).
                "node_modules",
                "vendor",
                "third_party",
                "dist",
                "build",
                ".build",
                "target",
                ".next",
                ".venv",
                "venv",
                "coverage",
                # Seed's own domain extras.
                ".git",
                ".mypy_cache",
                ".pytest_cache",
                ".ruff_cache",
                ".tox",
                "__pycache__",
                "untracked",
            }
        )

    def test_a_prefixed_env_file_is_suggested(self, repo: Path) -> None:
        """A dotfile is not the only shape a local env file takes. This repo's
        own ``.claude/hooks-daemon.env`` ends in ``.env`` without starting with
        it, and the first pass of these heuristics missed it — found by running
        the reporter against this repository rather than against a fixture."""
        (repo / "app.env").write_text("A=1\n", encoding="utf-8")

        assert suggest_seed_entries(repo) == [SeedEntry(path="app.env", mode=DEFAULT_SEED_MODE)]

    def test_a_secret_file_is_suggested(self, repo: Path) -> None:
        """A worktree missing a secret/word-list file does not fail loudly — the
        guard that reads it goes silently inert, which is worse."""
        (repo / "block-words.secret").write_text("word\n", encoding="utf-8")

        assert suggest_seed_entries(repo) == [
            SeedEntry(path="block-words.secret", mode=DEFAULT_SEED_MODE)
        ]

    def test_lock_and_coverage_artefacts_are_still_not_suggested(self, repo: Path) -> None:
        """Guards the widened patterns above: the same real-repository scan also
        turned up a scheduler lock and coverage output, and neither is config."""
        for artefact in ("scheduled_tasks.lock", "coverage.xml", ".coverage"):
            (repo / artefact).write_text("x\n", encoding="utf-8")

        assert suggest_seed_entries(repo) == []

    def test_suggestions_use_the_default_mode(self, repo: Path) -> None:
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")
        assert suggest_seed_entries(repo)[0].mode == DEFAULT_SEED_MODE

    def test_suggestions_are_ordered_deterministically(self, repo: Path) -> None:
        (repo / "settings.local.json").write_text("{}\n", encoding="utf-8")
        (repo / ".env.local").write_text("A=1\n", encoding="utf-8")
        (repo / ".env.test.local").write_text("B=2\n", encoding="utf-8")

        paths = [entry.path for entry in suggest_seed_entries(repo)]
        assert paths == sorted(paths)

    def test_a_non_git_directory_suggests_nothing(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        (plain / ".env.local").write_text("SECRET=1\n", encoding="utf-8")

        assert suggest_seed_entries(plain) == []


class TestDiffSeedConfig:
    def test_no_config_and_no_candidates_is_clean(self, repo: Path) -> None:
        drift = diff_seed_config(repo, [])
        assert not drift.has_drift
        assert drift.unconfigured == ()
        assert drift.missing == ()

    def test_candidate_absent_from_config_is_reported(self, repo: Path) -> None:
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")

        drift = diff_seed_config(repo, [])

        assert drift.has_drift
        assert [entry.path for entry in drift.unconfigured] == [".env.local"]

    def test_configured_candidate_is_not_reported(self, repo: Path) -> None:
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")

        drift = diff_seed_config(repo, [SeedEntry(path=".env.local", mode=SEED_MODE_SYMLINK)])

        assert not drift.has_drift

    def test_a_deliberate_mode_choice_is_not_drift(self, repo: Path) -> None:
        """The project OWNS the mode. Nagging about a deliberate choice would be wrong."""
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")

        drift = diff_seed_config(repo, [SeedEntry(path=".env.local", mode=SEED_MODE_COPY)])

        assert not drift.has_drift

    def test_configured_path_that_no_longer_exists_is_reported(self, repo: Path) -> None:
        """This one would make worktree creation FAIL, so it is the loudest finding."""
        drift = diff_seed_config(repo, [SeedEntry(path=".env.gone", mode=SEED_MODE_SYMLINK)])

        assert drift.has_drift
        assert [entry.path for entry in drift.missing] == [".env.gone"]

    def test_both_kinds_of_drift_are_reported_together(self, repo: Path) -> None:
        (repo / ".env.local").write_text("SECRET=1\n", encoding="utf-8")

        drift = diff_seed_config(repo, [SeedEntry(path=".env.gone", mode=SEED_MODE_SYMLINK)])

        assert [entry.path for entry in drift.unconfigured] == [".env.local"]
        assert [entry.path for entry in drift.missing] == [".env.gone"]

    def test_a_configured_path_outside_the_candidate_shapes_is_still_honoured(
        self, repo: Path
    ) -> None:
        """A project may seed something the heuristics would never propose."""
        (repo / "debug.log").write_text("noise\n", encoding="utf-8")

        drift = diff_seed_config(repo, [SeedEntry(path="debug.log", mode=SEED_MODE_COPY)])

        assert not drift.has_drift
