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
    VendorScope,
    is_vendored_path_in_scopes,
    matches_vendor_exception,
    may_contain_vendor_exception,
    may_contain_vendor_exception_in_scopes,
    resolve_vendor_scope,
)

_OURS = ("infra/roles/ours/**",)

_ROOT_SCOPE = VendorScope(root="", vendor_dirs=frozenset({"vendor"}), vendor_exceptions=())
_API_SCOPE = VendorScope(root="apps/api", vendor_dirs=frozenset({"roles"}), vendor_exceptions=())
_SCOPES = (_ROOT_SCOPE, _API_SCOPE)


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


class TestResolveVendorScope:
    """Plan 00332 Task 1.1: which project's vendor truth governs a path."""

    def test_a_path_inside_a_declared_project_resolves_to_it(self) -> None:
        assert resolve_vendor_scope("apps/api/roles/x.py", _SCOPES) is _API_SCOPE

    def test_a_path_outside_every_declared_project_resolves_to_the_root(self) -> None:
        assert resolve_vendor_scope("apps/web/roles/x.py", _SCOPES) is _ROOT_SCOPE

    def test_the_longest_root_wins_not_the_first(self) -> None:
        """A project declared INSIDE another's tree must win over its ancestor.

        First-match would make the answer depend on declaration order in the
        YAML, so re-ordering two `projects:` entries would silently change
        which vendor set governs a path.
        """
        inner = VendorScope(
            root="apps/api/vendor/inner", vendor_dirs=frozenset({"pkg"}), vendor_exceptions=()
        )
        scopes = (_ROOT_SCOPE, _API_SCOPE, inner)
        assert resolve_vendor_scope("apps/api/vendor/inner/pkg/x.py", scopes) is inner
        assert resolve_vendor_scope("apps/api/vendor/inner/pkg/x.py", tuple(reversed(scopes))) is (
            inner
        )

    def test_a_prefix_collision_is_not_containment(self) -> None:
        """`apps/api-legacy` is not inside `apps/api`."""
        assert resolve_vendor_scope("apps/api-legacy/roles/x.py", _SCOPES) is _ROOT_SCOPE

    def test_no_root_scope_declared_returns_none(self) -> None:
        """Callers must be able to tell "nothing governs this" from "the root
        governs it" — the two differ once a repo declares only sub-projects."""
        assert resolve_vendor_scope("elsewhere/x.py", (_API_SCOPE,)) is None


class TestIsVendoredPathInScopes:
    def test_the_declaring_project_judges_its_own_tree(self) -> None:
        assert is_vendored_path_in_scopes("apps/api/roles/x.py", _SCOPES) is True

    def test_a_sibling_does_not_inherit_the_declaration(self) -> None:
        """The discriminating case. A repo-wide UNION of every project's
        vendor_dirs would return True here, silently hiding project B's files
        because project A declared a name — the failure this design exists to
        avoid.
        """
        assert is_vendored_path_in_scopes("apps/web/roles/x.py", _SCOPES) is False

    def test_the_root_scope_still_governs_paths_outside_projects(self) -> None:
        assert is_vendored_path_in_scopes("apps/web/vendor/x.py", _SCOPES) is True

    def test_a_sub_projects_exception_re_includes_its_own_library(self) -> None:
        api = VendorScope(
            root="apps/api",
            vendor_dirs=frozenset({"roles"}),
            vendor_exceptions=("apps/api/roles/ours/**",),
        )
        assert is_vendored_path_in_scopes("apps/api/roles/ours/main.py", (_ROOT_SCOPE, api)) is (
            False
        )
        assert is_vendored_path_in_scopes("apps/api/roles/theirs/main.py", (_ROOT_SCOPE, api)) is (
            True
        )

    def test_no_scopes_means_nothing_is_vendored(self) -> None:
        assert is_vendored_path_in_scopes("apps/api/roles/x.py", ()) is False


class TestMayContainVendorExceptionInScopes:
    def test_an_ancestor_of_a_declared_project_is_never_prunable(self) -> None:
        """The prune-safety trap unique to per-scope resolution.

        `apps` is judged by the ROOT scope, which declares no exceptions --
        so asking the root alone says "prunable". But a declared project
        BELOW it has exceptions, and pruning `apps` makes them unreachable,
        exactly as pruning a vendored directory hides an exception inside it.
        """
        api = VendorScope(
            root="apps/api",
            vendor_dirs=frozenset({"roles"}),
            vendor_exceptions=("apps/api/roles/ours/**",),
        )
        scopes = (_ROOT_SCOPE, api)
        assert may_contain_vendor_exception_in_scopes("apps", scopes) is True
        assert may_contain_vendor_exception_in_scopes("apps/api", scopes) is True
        assert may_contain_vendor_exception_in_scopes("apps/api/roles", scopes) is True

    def test_an_unrelated_directory_stays_prunable(self) -> None:
        api = VendorScope(
            root="apps/api",
            vendor_dirs=frozenset({"roles"}),
            vendor_exceptions=("apps/api/roles/ours/**",),
        )
        assert may_contain_vendor_exception_in_scopes("other", (_ROOT_SCOPE, api)) is False

    def test_no_exceptions_anywhere_keeps_everything_prunable(self) -> None:
        """Zero-config must not make every walker descend the whole tree."""
        assert may_contain_vendor_exception_in_scopes("apps/api/roles", _SCOPES) is False
