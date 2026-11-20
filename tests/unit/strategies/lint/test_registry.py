"""Tests for Lint Strategy Registry."""

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.strategies.lint.registry import LintStrategyRegistry


class _MockLintStrategy:
    """Mock lint strategy for registry testing."""

    def __init__(
        self,
        language_name: str = "MockLang",
        extensions: tuple[str, ...] = (".mock",),
        default_lint_command: str = "mocklint {file}",
        extended_lint_command: str | None = None,
        skip_paths: tuple[str, ...] = ("vendor/",),
    ) -> None:
        self._language_name = language_name
        self._extensions = extensions
        self._default_lint_command = default_lint_command
        self._extended_lint_command = extended_lint_command
        self._skip_paths = skip_paths

    @property
    def language_name(self) -> str:
        return self._language_name

    @property
    def extensions(self) -> tuple[str, ...]:
        return self._extensions

    @property
    def default_lint_command(self) -> str:
        return self._default_lint_command

    @property
    def extended_lint_command(self) -> str | None:
        return self._extended_lint_command

    @property
    def skip_paths(self) -> tuple[str, ...]:
        return self._skip_paths

    def get_acceptance_tests(self) -> list[Any]:
        return []


class TestRegistry:
    @pytest.fixture()
    def registry(self) -> LintStrategyRegistry:
        return LintStrategyRegistry()

    def test_empty_registry(self, registry: LintStrategyRegistry) -> None:
        assert registry.registered_languages == []

    def test_register_strategy(self, registry: LintStrategyRegistry) -> None:
        strategy = _MockLintStrategy()
        registry.register(strategy)
        assert registry.registered_languages == ["MockLang"]

    def test_get_strategy_by_extension(self, registry: LintStrategyRegistry) -> None:
        strategy = _MockLintStrategy()
        registry.register(strategy)
        result = registry.get_strategy("/workspace/src/file.mock")
        assert result is not None
        assert result.language_name == "MockLang"

    def test_get_strategy_unknown_extension(self, registry: LintStrategyRegistry) -> None:
        strategy = _MockLintStrategy()
        registry.register(strategy)
        result = registry.get_strategy("/workspace/src/file.unknown")
        assert result is None

    def test_get_strategy_case_insensitive(self, registry: LintStrategyRegistry) -> None:
        strategy = _MockLintStrategy()
        registry.register(strategy)
        result = registry.get_strategy("/workspace/src/file.MOCK")
        assert result is not None

    def test_register_multiple_extensions(self, registry: LintStrategyRegistry) -> None:
        strategy = _MockLintStrategy(extensions=(".sh", ".bash"))
        registry.register(strategy)
        assert registry.get_strategy("/workspace/script.sh") is not None
        assert registry.get_strategy("/workspace/script.bash") is not None

    def test_register_multiple_strategies(self, registry: LintStrategyRegistry) -> None:
        strategy1 = _MockLintStrategy(language_name="Lang1", extensions=(".l1",))
        strategy2 = _MockLintStrategy(language_name="Lang2", extensions=(".l2",))
        registry.register(strategy1)
        registry.register(strategy2)
        assert set(registry.registered_languages) == {"Lang1", "Lang2"}


class TestStrategies:
    """strategies() (Plan 00296 T4.1): dedup listing for a caller that needs
    instances, not just names -- e.g. `get_enforcement_status()`'s extended-
    linter probe."""

    def test_empty_registry_returns_empty_list(self) -> None:
        assert LintStrategyRegistry().strategies() == []

    def test_returns_registered_instance(self) -> None:
        registry = LintStrategyRegistry()
        strategy = _MockLintStrategy()
        registry.register(strategy)
        assert registry.strategies() == [strategy]

    def test_dedupes_a_strategy_registered_under_several_extensions(self) -> None:
        """One strategy, several extensions -> one entry, not one per extension."""
        registry = LintStrategyRegistry()
        strategy = _MockLintStrategy(extensions=(".sh", ".bash"))
        registry.register(strategy)
        assert registry.strategies() == [strategy]

    def test_lists_every_distinct_strategy(self) -> None:
        registry = LintStrategyRegistry()
        strategy1 = _MockLintStrategy(language_name="Lang1", extensions=(".l1",))
        strategy2 = _MockLintStrategy(language_name="Lang2", extensions=(".l2",))
        registry.register(strategy1)
        registry.register(strategy2)
        assert {s.language_name for s in registry.strategies()} == {"Lang1", "Lang2"}


class TestFilterByLanguages:
    @pytest.fixture()
    def registry(self) -> LintStrategyRegistry:
        reg = LintStrategyRegistry()
        reg.register(_MockLintStrategy(language_name="Python", extensions=(".py",)))
        reg.register(_MockLintStrategy(language_name="Shell", extensions=(".sh", ".bash")))
        reg.register(_MockLintStrategy(language_name="Go", extensions=(".go",)))
        return reg

    def test_filter_keeps_matching(self, registry: LintStrategyRegistry) -> None:
        registry.filter_by_languages(["Python", "Shell"])
        assert set(registry.registered_languages) == {"Python", "Shell"}

    def test_filter_removes_non_matching(self, registry: LintStrategyRegistry) -> None:
        registry.filter_by_languages(["Python"])
        assert registry.get_strategy("/workspace/file.go") is None

    def test_filter_case_insensitive(self, registry: LintStrategyRegistry) -> None:
        registry.filter_by_languages(["python", "shell"])
        assert set(registry.registered_languages) == {"Python", "Shell"}

    def test_filter_empty_list_keeps_all(self, registry: LintStrategyRegistry) -> None:
        registry.filter_by_languages([])
        assert len(registry.registered_languages) == 3

    def test_filter_removes_all_extensions_of_language(
        self, registry: LintStrategyRegistry
    ) -> None:
        registry.filter_by_languages(["Python"])
        assert registry.get_strategy("/workspace/script.sh") is None
        assert registry.get_strategy("/workspace/script.bash") is None


class _NarrowingMockStrategy(_MockLintStrategy):
    """A mock that implements NarrowsByPath: accepts paths containing a marker."""

    def __init__(self, marker: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._marker = marker

    def handles_file(self, file_path: str) -> bool:
        return self._marker in file_path


class TestSharedExtensions:
    """Plan 00621: several strategies may share an extension when each narrows.

    ``.yml`` is shared by Ansible playbooks and GitHub workflows. Storing one
    strategy per extension would let the second registration silently replace
    the first for every YAML file in the project.
    """

    @pytest.fixture()
    def registry(self) -> LintStrategyRegistry:
        reg = LintStrategyRegistry()
        reg.register(
            _NarrowingMockStrategy(marker="/plays/", language_name="First", extensions=(".yml",))
        )
        reg.register(
            _NarrowingMockStrategy(marker="/flows/", language_name="Second", extensions=(".yml",))
        )
        return reg

    def test_each_narrowing_strategy_keeps_its_own_files(
        self, registry: LintStrategyRegistry
    ) -> None:
        first = registry.get_strategy("/repo/plays/site.yml")
        second = registry.get_strategy("/repo/flows/ci.yml")
        assert first is not None and first.language_name == "First"
        assert second is not None and second.language_name == "Second"

    def test_a_file_neither_accepts_resolves_to_none(self, registry: LintStrategyRegistry) -> None:
        assert registry.get_strategy("/repo/config.yml") is None

    def test_a_non_narrowing_newcomer_on_an_owned_extension_is_refused(
        self, registry: LintStrategyRegistry
    ) -> None:
        with pytest.raises(ValueError, match=r"\.yml"):
            registry.register(_MockLintStrategy(language_name="Greedy", extensions=(".yml",)))

    def test_a_newcomer_onto_a_non_narrowing_owner_is_refused(self) -> None:
        """The owner claims every file, so the newcomer would never be reached."""
        reg = LintStrategyRegistry()
        reg.register(_MockLintStrategy(language_name="Owner", extensions=(".yml",)))
        with pytest.raises(ValueError, match=r"\.yml"):
            reg.register(
                _NarrowingMockStrategy(marker="/x/", language_name="Late", extensions=(".yml",))
            )

    def test_a_refused_registration_leaves_the_registry_unchanged(
        self, registry: LintStrategyRegistry
    ) -> None:
        greedy = _MockLintStrategy(language_name="Greedy", extensions=(".other", ".yml"))
        with pytest.raises(ValueError):
            registry.register(greedy)
        assert registry.get_strategy("/repo/a.other") is None
        assert "Greedy" not in registry.registered_languages

    def test_filter_removes_one_of_two_sharing_and_keeps_the_other(
        self, registry: LintStrategyRegistry
    ) -> None:
        registry.filter_by_languages(["Second"])
        assert registry.get_strategy("/repo/plays/site.yml") is None
        kept = registry.get_strategy("/repo/flows/ci.yml")
        assert kept is not None and kept.language_name == "Second"
        assert registry.registered_languages == ["Second"]

    def test_strategies_lists_both_sharing_strategies_once(
        self, registry: LintStrategyRegistry
    ) -> None:
        assert [s.language_name for s in registry.strategies()] == ["First", "Second"]

    def test_registered_languages_lists_both(self, registry: LintStrategyRegistry) -> None:
        assert registry.registered_languages == ["First", "Second"]


class TestDefaultYamlRouting:
    """The default registry routes each YAML file to the right strategy, or none."""

    @staticmethod
    def _write(root: Path, relative: str, content: str) -> str:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path)

    def test_an_ansible_playbook_still_resolves_to_ansible(self, tmp_path: Path) -> None:
        path = self._write(tmp_path, "playbooks/site.yml", "---\n- hosts: all\n  tasks: []\n")
        strategy = LintStrategyRegistry.create_default().get_strategy(path)
        assert strategy is not None
        assert strategy.language_name == "Ansible"

    @pytest.mark.parametrize("name", ["ci.yml", "release.yaml"])
    def test_a_workflow_resolves_to_the_workflow_strategy(self, tmp_path: Path, name: str) -> None:
        path = self._write(tmp_path, f".github/workflows/{name}", "on: push\njobs: {}\n")
        strategy = LintStrategyRegistry.create_default().get_strategy(path)
        assert strategy is not None
        assert strategy.language_name == "GitHub Workflow"

    @pytest.mark.parametrize(
        "relative",
        [".github/workflows/sub/x.yml", ".github/dependabot.yml", "config.yml"],
    )
    def test_other_yaml_resolves_to_neither(self, tmp_path: Path, relative: str) -> None:
        path = self._write(tmp_path, relative, "version: 2\n")
        assert LintStrategyRegistry.create_default().get_strategy(path) is None


class TestCreateDefault:
    def test_create_default_returns_registry(self) -> None:
        registry = LintStrategyRegistry.create_default()
        assert isinstance(registry, LintStrategyRegistry)

    def test_create_default_registers_all_languages(self) -> None:
        registry = LintStrategyRegistry.create_default()
        expected_languages = {
            "Shell",
            "Python",
            "Go",
            "Rust",
            "Ruby",
            "PHP",
            "Dart",
            "Kotlin",
            "Swift",
            "Ansible",
            "GitHub Workflow",
        }
        assert set(registry.registered_languages) == expected_languages

    def test_create_default_shell_extension(self) -> None:
        registry = LintStrategyRegistry.create_default()
        assert registry.get_strategy("/workspace/script.sh") is not None
        assert registry.get_strategy("/workspace/script.bash") is not None

    def test_create_default_python_extension(self) -> None:
        registry = LintStrategyRegistry.create_default()
        assert registry.get_strategy("/workspace/app.py") is not None

    def test_create_default_go_extension(self) -> None:
        registry = LintStrategyRegistry.create_default()
        assert registry.get_strategy("/workspace/main.go") is not None

    def test_create_default_rust_extension(self) -> None:
        registry = LintStrategyRegistry.create_default()
        assert registry.get_strategy("/workspace/lib.rs") is not None
