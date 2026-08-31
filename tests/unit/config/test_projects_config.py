"""Tests for the top-level ``projects:`` block (Plan 00296, Task 3.1).

A project is a first-class configured concept, not something the daemon works
out for itself. Omitting the block means one project at the repository root —
byte-identical to the behaviour every single-project repo has today.

The load-bearing property under test is that **declaring a project must not
require it to contain a manifest**. The field report's `infra/` is
"config-driven, no manifest": if declaration demanded one, the only workspace
that cannot be detected would also be the one that cannot be declared.
"""

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, ProjectConfig


class TestProjectEntry:
    def test_name_and_root_are_enough(self) -> None:
        project = ProjectConfig(name="web", root="web")
        assert project.name == "web"
        assert project.root == "web"

    def test_kind_and_bin_dirs_default_to_unset(self) -> None:
        """Unset means 'fill in by convention', which is not the same as empty.

        An explicitly empty ``bin_dirs`` is a project stating it has no tool
        directory; an absent one is a project not saying. Conflating them
        would make it impossible to declare the former.
        """
        project = ProjectConfig(name="infra", root="infra")
        assert project.kind is None
        assert project.bin_dirs is None

    def test_kind_and_bin_dirs_are_accepted_when_stated(self) -> None:
        project = ProjectConfig(name="infra", root="infra", kind="ansible", bin_dirs=[".venv/bin"])
        assert project.kind == "ansible"
        assert project.bin_dirs == [".venv/bin"]

    def test_explicitly_empty_bin_dirs_is_distinct_from_unset(self) -> None:
        assert ProjectConfig(name="a", root="a", bin_dirs=[]).bin_dirs == []

    def test_name_is_required(self) -> None:
        with pytest.raises(ValidationError):
            ProjectConfig.model_validate({"root": "web"})

    def test_root_is_required(self) -> None:
        with pytest.raises(ValidationError):
            ProjectConfig.model_validate({"name": "web"})

    def test_unknown_key_is_rejected(self) -> None:
        """A typo must fail loudly rather than silently declaring nothing."""
        with pytest.raises(ValidationError):
            ProjectConfig.model_validate({"name": "web", "root": "web", "kidn": "node"})

    def test_absolute_root_is_rejected(self) -> None:
        """Roots are repository-relative; an absolute path is not portable."""
        with pytest.raises(ValidationError):
            ProjectConfig(name="web", root="/srv/web")

    def test_home_relative_root_is_rejected(self) -> None:
        """`~` is absolute once expanded, and expands differently per user."""
        with pytest.raises(ValidationError):
            ProjectConfig(name="web", root="~/code/web")

    def test_root_escaping_the_repository_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectConfig(name="web", root="../elsewhere")

    def test_root_escaping_via_an_interior_dotdot_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectConfig(name="web", root="apps/../../elsewhere")


class TestConfigCarriesZeroAbsolutePaths:
    """Every configured path is repository-relative, `bin_dirs` included.

    A repository is mounted at different places on different machines — a
    container bind mount, a developer's home directory, a CI checkout — so an
    absolute path in committed config is correct on exactly one of them and
    silently wrong everywhere else.
    """

    def test_absolute_bin_dir_is_rejected(self) -> None:
        """The easy one to miss: a plausible-looking system toolchain path."""
        with pytest.raises(ValidationError):
            ProjectConfig(name="web", root="web", bin_dirs=["/usr/local/bin"])

    def test_absolute_bin_dir_among_valid_ones_is_rejected(self) -> None:
        """One bad entry must fail the whole list, not be silently dropped."""
        with pytest.raises(ValidationError):
            ProjectConfig(name="web", root="web", bin_dirs=["node_modules/.bin", "/opt/tools/bin"])

    def test_home_relative_bin_dir_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectConfig(name="web", root="web", bin_dirs=["~/.local/bin"])

    def test_escaping_bin_dir_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProjectConfig(name="web", root="web", bin_dirs=["../shared/bin"])

    def test_relative_bin_dirs_are_kept_and_normalised(self) -> None:
        project = ProjectConfig(name="web", root="web", bin_dirs=["node_modules/.bin/"])

        assert project.bin_dirs == ["node_modules/.bin"]


class TestConfigCarriesAProjectsBlock:
    def test_absent_block_is_empty(self) -> None:
        """Zero-config: no declared projects, so resolution uses the repo root."""
        assert Config().projects == []

    def test_parses_a_multi_project_block(self) -> None:
        raw = {
            "projects": [
                {"name": "web", "root": "web"},
                {"name": "service", "root": "service", "kind": "php"},
                {
                    "name": "infra",
                    "root": "infra",
                    "kind": "ansible",
                    "bin_dirs": [".venv/bin"],
                },
            ]
        }
        config = Config.model_validate(raw)

        assert [project.name for project in config.projects] == ["web", "service", "infra"]
        assert config.projects[1].kind == "php"
        assert config.projects[2].bin_dirs == [".venv/bin"]

    def test_a_declared_project_needs_no_manifest(self) -> None:
        """The report's `infra/` case: config-driven, no manifest anywhere.

        Detection cannot see this project, which is precisely why declaring it
        must not depend on anything detectable.
        """
        config = Config.model_validate({"projects": [{"name": "infra", "root": "infra"}]})

        assert config.projects[0].root == "infra"

    def test_duplicate_names_are_rejected(self) -> None:
        """Two projects sharing a name makes advisory output ambiguous."""
        with pytest.raises(ValidationError):
            Config.model_validate(
                {
                    "projects": [
                        {"name": "web", "root": "web"},
                        {"name": "web", "root": "other"},
                    ]
                }
            )

    def test_duplicate_roots_are_rejected(self) -> None:
        """Two projects at one root cannot both win a nearest-root contest."""
        with pytest.raises(ValidationError):
            Config.model_validate(
                {
                    "projects": [
                        {"name": "web", "root": "apps/web"},
                        {"name": "frontend", "root": "apps/web"},
                    ]
                }
            )

    def test_nested_roots_are_allowed(self) -> None:
        """Nesting is legitimate — a package inside a workspace. Nearest wins."""
        config = Config.model_validate(
            {
                "projects": [
                    {"name": "apps", "root": "apps"},
                    {"name": "web", "root": "apps/web"},
                ]
            }
        )

        assert len(config.projects) == 2

    def test_root_normalises_trailing_slash(self) -> None:
        """`web/` and `web` are the same declaration; equality must agree."""
        config = Config.model_validate({"projects": [{"name": "web", "root": "web/"}]})

        assert config.projects[0].root == "web"

    def test_repo_root_may_be_declared_as_a_project(self) -> None:
        """A monorepo may legitimately also have code at its own root."""
        config = Config.model_validate({"projects": [{"name": "root", "root": "."}]})

        assert config.projects[0].root == "."
