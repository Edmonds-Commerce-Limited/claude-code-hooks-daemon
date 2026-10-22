"""``layout.ansible_configs``: the governing ansible.cfg declaration (GitHub #128)."""

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, LayoutConfig
from claude_code_hooks_daemon.core.project_layout import ProjectLayout


def test_defaults_to_no_declaration() -> None:
    assert LayoutConfig().ansible_configs == {}
    assert ProjectLayout.built_in_default().ansible_configs == {}


def test_reaches_the_root_layout_from_config() -> None:
    config = Config.model_validate(
        {"layout": {"ansible_configs": {"plays/**": "infra/ansible.cfg"}}}
    )

    assert ProjectLayout.from_config(config).ansible_configs == {"plays/**": "infra/ansible.cfg"}


def test_reaches_a_declared_projects_layout() -> None:
    layout = ProjectLayout.for_project(
        LayoutConfig(ansible_configs={"plays/**": "infra/ansible.cfg"}),
        ProjectLayout.built_in_default(),
    )

    assert layout.ansible_configs == {"plays/**": "infra/ansible.cfg"}


@pytest.mark.parametrize("bad", ["/etc/ansible/ansible.cfg", "../ansible.cfg", ""])
def test_a_config_path_must_be_repository_relative(bad: str) -> None:
    with pytest.raises(ValidationError):
        LayoutConfig(ansible_configs={"plays/**": bad})
