"""A project-declared governing ansible.cfg for plays outside its tree (GitHub #128)."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.strategies.lint.module_context import (
    GoverningConfigError,
    missing_config_note,
    resolve_module_context,
)


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A project whose ansible.cfg lives in ``infra/`` and whose plays live in ``plays/``."""
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / "ansible.cfg").write_text("[defaults]\n")
    (tmp_path / "plays").mkdir()
    (tmp_path / "plays" / "site.yml").write_text("- hosts: all\n")
    return tmp_path


class TestDeclaredConfig:
    def test_a_matching_glob_roots_the_module_at_the_config_directory(self, project: Path) -> None:
        context = resolve_module_context(
            str(project / "plays" / "site.yml"),
            "Ansible",
            project_root=project,
            ansible_configs={"plays/**": "infra/ansible.cfg"},
        )

        assert context.module_root == str(project / "infra")
        assert context.governing_config == str(project / "infra" / "ansible.cfg")
        assert context.env == {"ANSIBLE_CONFIG": str(project / "infra" / "ansible.cfg")}

    def test_the_declaration_wins_over_a_marker_found_by_walking_up(self, project: Path) -> None:
        (project / "plays" / "ansible.cfg").write_text("[defaults]\n")

        context = resolve_module_context(
            str(project / "plays" / "site.yml"),
            "Ansible",
            project_root=project,
            ansible_configs={"plays/**": "infra/ansible.cfg"},
        )

        assert context.module_root == str(project / "infra")

    def test_a_play_matching_no_glob_falls_back_to_the_marker_walk(self, project: Path) -> None:
        other = project / "other"
        other.mkdir()
        (other / "ansible.cfg").write_text("[defaults]\n")
        play = other / "site.yml"
        play.write_text("- hosts: all\n")

        context = resolve_module_context(
            str(play),
            "Ansible",
            project_root=project,
            ansible_configs={"plays/**": "infra/ansible.cfg"},
        )

        assert context.module_root == str(other)
        assert context.governing_config == str(other / "ansible.cfg")

    def test_a_declared_config_that_does_not_exist_is_a_loud_error(self, project: Path) -> None:
        with pytest.raises(GoverningConfigError, match="infra/missing.cfg"):
            resolve_module_context(
                str(project / "plays" / "site.yml"),
                "Ansible",
                project_root=project,
                ansible_configs={"plays/**": "infra/missing.cfg"},
            )

    def test_the_declaration_is_ignored_for_other_languages(self, project: Path) -> None:
        source = project / "plays" / "a.py"
        source.write_text("")

        context = resolve_module_context(
            str(source),
            "Python",
            project_root=project,
            ansible_configs={"plays/**": "infra/ansible.cfg"},
        )

        assert context.module_root is None
        assert context.env == {}
        assert context.governing_config is None


class TestWorkingDir:
    def test_prefers_the_module_root(self, project: Path) -> None:
        context = resolve_module_context(
            str(project / "plays" / "site.yml"),
            "Ansible",
            project_root=project,
            ansible_configs={"plays/**": "infra/ansible.cfg"},
        )

        assert context.working_dir(project) == str(project / "infra")

    def test_falls_back_to_the_given_workspace_root(self, project: Path) -> None:
        context = resolve_module_context(str(project / "plays" / "site.yml"), "Ansible")

        assert context.module_root is None
        assert context.working_dir(project) == str(project)


class TestMissingConfigNote:
    def test_names_the_option_when_ansible_ran_without_a_config(self, project: Path) -> None:
        context = resolve_module_context(str(project / "plays" / "site.yml"), "Ansible")

        note = missing_config_note("Ansible", context)

        assert note is not None
        assert "no ansible.cfg was in effect" in note
        assert "layout.ansible_configs" in note

    def test_is_silent_when_a_config_governed_the_run(self, project: Path) -> None:
        context = resolve_module_context(
            str(project / "plays" / "site.yml"),
            "Ansible",
            project_root=project,
            ansible_configs={"plays/**": "infra/ansible.cfg"},
        )

        assert missing_config_note("Ansible", context) is None

    def test_is_silent_for_other_languages(self, project: Path) -> None:
        context = resolve_module_context(str(project / "a.py"), "Python")

        assert missing_config_note("Python", context) is None
