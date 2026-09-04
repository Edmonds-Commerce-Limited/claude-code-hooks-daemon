"""Tests for the ``ProjectLayout`` facade (Plan 00288, Task 2.2)."""

import dataclasses

import pytest

from claude_code_hooks_daemon.config.models import Config, LayoutConfig
from claude_code_hooks_daemon.core.project_layout import ProjectLayout, main_repo_code_dirs
from claude_code_hooks_daemon.docs_qa.corpus import COMMON_VENDORED_BUILD_DIR_NAMES
from claude_code_hooks_daemon.strategies.tdd.common import COMMON_TEST_DIRECTORIES


class TestZeroConfigCompositionEqualsBuiltins:
    """Pins today's built-in behaviour byte-identical with no `layout:` block."""

    def test_source_dirs_empty_with_no_config(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.source_dirs == ()

    def test_test_dirs_match_common_test_directories(self) -> None:
        layout = ProjectLayout.from_config(Config())
        expected = tuple(name.strip("/") for name in COMMON_TEST_DIRECTORIES)
        assert layout.test_dirs == expected

    def test_config_dirs_default_to_config(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.config_dirs == ("config",)

    def test_vendor_dirs_equal_canonical_constant(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.vendor_dirs == frozenset(COMMON_VENDORED_BUILD_DIR_NAMES)

    def test_agent_and_human_docs_dirs_use_documentation_trees_defaults(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.agent_docs_dir == "CLAUDE"
        assert layout.human_docs_dir == "docs"

    def test_plan_dir_uses_plan_workflow_default(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.plan_dir == "CLAUDE/Plan"

    def test_plan_archive_dirs_use_qa_defaults(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.plan_archive_dirs == ("Completed", "Cancelled")


class TestAdditiveMode:
    def test_declared_source_dirs_extend_builtins(self) -> None:
        config = Config.model_validate({"layout": {"source_dirs": ["engine"]}})
        layout = ProjectLayout.from_config(config)
        assert layout.source_dirs == ("engine",)

    def test_declared_test_dirs_extend_common_test_directories(self) -> None:
        config = Config.model_validate({"layout": {"test_dirs": ["e2e"]}})
        layout = ProjectLayout.from_config(config)
        expected = (*(name.strip("/") for name in COMMON_TEST_DIRECTORIES), "e2e")
        assert layout.test_dirs == expected

    def test_declared_config_dirs_extend_builtin_config(self) -> None:
        config = Config.model_validate({"layout": {"config_dirs": ["settings"]}})
        layout = ProjectLayout.from_config(config)
        assert layout.config_dirs == ("config", "settings")

    def test_declared_vendor_dirs_extend_canonical_set(self) -> None:
        config = Config.model_validate({"layout": {"vendor_dirs": ["deps"]}})
        layout = ProjectLayout.from_config(config)
        assert layout.vendor_dirs == frozenset(COMMON_VENDORED_BUILD_DIR_NAMES) | {"deps"}

    def test_duplicate_declared_dir_is_not_repeated(self) -> None:
        config = Config.model_validate({"layout": {"config_dirs": ["config"]}})
        layout = ProjectLayout.from_config(config)
        assert layout.config_dirs == ("config",)


class TestReplaceMode:
    def test_set_list_stands_alone(self) -> None:
        config = Config.model_validate({"layout": {"config_dirs": ["settings"], "mode": "replace"}})
        layout = ProjectLayout.from_config(config)
        assert layout.config_dirs == ("settings",)

    def test_unset_list_keeps_builtin_even_under_replace(self) -> None:
        config = Config.model_validate({"layout": {"config_dirs": ["settings"], "mode": "replace"}})
        layout = ProjectLayout.from_config(config)
        expected = tuple(name.strip("/") for name in COMMON_TEST_DIRECTORIES)
        assert layout.test_dirs == expected

    def test_vendor_dirs_replace_stand_alone(self) -> None:
        config = Config.model_validate({"layout": {"vendor_dirs": ["deps"], "mode": "replace"}})
        layout = ProjectLayout.from_config(config)
        assert layout.vendor_dirs == frozenset({"deps"})


class TestMembershipHelpers:
    def test_is_source_path_true_for_declared_dir(self) -> None:
        config = Config.model_validate({"layout": {"source_dirs": ["engine"]}})
        layout = ProjectLayout.from_config(config)
        assert layout.is_source_path("engine/foo.py") is True

    def test_is_source_path_false_when_no_source_dirs_declared(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.is_source_path("src/foo.py") is False

    def test_is_test_path_true_for_builtin_test_dir(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.is_test_path("tests/unit/test_foo.py") is True

    def test_is_test_path_false_for_unrelated_path(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.is_test_path("src/foo.py") is False

    def test_is_vendored_path_true_for_node_modules(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.is_vendored_path("frontend/node_modules/pkg/index.js") is True

    def test_is_vendored_path_false_for_unrelated_path(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.is_vendored_path("src/foo.py") is False


class TestVendorExceptions:
    """Plan 00331 Phase 3: a first-party library living INSIDE a vendored tree.

    The owner's case: a vendor directory holds third-party code plus one or
    two libraries the project actually maintains in place. Skipping the whole
    tree hides work they do daily; not skipping it drowns them in findings
    about code they did not write.

    The two keys use DIFFERENT dialects deliberately. `vendor_dirs` holds
    NAMES because a name is a CONVENTION (`node_modules` is vendored wherever
    it appears); `vendor_exceptions` holds repo-relative path GLOBS because an
    exception is a SPECIFIC thing the project owns, and a bare basename would
    wrongly match it at any depth.
    """

    @staticmethod
    def _layout(exceptions: tuple[str, ...]) -> ProjectLayout:
        return ProjectLayout.for_project(
            LayoutConfig(vendor_dirs=["roles"], vendor_exceptions=list(exceptions)),
            ProjectLayout.built_in_default(),
        )

    def test_an_excepted_path_is_not_vendored(self) -> None:
        layout = self._layout(("infra/roles/ours/**",))
        assert layout.is_vendored_path("infra/roles/ours/tasks/main.py") is False

    def test_a_sibling_inside_the_same_vendor_dir_stays_vendored(self) -> None:
        """The exception must be surgical, not switch the vendor dir off."""
        layout = self._layout(("infra/roles/ours/**",))
        assert layout.is_vendored_path("infra/roles/theirs/tasks/main.py") is True

    def test_the_exception_root_itself_is_not_vendored(self) -> None:
        """`a/b/**` conventionally covers the directory it names, not just its
        contents -- otherwise a file directly in `ours/` is still hidden."""
        layout = self._layout(("infra/roles/ours/**",))
        assert layout.is_vendored_path("infra/roles/ours/README.md") is False

    def test_no_exceptions_leaves_the_vendor_dir_wholly_vendored(self) -> None:
        layout = self._layout(())
        assert layout.is_vendored_path("infra/roles/ours/tasks/main.py") is True

    def test_an_exception_outside_any_vendor_dir_changes_nothing(self) -> None:
        """An exception is a carve-out from the vendor set, not an independent
        include list -- a path that was never vendored cannot become MORE
        included, and must not accidentally read as vendored either."""
        layout = self._layout(("src/ours/**",))
        assert layout.is_vendored_path("src/ours/main.py") is False
        assert layout.is_vendored_path("src/other/main.py") is False

    def test_a_bare_name_exception_is_anchored_not_matched_at_any_depth(self) -> None:
        """The dialect difference, asserted rather than merely documented: an
        exception is repo-relative, so `ours` means the top-level `ours/`, NOT
        every directory called `ours`."""
        layout = self._layout(("ours/**",))
        assert layout.is_vendored_path("infra/roles/ours/main.py") is True


class TestPruneSafety:
    """A pruning walker must not prune a directory that could CONTAIN an
    exception.

    This is the constraint that silently defeats the whole feature if missed.
    Git itself cannot re-include a file whose parent directory is excluded,
    because it never descends -- and two docs-QA checks prune directories out
    of `os.walk` for exactly the performance reason git does.
    """

    @staticmethod
    def _layout(exceptions: tuple[str, ...]) -> ProjectLayout:
        return ProjectLayout.for_project(
            LayoutConfig(vendor_dirs=["roles"], vendor_exceptions=list(exceptions)),
            ProjectLayout.built_in_default(),
        )

    def test_an_ancestor_of_an_exception_may_contain_one(self) -> None:
        layout = self._layout(("infra/roles/ours/**",))
        assert layout.may_contain_vendor_exception("infra") is True
        assert layout.may_contain_vendor_exception("infra/roles") is True

    def test_the_exception_directory_itself_may_contain_one(self) -> None:
        layout = self._layout(("infra/roles/ours/**",))
        assert layout.may_contain_vendor_exception("infra/roles/ours") is True

    def test_a_descendant_of_an_exception_may_contain_one(self) -> None:
        """Once inside the exception, everything below it is first-party."""
        layout = self._layout(("infra/roles/ours/**",))
        assert layout.may_contain_vendor_exception("infra/roles/ours/tasks") is True

    def test_an_unrelated_directory_may_not(self) -> None:
        layout = self._layout(("infra/roles/ours/**",))
        assert layout.may_contain_vendor_exception("infra/roles/theirs") is False
        assert layout.may_contain_vendor_exception("other") is False

    def test_no_exceptions_means_nothing_is_prune_unsafe(self) -> None:
        """Zero-config must not make every walker descend everything."""
        layout = self._layout(())
        assert layout.may_contain_vendor_exception("infra/roles") is False

    def test_a_leading_wildcard_exception_is_conservatively_unprunable(self) -> None:
        """`**/ours/**` could match beneath ANY directory, so no directory can
        be proven safe to prune. Conservative on purpose: over-descending
        costs time, while over-pruning silently hides a project's own code.
        A project wanting the pruning back writes an anchored path."""
        layout = self._layout(("**/ours/**",))
        assert layout.may_contain_vendor_exception("anything/at/all") is True

    def test_is_docs_path_true_for_agent_tree(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.is_docs_path("CLAUDE/ARCHITECTURE.md") is True

    def test_is_docs_path_true_for_human_tree(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.is_docs_path("docs/guide.md") is True

    def test_is_docs_path_false_for_unrelated_path(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.is_docs_path("src/foo.py") is False

    def test_is_plan_path_true_under_plan_dir(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.is_plan_path("CLAUDE/Plan/00001-foo/PLAN.md") is True

    def test_is_plan_path_false_for_unrelated_path(self) -> None:
        layout = ProjectLayout.from_config(Config())
        assert layout.is_plan_path("src/foo.py") is False

    def test_is_plan_path_false_when_plan_dir_is_empty(self) -> None:
        config = Config.model_validate({"plan_workflow": {"directory": ""}})
        layout = ProjectLayout.from_config(config)
        assert layout.is_plan_path("anything.md") is False


class TestFrozen:
    def test_instance_is_immutable(self) -> None:
        layout = ProjectLayout.from_config(Config())
        with pytest.raises(dataclasses.FrozenInstanceError):
            layout.source_dirs = ("nope",)


class TestMainRepoCodeDirs:
    """main_repo_code_dirs() -- the shared "main repo code dirs" truth used
    by worktree_file_copy, same-commit-plan-doc, and path-existence (C5)."""

    def test_none_layout_returns_pre_facade_literal(self) -> None:
        assert main_repo_code_dirs(None) == ("src", "tests", "config")

    def test_zero_config_layout_is_a_superset_of_pre_facade_literal(self) -> None:
        """The real (non-None) zero-config facade widens test_dirs (adds
        test/, __tests__/, spec/) but never loses src/tests/config."""
        layout = ProjectLayout.from_config(Config())
        result = main_repo_code_dirs(layout)
        assert {"src", "tests", "config"}.issubset(set(result))

    def test_declared_source_dirs_are_included(self) -> None:
        """A declared source_dirs list is honoured -- and since it is no
        longer empty, the "src" fallback (which only applies when
        source_dirs is undeclared) does not additionally force "src" in."""
        config = Config.model_validate({"layout": {"source_dirs": ["backend"]}})
        layout = ProjectLayout.from_config(config)
        assert "backend" in main_repo_code_dirs(layout)
        assert "src" not in main_repo_code_dirs(layout)

    def test_declared_config_dirs_are_included(self) -> None:
        config = Config.model_validate({"layout": {"config_dirs": ["settings"]}})
        layout = ProjectLayout.from_config(config)
        assert "settings" in main_repo_code_dirs(layout)
        assert "config" in main_repo_code_dirs(layout)  # additive default

    def test_no_duplicate_entries(self) -> None:
        layout = ProjectLayout.from_config(Config())
        result = main_repo_code_dirs(layout)
        assert len(result) == len(set(result))
