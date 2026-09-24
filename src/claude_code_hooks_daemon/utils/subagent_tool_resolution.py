"""Shared subagent Write-capability resolver (Plan 00460).

``subagent_report_size_blocker`` (SubagentStop) and ``dispatch_declaration``
(PreToolUse) both need the same answer to the same question: can a given
``agent_type``/``subagent_type`` create a NEW file via ``Write``? Without one
resolver each handler would grow its own guess, and the two could disagree
about the very agent that triggered Plan 00460 (an ``Explore`` stop blocked
with "write the report to a file" when Explore has no Write tool at all).

Resolution order — each documented with the built-in table's citation and
the project/user-agent frontmatter fields below:

1. **Built-in types**: a constant table, ONLY for types the vendored
   ``remote-docs/code.claude.com/docs/en/sub-agents.md`` doc explicitly
   enumerates the tools of (Explore, Plan, general-purpose, claude). Two
   further built-ins (``claude-code-guide``, ``statusline-setup``) are named
   in that doc's "Other" table but their TOOL SETS are never documented —
   Task 1.1 requires resolving built-ins from documentation with a citation,
   and there isn't one for these two, so they resolve to unknown rather than
   reusing a secondhand claim (see Plan 00460 journal, T1.1 finding).
2. **Project agents** (``<project_root>/.claude/agents/**/*.md``):
   frontmatter ``tools``/``disallowedTools``, matched by the file's `name:`
   field — "identity comes only from the `name` frontmatter field", not the
   filename (same vendored doc, "Choose the subagent scope").
3. **User agents** (``<home_dir>/.claude/agents/**/*.md``): same rule,
   consulted only when no project agent matches — mirrors Claude Code's own
   project-before-user precedence for a shared name.
4. Anything else — a plugin agent (not cheaply resolvable: its location
   depends on marketplace/plugin config this module does not track) or a
   name matching nothing above — resolves to unknown.

``None`` means "cannot resolve"; every caller MUST keep its EXISTING
behaviour for it rather than guessing either way.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.utils.markdown_format import parse_frontmatter_yaml
from claude_code_hooks_daemon.utils.path_exclusion import resolve_project_root

# Citation: remote-docs/code.claude.com/docs/en/sub-agents.md,
# "Built-in subagents" section — "Tools: read-only tools; Write and Edit are
# denied" for both Explore and Plan.
_BUILTIN_READ_ONLY: Final[frozenset[str]] = frozenset({"Explore", "Plan"})

# Same section: general-purpose's own Tab states "every tool available to
# subagents"; the "Other" table's `claude` row (the main catch-all/background
# default agent) states the same.
_BUILTIN_WRITABLE: Final[frozenset[str]] = frozenset({"general-purpose", "claude"})

_AGENTS_DIR_PARTS: Final[tuple[str, str]] = (".claude", "agents")
_WRITE_TOOL: Final[str] = "Write"
_WILDCARD_TOOL: Final[str] = "*"
_NAME_FIELD: Final[str] = "name"
_TOOLS_FIELD: Final[str] = "tools"
_DISALLOWED_TOOLS_FIELD: Final[str] = "disallowedTools"

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


def _can_write_from_frontmatter(frontmatter: dict[str, Any]) -> bool | None:
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


def _find_agent_frontmatter(agents_dir: Path, agent_type: str) -> dict[str, Any] | None:
    """Frontmatter of the `.md` file under ``agents_dir`` whose `name:`
    field equals ``agent_type``, searched recursively (subfolders are
    scanned per the vendored doc), or None when no such file exists.

    Sorted so a directory with more than one candidate (which should not
    happen for a unique `name`) resolves deterministically rather than by
    filesystem read order.
    """
    if not agents_dir.is_dir():
        return None
    for path in sorted(agents_dir.rglob("*.md")):
        try:
            content = path.read_text()
        except OSError:
            continue
        frontmatter = parse_frontmatter_yaml(content)
        if frontmatter is not None and frontmatter.get(_NAME_FIELD) == agent_type:
            return frontmatter
    return None


def resolve_agent_can_write(
    agent_type: str | None, project_root: Path, *, home_dir: Path | None = None
) -> bool | None:
    """Whether ``agent_type`` can create a NEW file via `Write`.

    Returns True/False when resolvable, None when unknown. `Edit` alone
    cannot create a file, so it plays no part in this answer — only `Write`
    (or a wildcard/absent `tools`, which inherits `Write` too) does.

    ``home_dir`` defaults to :meth:`Path.home` in production; a test passes
    a ``tmp_path`` so this function never touches the real home directory.
    """
    if not agent_type:
        return None

    if agent_type in _BUILTIN_READ_ONLY:
        return False
    if agent_type in _BUILTIN_WRITABLE:
        return True

    for base in (project_root, home_dir if home_dir is not None else Path.home()):
        frontmatter = _find_agent_frontmatter(base.joinpath(*_AGENTS_DIR_PARTS), agent_type)
        if frontmatter is not None:
            return _can_write_from_frontmatter(frontmatter)

    # Plugin agents are not cheaply resolvable here: their on-disk location
    # depends on marketplace/plugin configuration this module does not
    # track (Plan 00460 Task 1.1 scope decision).
    return None


def resolve_lookup_root(
    project_root_override: Path | None, workspace_root: Path | str | None
) -> Path:
    """The directory an ``agent_type``'s `.claude/agents/` lookup is rooted at.

    Shared by every handler that calls :func:`resolve_agent_can_write`
    (``subagent_report_size_blocker`` and ``dispatch_declaration``) so the
    two never resolve a different root for the same agent type. An injected
    TEST override wins, then the registry's ``workspace_root`` option, then
    :func:`resolve_project_root` (None when ``ProjectContext`` is not
    initialised, e.g. a bare unit test), falling back to the process cwd so
    this always returns a concrete path.
    """
    if project_root_override is not None:
        return project_root_override
    if workspace_root is not None:
        return Path(workspace_root)
    resolved = resolve_project_root()
    return Path(resolved) if resolved is not None else Path.cwd()
