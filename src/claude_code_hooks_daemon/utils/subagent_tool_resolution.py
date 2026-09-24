"""Shared subagent definition resolver (Plans 00460 and 00468).

``subagent_report_size_blocker`` (SubagentStop), ``dispatch_declaration`` and
``agent_isolation_advisor`` (PreToolUse) all ask about the agent a dispatch
names: can it create a NEW file via ``Write``, and does its own definition
declare ``isolation: worktree``? Without one resolver each handler would grow
its own guess, and they could disagree about the very agent that triggered
Plan 00460 (an ``Explore`` stop blocked with "write the report to a file"
when Explore has no Write tool at all).

Resolution order (review M4: PROJECT/USER before built-in, not after —
the vendored doc states a project/user agent named e.g. ``Explore``
OVERRIDES the built-in of the same name; consulting the built-in table
first answered that override wrong):

1. **Project agents** (``<project_root>/.claude/agents/**/*.md``):
   frontmatter ``tools``/``disallowedTools``, matched by the file's `name:`
   field — "identity comes only from the `name` frontmatter field", not the
   filename (vendored doc, "Choose the subagent scope").
2. **User agents** (``<config_dir>/agents/**/*.md``, the config dir from
   :func:`claude_config_dir`): same rule, consulted only when no project
   agent matches — mirrors Claude Code's own project-before-user precedence
   for a shared name.
3. **Built-in types**: a constant table, ONLY for types the vendored
   ``remote-docs/code.claude.com/docs/en/sub-agents.md`` doc explicitly
   enumerates the tools of (Explore, Plan, general-purpose, claude). Two
   further built-ins (``claude-code-guide``, ``statusline-setup``) are named
   in that doc's "Other" table but their TOOL SETS are never documented —
   Task 1.1 requires resolving built-ins from documentation with a citation,
   and there isn't one for these two, so they resolve to unknown rather than
   reusing a secondhand claim (see Plan 00460 journal, T1.1 finding).
4. **Plugin agents** (Plan 00468 P2): an agent of an ENABLED plugin, by its
   scoped id ``<plugin>[:<subdir>...]:<name>``, through
   :func:`resolve_enabled_plugins`. Plugin names are namespaced, so this
   tier can never shadow the three above.
5. Anything else — a MANAGED-settings override (the doc's own precedence
   tier ABOVE project/user, not consulted here) or a name matching nothing
   above — resolves to unknown (review M4 scope note).

Frontmatter that strict YAML rejects is read by the lenient fallback (Plan
00468 P6): Claude Code itself loads such files, e.g. a description holding
``: ``.

``None`` means "cannot resolve"; every caller MUST keep its EXISTING
behaviour for it rather than guessing either way.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.utils.claude_config import claude_config_dir
from claude_code_hooks_daemon.utils.claude_plugins import resolve_enabled_plugins
from claude_code_hooks_daemon.utils.markdown_format import parse_frontmatter_lenient

# Review m5: resolve_lookup_root now lives in path_exclusion.py next to
# resolve_project_root (the one definition of a precedence this module used
# to duplicate); re-exported here (the "import X as X" form mypy recognises
# as deliberate) so this module's existing callers need no import change.
from claude_code_hooks_daemon.utils.path_exclusion import (
    resolve_lookup_root as resolve_lookup_root,
)

_LOGGER = logging.getLogger(__name__)

# Citation: remote-docs/code.claude.com/docs/en/sub-agents.md,
# "Built-in subagents" section — "Tools: read-only tools; Write and Edit are
# denied" for both Explore and Plan.
_BUILTIN_READ_ONLY: Final[frozenset[str]] = frozenset({"Explore", "Plan"})

# Same section: general-purpose's own Tab states "every tool available to
# subagents"; the "Other" table's `claude` row (the main catch-all/background
# default agent) states the same.
_BUILTIN_WRITABLE: Final[frozenset[str]] = frozenset({"general-purpose", "claude"})

_AGENTS_DIR_PARTS: Final[tuple[str, str]] = (".claude", "agents")
_USER_AGENTS_DIR: Final[str] = "agents"
_WRITE_TOOL: Final[str] = "Write"
_WILDCARD_TOOL: Final[str] = "*"
_NAME_FIELD: Final[str] = "name"
_TOOLS_FIELD: Final[str] = "tools"
_DISALLOWED_TOOLS_FIELD: Final[str] = "disallowedTools"
_ISOLATION_FIELD: Final[str] = "isolation"
#: The only ``isolation`` value Claude Code accepts (plugins-reference).
_WORKTREE_ISOLATION: Final[str] = "worktree"
#: Only a scoped id can name a plugin agent: ``<plugin>:<name>``.
_PLUGIN_SCOPE_SEPARATOR: Final[str] = ":"


class AgentSource(StrEnum):
    """Which tier an agent definition came from."""

    PROJECT = "project"
    USER = "user"
    BUILTIN = "builtin"
    PLUGIN = "plugin"


@dataclass(frozen=True)
class AgentDefinition:
    """What the resolver knows about one agent type.

    ``frontmatter`` is empty for a built-in (it has no file) and for a plugin
    agent whose frontmatter is missing. ``can_write`` is None when the
    definition is found but its tool fields cannot be read safely.
    """

    agent_type: str
    source: AgentSource
    path: Path | None
    frontmatter: Mapping[str, Any]
    can_write: bool | None

    @property
    def isolation(self) -> str | None:
        """The declared ``isolation`` value, trimmed and lower-cased, or None."""
        value = self.frontmatter.get(_ISOLATION_FIELD)
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip().lower()

    @property
    def declares_worktree_isolation(self) -> bool:
        """True when the definition itself always runs the agent in a worktree."""
        return self.isolation == _WORKTREE_ISOLATION


# A tool entry can carry a specifier, e.g. `Bash(git push *)` (sub-agents.md,
# "Available tools"): the specifier still names the WHOLE tool, so it is
# stripped before matching -- otherwise a disallowedTools specifier could
# never be told apart from a near-miss string.
_SPECIFIER_RE: Final[re.Pattern[str]] = re.compile(r"\(.*\)$")


def _parse_tool_field(raw: Any) -> set[str] | None:
    """Tool names from a `tools`/`disallowedTools` frontmatter value.

    Accepts a comma-separated string or a YAML list (both documented
    forms). Returns None for a value shaped like neither (e.g. a nested
    mapping) -- a caller receiving None must treat the whole resolution as
    unknown, not guess from a malformed field.
    """
    if isinstance(raw, str):
        items: list[Any] = raw.split(",")
    elif isinstance(raw, list):
        items = raw
    else:
        return None
    names = {_SPECIFIER_RE.sub("", str(item)).strip() for item in items}
    names.discard("")
    return names


def _can_write_from_frontmatter(frontmatter: Mapping[str, Any]) -> bool | None:
    """Write capability from one agent file's parsed frontmatter, or None.

    Per the frontmatter reference: `tools` absent means "inherits every
    tool"; when present, only a listed tool is available. `disallowedTools`
    is documented as applied FIRST, removing from whatever `tools` would
    otherwise resolve to -- so a name in both is removed either way, and the
    order here (start from `tools`, subtract `disallowedTools`) reaches the
    same answer without needing to replicate that ordering literally.
    """
    tools_raw = frontmatter.get(_TOOLS_FIELD)
    if tools_raw is None:
        can_write = True
    else:
        tools = _parse_tool_field(tools_raw)
        if tools is None:
            return None
        can_write = _WRITE_TOOL in tools or _WILDCARD_TOOL in tools

    disallowed_raw = frontmatter.get(_DISALLOWED_TOOLS_FIELD)
    if disallowed_raw is not None:
        disallowed = _parse_tool_field(disallowed_raw)
        if disallowed is None:
            return None
        if _WRITE_TOOL in disallowed:
            can_write = False

    return can_write


def _find_agent_file(agents_dir: Path, agent_type: str) -> tuple[Path, dict[str, Any]] | None:
    """The `.md` file under ``agents_dir`` whose `name:` field equals
    ``agent_type``, with its frontmatter, searched recursively (subfolders
    are scanned per the vendored doc), or None when no such file exists.

    Sorted so a directory with more than one candidate (which should not
    happen for a unique `name`) resolves deterministically rather than by
    filesystem read order.
    """
    if not agents_dir.is_dir():
        return None
    for path in sorted(agents_dir.rglob("*.md")):
        try:
            content = path.read_text()
        except OSError as exc:
            _LOGGER.debug("subagent_tool_resolution: cannot read %s: %s", path, exc)
            continue
        frontmatter = parse_frontmatter_lenient(content)
        if frontmatter is not None and frontmatter.get(_NAME_FIELD) == agent_type:
            return path, frontmatter
    return None


def resolve_agent_definition(
    agent_type: str | None, project_root: Path, *, config_dir: Path | None = None
) -> AgentDefinition | None:
    """Everything the resolver knows about ``agent_type``, or None when unknown.

    ``config_dir`` defaults to :func:`claude_config_dir`; a test passes a
    ``tmp_path`` so the real Claude home is never read. It locates both user
    agents (``<config_dir>/agents``) and installed plugins.

    A built-in whose tools the vendored doc does not enumerate
    (``claude-code-guide``, ``statusline-setup``) has no definition here.
    """
    if not agent_type:
        return None
    config = config_dir if config_dir is not None else claude_config_dir()

    # Review M4: project, THEN user, agents are consulted BEFORE the
    # built-in table -- the vendored doc states a user/project subagent can
    # OVERRIDE a built-in of the same name (e.g. a project's own writable
    # `Explore`), and the earlier built-in-first order failed towards
    # READ-ONLY for that override, the opposite of this module's own
    # documented "unknown, keep today's behaviour" fail-safe contract.
    tiers = (
        (AgentSource.PROJECT, project_root.joinpath(*_AGENTS_DIR_PARTS)),
        (AgentSource.USER, config / _USER_AGENTS_DIR),
    )
    for source, agents_dir in tiers:
        found = _find_agent_file(agents_dir, agent_type)
        if found is not None:
            path, frontmatter = found
            return AgentDefinition(
                agent_type, source, path, frontmatter, _can_write_from_frontmatter(frontmatter)
            )

    if agent_type in _BUILTIN_READ_ONLY or agent_type in _BUILTIN_WRITABLE:
        return AgentDefinition(
            agent_type, AgentSource.BUILTIN, None, {}, agent_type in _BUILTIN_WRITABLE
        )

    if _PLUGIN_SCOPE_SEPARATOR in agent_type:
        agent = resolve_enabled_plugins(project_root, config_dir=config).find_agent(agent_type)
        if agent is not None:
            return AgentDefinition(
                agent_type,
                AgentSource.PLUGIN,
                agent.path,
                agent.frontmatter,
                _can_write_from_frontmatter(agent.frontmatter),
            )

    # A managed-settings override (the doc's own precedence tier above
    # project/user) is not consulted, and is documented as out of scope
    # (review M4).
    return None


def resolve_agent_can_write(
    agent_type: str | None, project_root: Path, *, config_dir: Path | None = None
) -> bool | None:
    """Whether ``agent_type`` can create a NEW file via `Write`.

    Returns True/False when resolvable, None when unknown. `Edit` alone
    cannot create a file, so it plays no part in this answer — only `Write`
    (or a wildcard/absent `tools`, which inherits `Write` too) does. See
    :func:`resolve_agent_definition` for ``config_dir``.
    """
    definition = resolve_agent_definition(agent_type, project_root, config_dir=config_dir)
    return definition.can_write if definition is not None else None
