"""Tests for the shared vendor-exception primitives (Plan 00331 Phase 3).

These live in `utils/` rather than on `ProjectLayout` because BOTH sides need
them and neither may import the other: `core.project_layout` already imports
`docs_qa.corpus`, so a docs_qa -> core import would close a cycle. The facade
holds the config; this module holds the pure matching, and both read the same
answer rather than each deriving one.
"""

from __future__ import annotations

import pytest

from claude_code_hooks_daemon.utils.vendor_paths import (
    matches_vendor_exception,
    may_contain_vendor_exception,
)

_OURS = ("infra/roles/ours/**",)


class TestMatchesVendorException:
    def test_a_file_beneath_the_exception_matches(self) -> None:
        assert matches_vendor_exception("infra/roles/ours/tasks/main.py", _OURS) is True

    def test_the_exception_directory_itself_matches(self) -> None:
        """`a/b/**` conventionally covers the directory it names.

        Without this a file sitting DIRECTLY in `ours/` stays hidden, which is
        the surprising half of the gitignore convention and the half a naive
        `fnmatch` gets wrong.
        """
        assert matches_vendor_exception("infra/roles/ours", _OURS) is True
        assert matches_vendor_exception("infra/roles/ours/README.md", _OURS) is True

    def test_a_sibling_does_not_match(self) -> None:
        assert matches_vendor_exception("infra/roles/theirs/main.py", _OURS) is False

    def test_a_prefix_collision_does_not_match(self) -> None:
        """`ours-vendored` starts with `ours` but is a different directory."""
        assert matches_vendor_exception("infra/roles/ours-vendored/main.py", _OURS) is False

    def test_no_patterns_never_matches(self) -> None:
        assert matches_vendor_exception("infra/roles/ours/main.py", ()) is False

    def test_leading_and_trailing_slashes_are_tolerated(self) -> None:
        assert matches_vendor_exception("/infra/roles/ours/main.py", _OURS) is True

    def test_a_bare_relative_pattern_is_anchored(self) -> None:
        """An exception is a repo-relative PATH, not a directory NAME -- so it
        must not match the same basename at another depth."""
        assert matches_vendor_exception("infra/roles/ours/main.py", ("ours/**",)) is False
        assert matches_vendor_exception("ours/main.py", ("ours/**",)) is True


class TestMayContainVendorException:
    def test_an_ancestor_may_contain_one(self) -> None:
        assert may_contain_vendor_exception("infra", _OURS) is True
        assert may_contain_vendor_exception("infra/roles", _OURS) is True

    def test_the_exception_directory_may_contain_one(self) -> None:
        assert may_contain_vendor_exception("infra/roles/ours", _OURS) is True

    def test_a_descendant_may_contain_one(self) -> None:
        assert may_contain_vendor_exception("infra/roles/ours/tasks", _OURS) is True

    def test_an_unrelated_directory_may_not(self) -> None:
        assert may_contain_vendor_exception("infra/roles/theirs", _OURS) is False
        assert may_contain_vendor_exception("other", _OURS) is False

    def test_no_patterns_means_everything_is_prunable(self) -> None:
        """Zero-config must not make every walker descend the whole tree."""
        assert may_contain_vendor_exception("infra/roles", ()) is False

    @pytest.mark.parametrize("candidate", ["a", "a/b", "totally/unrelated"])
    def test_a_leading_wildcard_makes_nothing_prunable(self, candidate: str) -> None:
        """`**/ours/**` has no literal prefix, so it could match beneath ANY
        directory and none can be proven safe to prune.

        Conservative on purpose: over-descending costs time, over-pruning
        silently hides a project's own code, and only one of those announces
        itself.
        """
        assert may_contain_vendor_exception(candidate, ("**/ours/**",)) is True

    def test_the_repo_root_may_always_contain_one(self) -> None:
        """An `os.walk` starts at the root with a relative path of `""`; if
        that read as prunable the walk would never begin."""
        assert may_contain_vendor_exception("", _OURS) is True
