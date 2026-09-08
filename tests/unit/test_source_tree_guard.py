"""Plan 00358 — a test session must import the package from ITS OWN checkout.

A worktree whose ``untracked/venv`` symlinks to the main checkout's venv
imports ``claude_code_hooks_daemon`` from ``/workspace/src`` while the tests
run from the worktree, so a correct fix looks like a wall of failures and a
green run says nothing about the branch. The guard turns that silent wrong
answer into one loud error that names both paths and the remedy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.source_tree_guard import (
    SETUP_WORKTREE_REMEDY,
    SourceTreeMismatch,
    assert_package_is_this_checkout,
    package_root_for,
)


def _checkout(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    package = root / "src" / "claude_code_hooks_daemon"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    return root


class TestThePackageMustBelongToTheInvokingCheckout:
    def test_a_package_under_the_checkouts_own_src_passes(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path, "repo")
        package_file = root / "src" / "claude_code_hooks_daemon" / "__init__.py"
        assert_package_is_this_checkout(package_file=package_file, repo_root=root)

    def test_a_package_resolved_from_another_checkout_fails_naming_both_paths(
        self, tmp_path: Path
    ) -> None:
        main = _checkout(tmp_path, "workspace")
        worktree = _checkout(tmp_path, "worktree")
        foreign = main / "src" / "claude_code_hooks_daemon" / "__init__.py"
        with pytest.raises(SourceTreeMismatch) as excinfo:
            assert_package_is_this_checkout(package_file=foreign, repo_root=worktree)
        message = str(excinfo.value)
        assert str(main / "src") in message
        assert str(worktree / "src") in message
        assert SETUP_WORKTREE_REMEDY in message

    def test_a_symlinked_src_that_resolves_elsewhere_is_still_a_mismatch(
        self, tmp_path: Path
    ) -> None:
        """The incident shape: the path LOOKS local until it is resolved."""
        main = _checkout(tmp_path, "workspace")
        worktree = tmp_path / "worktree"
        worktree.mkdir()
        (worktree / "src").symlink_to(main / "src", target_is_directory=True)
        looks_local = worktree / "src" / "claude_code_hooks_daemon" / "__init__.py"
        with pytest.raises(SourceTreeMismatch):
            assert_package_is_this_checkout(package_file=looks_local, repo_root=worktree)


class TestTheRealSession:
    def test_the_running_suite_imports_from_this_checkout(self) -> None:
        """If this fails, every other result in the run is about someone else's code."""
        repo_root = Path(__file__).resolve().parents[2]
        assert package_root_for(repo_root) == repo_root / "src"
        assert_package_is_this_checkout(repo_root=repo_root)
