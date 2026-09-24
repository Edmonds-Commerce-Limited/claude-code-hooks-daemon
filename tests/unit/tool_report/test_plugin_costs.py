"""Tests for the enabled plugins' always-on listing cost (Plan 00468 G15).

Every enabled Claude Code plugin adds to every session's context before it
is ever used: each skill's name and description go into the skill listing,
and each agent's name and description into the agent listing. The skills
docs cap one skill's listed text (``description`` plus ``when_to_use``) at
1,536 characters, and a ``disable-model-invocation: true`` skill is not
listed at all. MCP tool schemas are not measured: that needs the server
running.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_code_hooks_daemon.tool_report.plugin_costs import (
    SKILL_LISTING_MAX_CHARS,
    PluginListingCost,
    plugin_listing_costs,
)
from claude_code_hooks_daemon.utils.claude_plugins import resolve_enabled_plugins
from tests.claude_plugin_fixture import install_fake_plugin

_NAME = "defence-before-fix:"


def _costs(
    tmp_path: Path,
    *,
    skills: dict[str, str] | None = None,
    agents: dict[str, str | None] | None = None,
) -> list[PluginListingCost]:
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True, exist_ok=True)
    config = tmp_path / "config"
    install_fake_plugin(config, project, skills=skills, agents=agents)
    inventory = resolve_enabled_plugins(
        project, config_dir=config, managed_dir=tmp_path / "managed"
    )
    return list(plugin_listing_costs(inventory))


class TestSkills:
    def test_a_skill_costs_its_scoped_name_plus_its_description(self, tmp_path: Path) -> None:
        (cost,) = _costs(tmp_path, skills={"dbf": "name: dbf\ndescription: ten chars!"})
        assert cost.plugin_id == "defence-before-fix@defence-before-fix"
        assert cost.skills_listed == 1
        assert cost.skill_chars == len(f"{_NAME}dbf") + len("ten chars!")

    def test_when_to_use_is_appended_to_the_description(self, tmp_path: Path) -> None:
        (cost,) = _costs(tmp_path, skills={"s": "name: s\ndescription: abc\nwhen_to_use: defg"})
        assert cost.skill_chars == len(f"{_NAME}s") + len("abc defg")

    def test_the_listed_text_is_capped(self, tmp_path: Path) -> None:
        long_text = "x" * (SKILL_LISTING_MAX_CHARS + 500)
        (cost,) = _costs(tmp_path, skills={"s": f"name: s\ndescription: {long_text}"})
        assert cost.skill_chars == len(f"{_NAME}s") + SKILL_LISTING_MAX_CHARS

    @pytest.mark.parametrize("value", ["true", "yes", "On", "1"])
    def test_a_skill_hidden_from_the_model_costs_nothing(self, tmp_path: Path, value: str) -> None:
        (cost,) = _costs(
            tmp_path,
            skills={"s": f"name: s\ndescription: d\ndisable-model-invocation: {value}"},
        )
        assert cost.skills_listed == 0
        assert cost.skills_hidden == 1
        assert cost.skill_chars == 0

    def test_a_missing_description_uses_the_first_body_line(self, tmp_path: Path) -> None:
        (cost,) = _costs(tmp_path, skills={"s": "name: s"})
        # The fixture's SKILL.md body is "Body.".
        assert cost.skill_chars == len(f"{_NAME}s") + len("Body.")

    def test_an_unreadable_skill_costs_only_its_name(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        (project / ".claude").mkdir(parents=True)
        config = tmp_path / "config"
        root = install_fake_plugin(config, project, skills={"s": "description: d"})
        (root / "skills" / "s" / "SKILL.md").write_bytes(b"\xff\xfe not utf-8")
        inventory = resolve_enabled_plugins(
            project, config_dir=config, managed_dir=tmp_path / "managed"
        )
        (cost,) = plugin_listing_costs(inventory)
        assert cost.skill_chars == len(f"{_NAME}s")


class TestAgents:
    def test_an_agent_costs_its_scoped_id_plus_its_description(self, tmp_path: Path) -> None:
        (cost,) = _costs(tmp_path, agents={"r.md": "name: r\ndescription: reviews"})
        assert cost.agents_listed == 1
        assert cost.agent_chars == len(f"{_NAME}r") + len("reviews")

    def test_an_agent_without_frontmatter_uses_the_documented_description(
        self, tmp_path: Path
    ) -> None:
        """plugins-reference: an unparseable plugin agent is described as
        ``Agent from <plugin> plugin``."""
        (cost,) = _costs(tmp_path, agents={"plain.md": None})
        expected = len(f"{_NAME}plain") + len("Agent from defence-before-fix plugin")
        assert cost.agent_chars == expected


class TestTotals:
    def test_total_and_estimated_tokens(self, tmp_path: Path) -> None:
        (cost,) = _costs(
            tmp_path,
            skills={"s": "name: s\ndescription: abc"},
            agents={"r.md": "name: r\ndescription: reviews"},
        )
        assert cost.total_chars == cost.skill_chars + cost.agent_chars
        assert cost.estimated_tokens == -(-cost.total_chars // 4)

    def test_no_enabled_plugins_is_no_rows(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        inventory = resolve_enabled_plugins(
            project, config_dir=tmp_path / "config", managed_dir=tmp_path / "managed"
        )
        assert plugin_listing_costs(inventory) == ()
