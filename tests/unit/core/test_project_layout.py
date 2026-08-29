"""Tests for the ``ProjectLayout`` facade (Plan 00288, Task 2.2)."""

import dataclasses

import pytest

from claude_code_hooks_daemon.config.models import Config
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
