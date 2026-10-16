"""SubagentTierAdvisorHandler - name a cheaper tier, or a floor, at dispatch time (Plan 00472 T3/T4).

A subagent nobody chose a model for runs on its spawner's: 36.5 % of measured
agents never had a model chosen, and 135 of those 142 ran on Opus (472-B
section 2.1). The single largest pattern, 27 % of subagent spend, was an
explicit ``model: opus`` on a type whose own definition says ``sonnet``.

On an ``Agent``/``Task`` dispatch, in the main thread or a subagent, it advises
when one of three triggers holds:

- **inherited top tier** (``inherited``, ``inherited-capped``, ``fork``): the
  predicted family is above the type's ``ceiling`` (else ``default_ceiling``);
  with no ceiling configured, when it is Opus or above, naming the next tier
  down;
- **explicit above the definition**: the ``model`` parameter outranks the
  definition's own model, naming the definition's.

It is silent on a security, adversarial, decide or review role, on a
``tier: <reason>`` line in the prompt, on an explicit model not above the
definition, and whenever the spawner's model is unknown. The inverse, the FLOOR
advisory, fires when a dispatch resolves below the type's ``floor`` or its
role's ``role_floors`` entry. Each fires once per ``(session, subagent_type,
source)``, counted only when the dispatch went ahead, and each is a ledger event.

**Advisory only, by ruling (D4).** ``mode`` accepts only ``advise``; the key is
reserved so a later enforcing mode is one value, not a schema change.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    SUBAGENT_DISPATCH_TOOL_NAMES,
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
)
from claude_code_hooks_daemon.core import Decision, GatingResult, ProjectContext
from claude_code_hooks_daemon.core.chain import is_restrictive
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.dispatch_tier import (
    INHERITING_SOURCES,
    TOP_TIER_ROLES,
    DispatchFacts,
    DispatchRole,
    DispatchSource,
    DispatchTier,
    classify,
    dispatch_facts,
    effective_definition_model,
    has_tier_token,
    spawner_model,
)
from claude_code_hooks_daemon.utils.model_tiers import (
    FAMILIES,
    OPUS,
    family_below,
    family_rank,
    resolve_model_family,
)
from claude_code_hooks_daemon.utils.spend_ledger import (
    append_event,
    read_state,
    state_path,
    write_state,
)

logger = logging.getLogger(__name__)

MODE_ADVISE: Final[str] = "advise"
_MODES: Final[frozenset[str]] = frozenset({MODE_ADVISE})
_TYPE_KEYS: Final[frozenset[str]] = frozenset({"ceiling", "floor"})
_ROLES: Final[frozenset[str]] = frozenset(role.value for role in DispatchRole)
_STATE_KIND: Final[str] = "tier-advisory"
_FLOOR_KEY: Final[str] = "floor"
_ADVISED: Final[str] = "advised"
_KIND_TIER: Final[str] = "tier-advisory"
_KIND_FLOOR: Final[str] = "tier-floor-advisory"

_SOURCE_REASONS: Final[Mapping[DispatchSource, str]] = {
    DispatchSource.INHERITED: "it inherits its spawner's model",
    DispatchSource.FORK: "a fork always inherits its spawner's model",
    DispatchSource.INHERITED_CAPPED: "built-in Explore inherits its spawner's model, capped at opus",
}


@dataclass(frozen=True)
class _Verdict:
    """One advisory this dispatch draws."""

    kind: str
    key: str
    message: str
    tier: DispatchTier
    suggested: str


def _family(model: str) -> str | None:
    resolved = resolve_model_family(model)
    return resolved[0] if resolved is not None else None


def _rank(family: str) -> int:
    rank = family_rank(family)
    return rank if rank is not None else -1


def _text(tool_input: Mapping[str, Any], field: str) -> str:
    value = tool_input.get(field)
    return value if isinstance(value, str) else ""


class SubagentTierAdvisorHandler(PreToolUseHandlerBase):
    """Advise a cheaper tier on an unchosen or up-overridden dispatch, and a floor below it."""

    #: None reads as ``advise``, the only mode; each ledger event records it.
    _mode: str | None = None
    _default_ceiling: str | None = None
    _types: Mapping[str, Mapping[str, str]] | None = None
    _role_floors: Mapping[str, str] | None = None

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SUBAGENT_TIER_ADVISOR,
            priority=Priority.SUBAGENT_TIER_ADVISOR,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        self._untracked_override: Path | None = None
        self._project_root_override: Path | None = None

    @staticmethod
    def validate_options(options: Mapping[str, Any]) -> dict[str, str]:
        """Refuse a malformed option; the handler then runs on its default for it."""
        problems: dict[str, str] = {}
        if "mode" in options and options["mode"] not in _MODES:
            problems["mode"] = f"mode must be one of {', '.join(sorted(_MODES))}"
        ceiling = options.get("default_ceiling")
        if ceiling is not None and ceiling not in FAMILIES:
            problems["default_ceiling"] = f"default_ceiling must be null or one of {FAMILIES}"
        types = options.get("types")
        if types is not None and not (
            isinstance(types, Mapping)
            and all(
                isinstance(name, str)
                and isinstance(entry, Mapping)
                and set(entry) <= _TYPE_KEYS
                and all(value in FAMILIES for value in entry.values())
                for name, entry in types.items()
            )
        ):
            problems["types"] = (
                f"types maps a subagent_type to {{ceiling, floor}}, each one of {FAMILIES}"
            )
        floors = options.get("role_floors")
        if floors is not None and not (
            isinstance(floors, Mapping)
            and all(role in _ROLES and value in FAMILIES for role, value in floors.items())
        ):
            problems["role_floors"] = f"role_floors maps a role in {sorted(_ROLES)} to a family"
        return problems

    def _untracked_dir(self) -> Path:
        return self._untracked_override or ProjectContext.daemon_untracked_dir()

    def _project_root(self) -> Path:
        return self._project_root_override or ProjectContext.project_root()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every ``Agent``/``Task`` dispatch; whether it draws advice is judged in handle()."""
        return hook_input.get(HookInputField.TOOL_NAME) in SUBAGENT_DISPATCH_TOOL_NAMES

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Advise, once per key; always ALLOW."""
        verdict = self._judge(hook_input)
        if verdict is None or self._advised(hook_input, verdict.key):
            return GatingResult(decision=Decision.ALLOW)
        return GatingResult(decision=Decision.ALLOW, context=[verdict.message])

    def commit_side_effects(self, hook_input: dict[str, Any], chain_decision: Decision) -> None:
        """Spend the key and record the event, only when the dispatch went ahead."""
        if is_restrictive(chain_decision):
            return
        verdict = self._judge(hook_input)
        if verdict is None or self._advised(hook_input, verdict.key):
            return
        session = str(hook_input.get(HookInputField.SESSION_ID) or "")
        write_state(self._state_file(session, verdict.key), {_ADVISED: True})
        append_event(
            self._untracked_dir(),
            session,
            {
                "kind": verdict.kind,
                "subagent_type": verdict.key.split("|", 1)[0],
                "source": verdict.tier.source.value,
                "role": verdict.tier.role.value,
                "predicted_family": verdict.tier.predicted_family,
                "suggested": verdict.suggested,
                "mode": self._mode or MODE_ADVISE,
            },
        )

    def _state_file(self, session: str, key: str) -> Path:
        return state_path(self._untracked_dir(), session, _STATE_KIND, key)

    def _advised(self, hook_input: dict[str, Any], key: str) -> bool:
        session = str(hook_input.get(HookInputField.SESSION_ID) or "")
        return read_state(self._state_file(session, key)).get(_ADVISED) is True

    def _judge(self, hook_input: dict[str, Any]) -> _Verdict | None:
        """The advisory this dispatch draws, or None; a failure to judge is silent."""
        tool_input = hook_input.get(HookInputField.TOOL_INPUT)
        if not isinstance(tool_input, dict) or has_tier_token(_text(tool_input, "prompt")):
            return None
        facts: DispatchFacts | None = None
        try:
            main_model = spawner_model(hook_input, self._untracked_dir())
            if _family(main_model) is not None:
                facts = dispatch_facts(
                    tool_input, project_root=self._project_root(), main_model=main_model
                )
        except (OSError, RuntimeError) as exc:
            log_and_continue(
                logger,
                exc,
                reason="a dispatch the tier advisor cannot classify draws no advice; it never blocks",
                level=logging.DEBUG,
            )
        if facts is None:
            return None
        tier = classify(
            facts, name=_text(tool_input, "name"), description=_text(tool_input, "description")
        )
        if tier.predicted_family is None:
            return None
        return self._floor_verdict(facts, tier) or self._ceiling_verdict(facts, tier)

    def _type_entry(self, subagent_type: str) -> Mapping[str, str]:
        entry = (self._types or {}).get(subagent_type)
        return entry if isinstance(entry, Mapping) else {}

    def _floor_verdict(self, facts: DispatchFacts, tier: DispatchTier) -> _Verdict | None:
        predicted = str(tier.predicted_family)
        type_floor = self._type_entry(facts.subagent_type).get("floor")
        floor = type_floor or (self._role_floors or {}).get(tier.role.value)
        if not floor or _rank(predicted) >= _rank(floor):
            return None
        whom = f"`{facts.subagent_type}`" if type_floor else f"{tier.role.value} work"
        return _Verdict(
            kind=_KIND_FLOOR,
            key=f"{facts.subagent_type}|{_FLOOR_KEY}",
            message=(
                f"TIER FLOOR: this `{facts.subagent_type}` dispatch resolves to {predicted}, "
                f"below the {floor} floor for {whom}.\n"
                f"Pass `model: {floor}`, or add a line `tier: <reason>` to the prompt if the "
                "lower tier is deliberate."
            ),
            tier=tier,
            suggested=floor,
        )

    def _ceiling_verdict(self, facts: DispatchFacts, tier: DispatchTier) -> _Verdict | None:
        if tier.role in TOP_TIER_ROLES:
            return None
        predicted = str(tier.predicted_family)
        cheaper: str | None = None
        reason = _SOURCE_REASONS.get(tier.source, "")
        if tier.source in INHERITING_SOURCES:
            ceiling = self._type_entry(facts.subagent_type).get("ceiling") or self._default_ceiling
            if ceiling:
                cheaper = ceiling if _rank(predicted) > _rank(ceiling) else None
            elif _rank(predicted) >= _rank(OPUS):
                cheaper = family_below(predicted)
        elif tier.source is DispatchSource.EXPLICIT:
            definition = _family(effective_definition_model(facts))
            if definition is not None and _rank(predicted) > _rank(definition):
                cheaper = definition
                reason = (
                    f"the call passes `model: {facts.model_param}` above its definition's "
                    f"`{definition}`"
                )
        if cheaper is None:
            return None
        work = (
            f"Routine {tier.role.value} work"
            if tier.role is not DispatchRole.OTHER
            else "Routine work"
        )
        return _Verdict(
            kind=_KIND_TIER,
            key=f"{facts.subagent_type}|{tier.source.value}",
            message=(
                f"TIER: this `{facts.subagent_type}` dispatch runs on {predicted} because {reason}.\n"
                f"{work} fits {cheaper}: pass `model: {cheaper}`, or add a line "
                f"`tier: <reason>` to the prompt to keep {predicted}."
            ),
            tier=tier,
            suggested=cheaper,
        )

    def get_claude_md(self) -> str | None:
        """T2: the advice arrives with the dispatch and governs the next one; no standing rule."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """A dispatch that inherits the top tier draws the advisory; one carrying ``tier:`` does not."""
        from claude_code_hooks_daemon.constants.tools import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        fires = ToolPayload(
            tool_name=ToolName.AGENT,
            tool_input={
                "subagent_type": "general-purpose",
                "description": "Rename one variable",
                "prompt": "Reply with the word done and nothing else.",
            },
        )
        token = ToolPayload(
            tool_name=ToolName.AGENT,
            tool_input={
                "subagent_type": "general-purpose",
                "description": "Rename one variable",
                "prompt": "Reply with the word done and nothing else.\ntier: acceptance probe",
            },
        )
        return [
            AcceptanceTest(
                title="subagent tier advisor - an inherited top-tier dispatch is advised",
                command=fires.as_instruction(),
                description=(
                    "Run from an Opus or Fable main thread. The dispatch is allowed with a "
                    "TIER advisory naming the cheaper tier (once per session and source). The "
                    "fire/silent matrix is in tests/unit/handlers/pre_tool_use/"
                    "test_subagent_tier_advisor.py."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"TIER: this `general-purpose` dispatch runs on"],
                safety_notes="Advisory only; the dispatched agent replies with one word.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=True,
                tool_payload=fires,
            ),
            AcceptanceTest(
                title="subagent tier advisor - a tier: line keeps the tier silently",
                command=token.as_instruction(),
                description="The same dispatch carrying `tier: <reason>` draws no advisory.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Advisory only; the dispatched agent replies with one word.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=True,
                tool_payload=token,
            ),
        ]
