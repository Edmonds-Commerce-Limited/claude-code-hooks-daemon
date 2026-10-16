"""How a subagent dispatch's model is chosen, and what kind of work it is (Plan 00472 Task 3.2).

Claude Code resolves a subagent's model in a fixed order (sub-agents.md): the
per-call ``model`` parameter, then the definition's frontmatter ``model``
(``inherit`` means the spawner's), then ``CLAUDE_CODE_SUBAGENT_MODEL``, then the
spawner's own model. A fork always inherits; built-in Explore inherits capped at
Opus, and the env step does not apply to Explore or Plan. :func:`classify`
labels the step that decides (the SOURCE) and predicts the family it yields.

The ROLE is a keyword label over the type, name and description. A type that
names a role (``code-reviewer``, ``qa-runner``) wins over the free text, and fix
and resume are checked before review: 41 of 146 dispatches carrying "review"
were fixers of review findings (472-B section 3.2), a 28 % false positive on the
bare keyword.

Pure functions, except the three readers at the bottom, which every tier
handler shares so they cannot disagree about a dispatch.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HookInputField
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.model_tiers import (
    predicted_explore_family,
    resolve_model_family,
)
from claude_code_hooks_daemon.utils.subagent_tool_resolution import (
    AgentSource,
    resolve_agent_definition,
)
from claude_code_hooks_daemon.utils.transcript_tail import (
    NoUsageInTail,
    read_tail,
    resolve_agent_transcript,
)

logger = logging.getLogger(__name__)


class DispatchSource(StrEnum):
    """Which resolution step chose a dispatch's model."""

    FORK = "fork"
    EXPLICIT = "explicit"
    DEFINITION = "definition"
    ENV = "env"
    INHERITED_CAPPED = "inherited-capped"
    INHERITED = "inherited"


class DispatchRole(StrEnum):
    """What kind of work a dispatch is, as far as its words say."""

    SECURITY = "security"
    ADVERSARIAL = "adversarial"
    DECIDE = "decide"
    FIX = "fix"
    IMPLEMENT = "implement"
    REVIEW = "review"
    VERIFY = "verify"
    SCOUT = "scout"
    DOCS = "docs"
    OTHER = "other"


#: Roles whose work is judgement: the tier advisory never asks them to go cheaper.
TOP_TIER_ROLES: Final[frozenset[DispatchRole]] = frozenset(
    {DispatchRole.SECURITY, DispatchRole.ADVERSARIAL, DispatchRole.DECIDE, DispatchRole.REVIEW}
)

#: Sources nobody chose: the model came from the spawner.
INHERITING_SOURCES: Final[frozenset[DispatchSource]] = frozenset(
    {DispatchSource.FORK, DispatchSource.INHERITED, DispatchSource.INHERITED_CAPPED}
)

#: The prompt line that keeps a deliberate tier: ``tier: <reason>``.
TIER_TOKEN: Final[str] = "tier:"
_TIER_LINE: Final[re.Pattern[str]] = re.compile(r"(?im)^\s*tier:\s*\S")

_FORK_TYPE: Final[str] = "fork"
_EXPLORE_TYPE: Final[str] = "Explore"
#: Built-ins the env step does not reach (sub-agents.md).
_ENV_EXEMPT_TYPES: Final[frozenset[str]] = frozenset({_EXPLORE_TYPE, "Plan"})
#: Built-ins that carry a model of their own (measured: claude-code-guide ran on Haiku).
_BUILTIN_MODELS: Final[Mapping[str, str]] = {"claude-code-guide": "haiku"}
_INHERIT: Final[str] = "inherit"
_MODEL_FIELD: Final[str] = "model"
_ENV_KEY: Final[str] = "CLAUDE_CODE_SUBAGENT_MODEL"
_SETTINGS_PARTS: Final[tuple[str, str]] = (".claude", "settings.json")

# Checked in this order; the first match wins (fix before review, see module docstring).
_ROLE_PATTERNS: Final[tuple[tuple[DispatchRole, re.Pattern[str]], ...]] = (
    (DispatchRole.SECURITY, re.compile(r"secur|\bsec-|secret|safeguard|fail-closed")),
    (DispatchRole.ADVERSARIAL, re.compile(r"adversar|red-?team")),
    (
        DispatchRole.DECIDE,
        re.compile(r"\bdecid|\brule on\b|\bruling|\btriage|\bbrainstorm|\bdesign\b"),
    ),
    (DispatchRole.FIX, re.compile(r"\bfix|\bresume|\bcontinu|\brepair")),
    (DispatchRole.IMPLEMENT, re.compile(r"\bimplement|\bbuild|\bintegrat")),
    (DispatchRole.REVIEW, re.compile(r"review")),
    (DispatchRole.VERIFY, re.compile(r"\bverif|\bqa\b|\bqa-|\btests?\b")),
    (DispatchRole.SCOUT, re.compile(r"scout|\bsearch|\bexplore|\bdedupe|\blocate|\bfind\b")),
    (DispatchRole.DOCS, re.compile(r"\bdocs?\b|\bdocument")),
)


@dataclass(frozen=True)
class DispatchFacts:
    """Everything the classifier reads about one dispatch."""

    subagent_type: str
    #: The call's ``model`` parameter, or "".
    model_param: str
    #: The definition's frontmatter ``model`` (``inherit`` kept), or "".
    definition_model: str
    #: True when no project, user or plugin file defines the type.
    definition_builtin: bool
    #: ``CLAUDE_CODE_SUBAGENT_MODEL`` from the project settings, or "".
    env_model: str
    #: The spawner's model id, or "" when unknown.
    main_model: str


@dataclass(frozen=True)
class DispatchTier:
    """The classifier's verdict on one dispatch."""

    source: DispatchSource
    #: The family the dispatch is predicted to run on; None when unknown.
    predicted_family: str | None
    role: DispatchRole


def _family(model: str) -> str | None:
    resolved = resolve_model_family(model)
    return resolved[0] if resolved is not None else None


def effective_definition_model(facts: DispatchFacts) -> str:
    """The definition's model, falling back to a built-in's own; "" when it has none."""
    if facts.definition_model:
        return facts.definition_model
    if facts.definition_builtin:
        return _BUILTIN_MODELS.get(facts.subagent_type, "")
    return ""


def classify_source(facts: DispatchFacts) -> DispatchSource:
    """The resolution step that chooses this dispatch's model (472-B section 1.2)."""
    if facts.subagent_type == _FORK_TYPE:
        return DispatchSource.FORK
    if facts.model_param:
        return DispatchSource.EXPLICIT
    definition = effective_definition_model(facts)
    if definition and definition != _INHERIT:
        return DispatchSource.DEFINITION
    builtin_exempt = facts.definition_builtin and facts.subagent_type in _ENV_EXEMPT_TYPES
    if facts.env_model and not builtin_exempt:
        return DispatchSource.ENV
    if facts.definition_builtin and facts.subagent_type == _EXPLORE_TYPE:
        return DispatchSource.INHERITED_CAPPED
    return DispatchSource.INHERITED


def predict_family(facts: DispatchFacts, source: DispatchSource) -> str | None:
    """The family ``source`` resolves to; None when the deciding model is unknown."""
    main = _family(facts.main_model)
    if source is DispatchSource.EXPLICIT:
        return main if facts.model_param == _INHERIT else _family(facts.model_param)
    if source is DispatchSource.DEFINITION:
        return _family(effective_definition_model(facts))
    if source is DispatchSource.ENV:
        return _family(facts.env_model)
    if source is DispatchSource.INHERITED_CAPPED:
        return predicted_explore_family(main) if main is not None else None
    return main


def classify_role(subagent_type: str, name: str, description: str) -> DispatchRole:
    """The role a dispatch's words name; the type wins over the free text."""
    for text in (subagent_type.lower(), f"{name} {description}".lower()):
        for role, pattern in _ROLE_PATTERNS:
            if pattern.search(text):
                return role
    return DispatchRole.OTHER


def classify(facts: DispatchFacts, *, name: str, description: str) -> DispatchTier:
    """Source, predicted family and role of one dispatch."""
    source = classify_source(facts)
    return DispatchTier(
        source=source,
        predicted_family=predict_family(facts, source),
        role=classify_role(facts.subagent_type, name, description),
    )


def has_tier_token(prompt: str) -> bool:
    """Whether the prompt carries a ``tier: <reason>`` line keeping its tier."""
    return bool(_TIER_LINE.search(prompt))


def read_env_subagent_model(project_root: Path) -> str:
    """``CLAUDE_CODE_SUBAGENT_MODEL`` from the project ``settings.json`` env block, or "".

    A file read rather than the daemon's own environment, which is not the
    Claude Code process's (472-B section 1.2).
    """
    path = project_root.joinpath(*_SETTINGS_PARTS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ""
    except (OSError, ValueError) as exc:
        log_and_continue(
            logger,
            exc,
            reason=f"an unreadable {path} reads as no env model; the classifier then labels an env-chosen dispatch inherited, and PostToolUse resolvedModel records what really ran",
            level=logging.DEBUG,
        )
        return ""
    env = data.get("env") if isinstance(data, dict) else None
    value = env.get(_ENV_KEY) if isinstance(env, dict) else None
    return value if isinstance(value, str) else ""


def _sidecar_model(untracked: Path, session_id: str) -> str:
    from claude_code_hooks_daemon.handlers.status_line.context_sidecar import sidecar_path

    try:
        data = json.loads(sidecar_path(untracked, session_id).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ""
    except (OSError, ValueError) as exc:
        log_and_continue(
            logger,
            exc,
            reason="an unreadable context sidecar reads as an unknown main model, and unknown means the tier advisories stay silent",
            level=logging.DEBUG,
        )
        return ""
    value = data.get("model_id") if isinstance(data, dict) else None
    return value if isinstance(value, str) else ""


def spawner_model(hook_input: Mapping[str, Any], untracked: Path) -> str:
    """The model id of whoever is dispatching, or "" when unknown.

    The spawner's own transcript tail first (a subagent's when the payload
    carries ``agent_id``), then, for the main thread only, the status line's
    context sidecar: the sidecar names main's model, which is not a subagent's.
    """
    session = str(hook_input.get(HookInputField.SESSION_ID) or "")
    transcript_path = str(hook_input.get(HookInputField.TRANSCRIPT_PATH) or "")
    agent_id = str(hook_input.get(HookInputField.AGENT_ID) or "")
    transcript: Path | None
    if agent_id:
        transcript = resolve_agent_transcript(transcript_path, session, agent_id)
    else:
        transcript = Path(transcript_path) if transcript_path else None
    if transcript is not None:
        try:
            reading = read_tail(transcript)
        except (OSError, NoUsageInTail) as exc:
            log_and_continue(
                logger,
                exc,
                reason="a spawner transcript that cannot be read falls back to the sidecar, then to unknown, which keeps the advisories silent",
                level=logging.DEBUG,
            )
            reading = None
        if reading is not None and reading.model:
            return reading.model
    if agent_id:
        return ""
    return _sidecar_model(untracked, session)


def dispatch_facts(
    tool_input: Mapping[str, Any], *, project_root: Path, main_model: str
) -> DispatchFacts:
    """The classifier's inputs for one ``Agent``/``Task`` call's ``tool_input``."""
    subagent_type = tool_input.get("subagent_type")
    agent_type = subagent_type if isinstance(subagent_type, str) else ""
    model = tool_input.get(_MODEL_FIELD)
    definition = resolve_agent_definition(agent_type, project_root) if agent_type else None
    frontmatter_model = definition.frontmatter.get(_MODEL_FIELD) if definition else None
    return DispatchFacts(
        subagent_type=agent_type,
        model_param=model if isinstance(model, str) else "",
        definition_model=frontmatter_model if isinstance(frontmatter_model, str) else "",
        definition_builtin=definition is None or definition.source is AgentSource.BUILTIN,
        env_model=read_env_subagent_model(project_root),
        main_model=main_model,
    )
