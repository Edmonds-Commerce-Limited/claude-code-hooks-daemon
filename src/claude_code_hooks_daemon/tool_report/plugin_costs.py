"""The always-on context cost of enabled Claude Code plugins (Plan 00468 G15).

A plugin costs context in every session before it is ever used: each of its
skills is named and described in the skill listing, and each of its agents
in the agent listing. This module measures that listed text for every
enabled plugin, in characters, from the plugin's own files.

What counts, per the skills docs: a skill's scoped name plus its
``description`` with ``when_to_use`` appended, capped at
:data:`SKILL_LISTING_MAX_CHARS`; with no ``description``, the first non-empty
line of the body stands in. A ``disable-model-invocation`` skill is not
listed and costs nothing. An agent's scoped id plus its ``description``; per
plugins-reference, a plugin agent with no readable frontmatter is described
as ``Agent from <plugin> plugin``.

Not measured: MCP tool schemas (that needs each server running), and the
listing budget, which can shorten descriptions further when a session has
many skills. The token figure is an estimate at
:data:`CHARS_PER_TOKEN_ESTIMATE` characters per token, not a tokenizer count.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from claude_code_hooks_daemon.utils.claude_plugins import (
    EnabledPlugin,
    PluginAgent,
    PluginInventory,
    PluginSkill,
)
from claude_code_hooks_daemon.utils.markdown_format import split_frontmatter

logger = logging.getLogger(__name__)

#: The skills docs' cap on one skill's listed ``description`` + ``when_to_use``.
SKILL_LISTING_MAX_CHARS: Final[int] = 1536

#: A rough English-text ratio, used only to put a token figure beside the
#: measured character count.
CHARS_PER_TOKEN_ESTIMATE: Final[int] = 4

_DESCRIPTION_FIELD: Final[str] = "description"
_WHEN_TO_USE_FIELD: Final[str] = "when_to_use"
_HIDDEN_FIELD: Final[str] = "disable-model-invocation"
#: plugins-reference: plugin skill booleans accept these, in any letter case.
_TRUE_WORDS: Final[frozenset[str]] = frozenset({"true", "yes", "on", "1"})
_UNPARSED_AGENT_DESCRIPTION: Final[str] = "Agent from {plugin} plugin"


@dataclass(frozen=True)
class PluginListingCost:
    """One enabled plugin's always-on listing cost."""

    plugin_id: str
    skills_listed: int
    skills_hidden: int
    agents_listed: int
    skill_chars: int
    agent_chars: int

    @property
    def total_chars(self) -> int:
        return self.skill_chars + self.agent_chars

    @property
    def estimated_tokens(self) -> int:
        """``total_chars`` over :data:`CHARS_PER_TOKEN_ESTIMATE`, rounded up."""
        return -(-self.total_chars // CHARS_PER_TOKEN_ESTIMATE)


def plugin_listing_costs(inventory: PluginInventory) -> tuple[PluginListingCost, ...]:
    """The listing cost of every enabled plugin, in inventory order."""
    return tuple(_plugin_cost(plugin) for plugin in inventory.enabled)


def _plugin_cost(plugin: EnabledPlugin) -> PluginListingCost:
    listed = [skill for skill in plugin.skills if not _is_hidden(skill.frontmatter)]
    return PluginListingCost(
        plugin_id=plugin.plugin_id,
        skills_listed=len(listed),
        skills_hidden=len(plugin.skills) - len(listed),
        agents_listed=len(plugin.agents),
        skill_chars=sum(_skill_chars(skill) for skill in listed),
        agent_chars=sum(_agent_chars(agent, plugin.name) for agent in plugin.agents),
    )


def _is_hidden(frontmatter: Mapping[str, Any]) -> bool:
    value = frontmatter.get(_HIDDEN_FIELD)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE_WORDS if value is not None else False


def _skill_chars(skill: PluginSkill) -> int:
    parts = [
        _text(skill.frontmatter.get(_DESCRIPTION_FIELD)) or _first_body_line(skill),
        _text(skill.frontmatter.get(_WHEN_TO_USE_FIELD)),
    ]
    listed = " ".join(part for part in parts if part)
    return len(skill.scoped_name) + min(len(listed), SKILL_LISTING_MAX_CHARS)


def _agent_chars(agent: PluginAgent, plugin_name: str) -> int:
    description = (
        _text(agent.frontmatter.get(_DESCRIPTION_FIELD))
        if agent.frontmatter
        else _UNPARSED_AGENT_DESCRIPTION.format(plugin=plugin_name)
    )
    return len(agent.scoped_id) + len(description)


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _first_body_line(skill: PluginSkill) -> str:
    """The first non-empty body line, which stands in for a missing description."""
    try:
        content = skill.path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # Unreadable here means Claude Code cannot list a description either.
        logger.debug("plugin_costs: cannot read %s: %s", skill.path, exc)
        content = ""
    _frontmatter, body = split_frontmatter(content)
    return next((line.strip() for line in body.splitlines() if line.strip()), "")
