"""BranchRejectDispatchGateHandler - a branch-reject reviewer runs only on the daemon's prompt.

Plan 00620 Task 2.2. ``hooks-daemon branch-reject request <branch>`` records a request
and prints a review prompt whose first line carries the request's nonce. This gate
admits a dispatch of that prompt only when it is byte-equal to the recorded one (its
sha256), names the shipped reviewer type, is predicted to run on Opus or above, is a
fresh agent rather than a resumed one, and the deployed reviewer definition is the
shipped one. It then records the nonce's dispatch, unbound; the PostToolUse binder
fills in the agent id. All judgement lives in ``core.branch_reject``.

It matches in both directions: the reviewer type with any prompt, and a review prompt
under any type. Everything else passes untouched.

**It fails closed.** Every dependency that raises (the project root, the spawner
model, the agent definition, the main checkout, the state store) denies the call
before anything is written, and the only write is the exclusive create of the
dispatch record, made last.

**Disabling it fails closed too.** With the gate off no dispatch record is written,
and a verdict whose nonce has no dispatch record never chains, so no removal can be
unlocked. That is why it needs no "cannot be disabled" treatment.

**Priority 59.** An ALLOW never ends the chain, so a deny from a later handler would
leave the nonce recorded as dispatched for an agent that never ran. It therefore
runs after every handler that can deny an ``Agent`` call; only advisories follow it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.config.models import BranchesConfig
from claude_code_hooks_daemon.constants import (
    SUBAGENT_DISPATCH_TOOL_NAMES,
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, ProjectContext
from claude_code_hooks_daemon.core.branch_reject import (
    PROMPT_MARKER,
    REVIEWER_AGENT_TYPE,
    DispatchCall,
    RejectRefusedError,
    RejectStore,
    admit_dispatch,
    is_reviewer_dispatch,
    main_checkout,
)
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.install.agent_assets import (
    BRANCH_REJECT_REVIEWER_AGENT_NAME,
    AgentAssetState,
    classify_agent,
    spec_by_name,
)
from claude_code_hooks_daemon.utils.dispatch_tier import classify, dispatch_facts, spawner_model
from claude_code_hooks_daemon.utils.scratch_dir import acceptance_path

_SUBAGENT_TYPE_FIELD: Final[str] = "subagent_type"
_PROMPT_FIELD: Final[str] = "prompt"
_NAME_FIELD: Final[str] = "name"
_DESCRIPTION_FIELD: Final[str] = "description"
#: Present on a call that asks to continue an earlier agent rather than start one.
_RESUME_FIELD: Final[str] = "resume"

_RULE: Final[Rule] = Rule(
    rule_id=RuleID.BRANCH_REJECT_DISPATCH,
    blocked="a branch-reject reviewer dispatch the gate cannot admit",
    why=(
        "A no-value verdict can unlock a branch removal, so the reviewer must run on the "
        "exact prompt the daemon composed, as a fresh Opus agent of the shipped definition"
    ),
    fix=(
        "Run `hooks-daemon branch-reject request <branch>` and dispatch the "
        f"{REVIEWER_AGENT_TYPE} agent with the printed prompt, byte for byte, and no model "
        "parameter"
    ),
    verbose=(
        "WHY BLOCKED:\n"
        "A branch-reject reviewer's verdict is one of the two facts that can unlock the\n"
        "removal of a branch whose work no proof clears. The daemon therefore admits a\n"
        "reviewer only on the prompt it composed itself, recorded by\n"
        "`hooks-daemon branch-reject request <branch>`, dispatched once, to the shipped\n"
        f"`{REVIEWER_AGENT_TYPE}` type, on Opus or above, as a fresh agent.\n\n"
        "DO INSTEAD:\n"
        "  - Run `hooks-daemon branch-reject request <branch>` and pass each printed\n"
        "    prompt to its own Agent call, byte for byte, with no `model` parameter.\n"
        "  - A nonce dispatches once. If a dispatch was refused or lost, run the\n"
        "    request again for a fresh prompt.\n"
        "  - If the deployed definition is not the shipped one, run `hooks-daemon\n"
        "    upgrade` to redeploy it."
    ),
)


def _text(tool_input: dict[str, Any], field: str) -> str:
    value = tool_input.get(field)
    return value if isinstance(value, str) else ""


def _hook_text(hook_input: dict[str, Any], field: str) -> str:
    value = hook_input.get(field)
    return value if isinstance(value, str) else ""


class BranchRejectDispatchGateHandler(PreToolUseHandlerBase):
    """Admit a branch-reject reviewer dispatch only on the daemon's prompt; else deny.

    Terminal: a deny is the final word on the call. An allow does not end the chain,
    which is why the gate sits after every other handler that can deny an Agent call.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.BRANCH_REJECT_DISPATCH_GATE,
            priority=Priority.BRANCH_REJECT_DISPATCH_GATE,
            terminal=True,
            tags=[HandlerTag.SAFETY, HandlerTag.BLOCKING, HandlerTag.WORKFLOW],
        )
        # The registry injects the project's own ``branches`` config here.
        self._branches: BranchesConfig = BranchesConfig()

    def get_default_enabled(self) -> bool:
        """Opt-OUT: on by default. Off fails closed (no dispatch record, no verdict)."""
        return True

    @staticmethod
    def _project_root() -> Path:
        return ProjectContext.project_root()

    @staticmethod
    def _untracked_dir() -> Path:
        return ProjectContext.daemon_untracked_dir()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for the reviewer type with any prompt, or a review prompt under any type."""
        if hook_input.get(HookInputField.TOOL_NAME) not in SUBAGENT_DISPATCH_TOOL_NAMES:
            return False
        tool_input = hook_input.get(HookInputField.TOOL_INPUT)
        if not isinstance(tool_input, dict):
            return False
        return is_reviewer_dispatch(
            _text(tool_input, _SUBAGENT_TYPE_FIELD), _text(tool_input, _PROMPT_FIELD)
        )

    def get_rules(self) -> list[Rule]:
        """The single Rule backing this handler's deny."""
        return [_RULE]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Admit and record the dispatch, or deny naming every problem."""
        try:
            call, store = self._judge_inputs(hook_input)
            admit_dispatch(call, store)
        except RejectRefusedError as exc:
            return self._deny(str(exc))
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            return self._deny(f"the gate could not judge the dispatch, so it is refused: {exc}")
        return GatingResult(decision=Decision.ALLOW)

    def _judge_inputs(self, hook_input: dict[str, Any]) -> tuple[DispatchCall, RejectStore]:
        """Every read the gate needs, made before anything is written."""
        tool_input = hook_input[HookInputField.TOOL_INPUT]
        root = self._project_root()
        main_model = spawner_model(hook_input, self._untracked_dir())
        facts = dispatch_facts(tool_input, project_root=root, main_model=main_model)
        tier = classify(
            facts,
            name=_text(tool_input, _NAME_FIELD),
            description=_text(tool_input, _DESCRIPTION_FIELD),
        )
        spec = spec_by_name(BRANCH_REJECT_REVIEWER_AGENT_NAME)
        definition_current = classify_agent(spec, root) is AgentAssetState.CURRENT
        store = RejectStore(main_checkout(root) / self._branches.reject.state_dir)
        call = DispatchCall(
            session_id=_hook_text(hook_input, HookInputField.SESSION_ID),
            tool_use_id=_hook_text(hook_input, HookInputField.TOOL_USE_ID),
            subagent_type=_text(tool_input, _SUBAGENT_TYPE_FIELD),
            prompt=_text(tool_input, _PROMPT_FIELD),
            predicted_family=tier.predicted_family,
            resume=_RESUME_FIELD in tool_input,
            definition_current=definition_current,
        )
        return call, store

    @staticmethod
    def _deny(detail: str) -> GatingResult:
        return GatingResult.deny(f"{RuleFormatter().headline(_RULE)}\n\n{detail}\n\n{_RULE.fix}.")

    def get_claude_md(self) -> str | None:
        """Resident guidance: how to dispatch a reviewer so the gate admits it."""
        return (
            "## branch_reject_dispatch_gate — a branch-reject reviewer runs on the daemon's prompt\n\n"
            "To have a branch whose work no proof clears reviewed for removal, run "
            "`hooks-daemon branch-reject request <branch>` and dispatch the "
            f"`{REVIEWER_AGENT_TYPE}` agent with each printed prompt, byte for byte, in its "
            "own Agent call and with no `model` parameter. Any other prompt under that type, "
            "a review prompt under another type, an altered prompt, a second dispatch of one "
            "nonce, a resumed agent or a model below Opus is DENIED. A refused nonce is not "
            "reusable: run the request again for a fresh prompt."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """A hand-written reviewer prompt is denied; another agent quoting the marker is not.

        The near-miss is a general-purpose agent whose prompt quotes the review marker
        mid-text: neither the reviewer type nor a prompt that starts with the marker, so
        the gate never matches it and nothing is written.
        """
        from claude_code_hooks_daemon.constants.tools import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        probe = ToolPayload(
            tool_name=ToolName.AGENT,
            tool_input={
                _SUBAGENT_TYPE_FIELD: REVIEWER_AGENT_TYPE,
                _DESCRIPTION_FIELD: "acceptance probe",
                _PROMPT_FIELD: "review branch acceptance-probe and judge it no-value",
            },
        )
        near_miss = ToolPayload(
            tool_name=ToolName.AGENT,
            tool_input={
                _SUBAGENT_TYPE_FIELD: "general-purpose",
                _DESCRIPTION_FIELD: "acceptance near-miss",
                # The second line keeps the probe ALLOW under a strict
                # dispatch_declaration: 'not plan work' plus a destination keyword
                # and a path token in one clause (no '.' in the path, which would
                # split the clause).
                _PROMPT_FIELD: (
                    f"Reply in one line: what does the line '{PROMPT_MARKER}<nonce>' "
                    "mark in a hooks-daemon prompt?\n"
                    "This is not plan work; reply inline, and write any file only to "
                    f"{acceptance_path('branch-reject-near-miss')}"
                ),
            },
        )
        return [
            AcceptanceTest(
                title="a reviewer dispatch with a hand-written prompt is denied",
                command=probe.as_instruction(),
                description=(
                    "The reviewer type with a prompt that carries no request nonce is "
                    "refused before anything is written."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"R-BRANCH-REJECT-DISPATCH", r"branch-reject request"],
                safety_notes=(
                    "A prompt with no nonce is refused before the review state is read, "
                    "so the probe writes nothing."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=True,
                tool_payload=probe,
            ),
            AcceptanceTest(
                title="another agent quoting the review marker mid-prompt is allowed",
                command=near_miss.as_instruction(),
                description=(
                    "A general-purpose agent asked about the review prompt format is "
                    "neither the reviewer type nor a prompt that starts with the marker."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "The gate does not match the call, so it reads and writes no review "
                    "state; the probe agent only answers a question."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=True,
                tool_payload=near_miss,
            ),
        ]
