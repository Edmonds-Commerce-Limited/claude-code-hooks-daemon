"""Measured per-tool schema token costs and known disable routes.

Grounding: Plan 00293 Phase 1 (``RESEARCH-tool-disable.md``). The numbers were
measured on 2026-08-30 by transcribing the rendered schema blocks from a live
Claude Code session's system prompt and token-counting with tiktoken
``cl100k_base`` — a proxy for the Claude tokenizer, treat as ±10-15%.
Rendered schemas are session-variant (feature-gated fragments), so every
consumer of this table must present the values as ESTIMATES and point at
``/context`` for a session's own ground truth.

Loading classes:

- ``upfront``: the full schema is resident in every session's context.
- ``deferred``: only the tool NAME is resident (~8 tokens); the schema loads
  on demand via ToolSearch, so a deferred tool is already nearly free and
  disabling it saves almost nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

# Context cost of one deferred tool: its name line in the deferred-tools
# listing (measured: 11 names in ~105 cl100k tokens of listing).
DEFERRED_NAME_TOKENS = 8


@dataclass(frozen=True)
class ToolCost:
    """One tool's measured schema cost and how it loads."""

    tokens: int
    loading: str  # "upfront" | "deferred"


MEASURED_SCHEMA_TOKENS: dict[str, ToolCost] = {
    # Upfront-loaded tools: full rendered schema (description + parameters).
    "Artifact": ToolCost(tokens=6038, loading="upfront"),
    "Agent": ToolCost(tokens=836, loading="upfront"),
    "Bash": ToolCost(tokens=704, loading="upfront"),
    "Read": ToolCost(tokens=430, loading="upfront"),
    "Skill": ToolCost(tokens=419, loading="upfront"),
    "ToolSearch": ToolCost(tokens=347, loading="upfront"),
    "Write": ToolCost(tokens=268, loading="upfront"),
    "Edit": ToolCost(tokens=242, loading="upfront"),
    # Deferred tools: name-only until fetched via ToolSearch.
    "CronCreate": ToolCost(tokens=DEFERRED_NAME_TOKENS, loading="deferred"),
    "CronDelete": ToolCost(tokens=DEFERRED_NAME_TOKENS, loading="deferred"),
    "CronList": ToolCost(tokens=DEFERRED_NAME_TOKENS, loading="deferred"),
    "EnterWorktree": ToolCost(tokens=DEFERRED_NAME_TOKENS, loading="deferred"),
    "ExitWorktree": ToolCost(tokens=DEFERRED_NAME_TOKENS, loading="deferred"),
    "Monitor": ToolCost(tokens=DEFERRED_NAME_TOKENS, loading="deferred"),
    "NotebookEdit": ToolCost(tokens=DEFERRED_NAME_TOKENS, loading="deferred"),
    "SendMessage": ToolCost(tokens=DEFERRED_NAME_TOKENS, loading="deferred"),
    "TaskStop": ToolCost(tokens=DEFERRED_NAME_TOKENS, loading="deferred"),
    "WebFetch": ToolCost(tokens=DEFERRED_NAME_TOKENS, loading="deferred"),
    "WebSearch": ToolCost(tokens=DEFERRED_NAME_TOKENS, loading="deferred"),
}

# Artifact has a dedicated, documented settings switch that no other file can
# re-enable once set — strictly stronger than a deny rule.
_ARTIFACT_ROUTE = (
    'settings: `"enableArtifact": false` in `.claude/settings.json` '
    "(or `CLAUDE_CODE_DISABLE_ARTIFACT=1`; this daemon can enforce it via "
    "`handlers.pre_tool_use.artifact_publish_blocker.options.source_disable: true`)"
)

# Bare tool-name deny rules remove the tool from the session's available set;
# specifier/parameter rules do NOT (call-time refusal only, zero token
# savings) — see RESEARCH-tool-disable.md.
_GENERIC_ROUTE = 'settings: add "{tool}" to `permissions.deny` (bare tool name, no specifier)'


def disable_route_for(tool: str) -> str:
    """The known source-disable route for a tool, as advice text."""
    if tool == "Artifact":
        return _ARTIFACT_ROUTE
    return _GENERIC_ROUTE.format(tool=tool)
