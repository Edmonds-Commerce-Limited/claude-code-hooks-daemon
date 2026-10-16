"""WorkflowFanoutAdvisorHandler - name a Workflow script's fan-out and tier (Plan 00472, ruling 2(a)/(c)).

The owner saw a Fable main thread launch a ``Workflow`` of 60 Fable agents. A
script's ``agent()`` calls fire no PreToolUse(``Agent``) and inherit the session
model unless they pass ``model``, so PreToolUse(``Workflow``) is the only point
that sees the fan-out before any agent starts (472-W section 2).

It reads the script WITHOUT running it (:mod:`utils.workflow_fanout`): from
``tool_input.script`` when it is a string, else ``scriptPath`` when it is an
absolute path that exists, with ``tool_input.args`` resolving an ``args``-driven
fan-out when it is an array (or a JSON array string). It says how many agents
the script starts ("at least N" when any site is unknown), how many ``agent()``
sites pass no ``model`` and so inherit the session's family, and whether N is
over that family's lifetime fan-out ``ceilings`` entry. An unknown fan-out
counts as at the ceiling. A script whose sites all pass a model, within the
ceiling, draws nothing; so does an unknown session model.

**Defensive, and its own probe (ruling section 3).** No real ``Workflow``
payload has been captured, so the shape is assumed. On the first ``Workflow``
call of a session it writes the ``tool_input`` key names and value TYPES, never
a value or the script text, to ``<untracked>/payload-capture/workflow-shape.json``.
Any shape it cannot read is allowed with one ``unparsed`` verdict. Every call
records one verdict (``unparsed``, ``no-agents``, ``within-ceiling`` or
``advised``) in the verdict log.

Advisory only: there is no deny mode until a real payload confirms the shape.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, GatingResult, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.utils.deliberate_swallow import log_and_continue
from claude_code_hooks_daemon.utils.dispatch_tier import spawner_model
from claude_code_hooks_daemon.utils.model_tiers import FAMILIES, resolve_model_family
from claude_code_hooks_daemon.utils.spend_ledger import read_state, state_path, write_state
from claude_code_hooks_daemon.utils.workflow_fanout import FanoutReading, analyse_script

logger = logging.getLogger(__name__)

#: Lifetime agents per session family before the advisory says "over" (ruling 2(c)).
DEFAULT_CEILINGS: Final[Mapping[str, int]] = {"fable": 10, "opus": 25, "sonnet": 60, "haiku": 60}

#: A script larger than this is not read: it is allowed as unparsed.
MAX_SCRIPT_BYTES: Final[int] = 1_048_576

SHAPE_SUBDIR: Final[str] = "payload-capture"
SHAPE_FILE: Final[str] = "workflow-shape.json"

VERDICT_UNPARSED: Final[str] = "unparsed"
VERDICT_NO_AGENTS: Final[str] = "no-agents"
VERDICT_WITHIN: Final[str] = "within-ceiling"
VERDICT_ADVISED: Final[str] = "advised"

_SCRIPT: Final[str] = "script"
_SCRIPT_PATH: Final[str] = "scriptPath"
_ARGS: Final[str] = "args"
_STATE_KIND: Final[str] = "workflow-shape"
_STATE_KEY: Final[str] = "probe"
_WRITTEN: Final[str] = "written"
_LOG_SUBDIR: Final[tuple[str, str]] = ("logs", "hooks")


def json_type(value: object) -> str:
    """The JSON type name of ``value``; the probe records this, never the value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _args_len(raw: object) -> int | None:
    """The length of ``args`` when it is an array or a JSON array string, else None."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            log_and_continue(
                logger,
                exc,
                reason="args that are not JSON leave an args-driven fan-out unknown, which counts as at the ceiling",
                level=logging.DEBUG,
            )
    return len(raw) if isinstance(raw, list) else None


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


class WorkflowFanoutAdvisorHandler(PreToolUseHandlerBase):
    """Advise on a Workflow script's agent count, inherited sites and per-family ceiling."""

    _ceilings: Mapping[str, int] | None = DEFAULT_CEILINGS

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.WORKFLOW_FANOUT_ADVISOR,
            priority=Priority.WORKFLOW_FANOUT_ADVISOR,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.ADVISORY, HandlerTag.NON_TERMINAL],
        )
        self._untracked_override: Path | None = None

    @staticmethod
    def validate_options(options: Mapping[str, Any]) -> dict[str, str]:
        """Refuse a malformed option; the handler then runs on its default for it."""
        ceilings = options.get("ceilings")
        if ceilings is not None and not (
            isinstance(ceilings, Mapping)
            and all(
                family in FAMILIES
                and isinstance(limit, int)
                and not isinstance(limit, bool)
                and limit > 0
                for family, limit in ceilings.items()
            )
        ):
            return {"ceilings": f"ceilings maps a family in {FAMILIES} to a positive integer"}
        return {}

    def _untracked_dir(self) -> Path:
        return self._untracked_override or ProjectContext.daemon_untracked_dir()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every ``Workflow`` call."""
        return hook_input.get(HookInputField.TOOL_NAME) == ToolName.WORKFLOW

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Probe the shape once, read the script, advise; always ALLOW."""
        try:
            return self._advise(hook_input)
        except (OSError, RuntimeError) as exc:
            log_and_continue(
                logger,
                exc,
                reason="a Workflow call the advisor cannot judge is allowed with no advice; it never blocks",
                level=logging.WARNING,
            )
            return GatingResult(decision=Decision.ALLOW)

    def _advise(self, hook_input: dict[str, Any]) -> GatingResult:
        untracked = self._untracked_dir()
        session = str(hook_input.get(HookInputField.SESSION_ID) or "")
        tool_input = hook_input.get(HookInputField.TOOL_INPUT)
        self._probe_shape(untracked, session, tool_input)
        fields: dict[str, Any] = tool_input if isinstance(tool_input, dict) else {}
        script = self._script(tool_input)
        if script is None:
            self._verdict(untracked, session, VERDICT_UNPARSED, {"keys": sorted(fields)})
            return GatingResult(decision=Decision.ALLOW)

        reading = analyse_script(script, args_len=_args_len(fields.get(_ARGS)))
        detail: dict[str, Any] = {
            "agents": reading.total,
            "sites": len(reading.sites),
            "sites_without_model": reading.sites_without_model,
            "unknown_sites": reading.unknown_sites,
        }
        if not reading.sites:
            self._verdict(untracked, session, VERDICT_NO_AGENTS, detail)
            return GatingResult(decision=Decision.ALLOW)
        resolved = resolve_model_family(spawner_model(hook_input, untracked))
        family = resolved[0] if resolved is not None else None
        detail["family"] = family
        message = self._message(reading, family) if family is not None else None
        self._verdict(untracked, session, VERDICT_ADVISED if message else VERDICT_WITHIN, detail)
        if message is None:
            return GatingResult(decision=Decision.ALLOW)
        return GatingResult(decision=Decision.ALLOW, context=[message])

    def _message(self, reading: FanoutReading, family: str) -> str | None:
        ceiling = (self._ceilings or {}).get(family)
        over = ceiling is not None and reading.total > ceiling
        at_ceiling = ceiling is not None and reading.has_unknown and not over
        if not (reading.sites_without_model or over or at_ceiling):
            return None
        bound = "at least " if reading.has_unknown else ""
        sites = len(reading.sites)
        lines = [
            f"WORKFLOW FAN-OUT: this script starts {bound}{_plural(reading.total, 'agent')} "
            f"from {_plural(sites, 'agent() site')}; {reading.sites_without_model} of "
            f"{sites} agent() sites pass no `model` and inherit the session's {family}."
        ]
        if over:
            lines.append(f"That is over the {family} fan-out ceiling of {ceiling}.")
        elif at_ceiling:
            lines.append(
                f"{_plural(reading.unknown_sites, 'site')} fan out over a list the script "
                f"decides at run time, counted as at the {family} ceiling of {ceiling}."
            )
        if reading.sites_without_model:
            lines.append("Pass `model: 'sonnet'` (or lower) on fanned-out agent() calls.")
        return " ".join(lines)

    @staticmethod
    def _script(tool_input: object) -> str | None:
        """The script text, or None when the shape gives none this reader can use."""
        if not isinstance(tool_input, dict):
            return None
        script = tool_input.get(_SCRIPT)
        if isinstance(script, str):
            return script if len(script.encode("utf-8")) <= MAX_SCRIPT_BYTES else None
        raw_path = tool_input.get(_SCRIPT_PATH)
        if not isinstance(raw_path, str) or not raw_path:
            return None
        path = Path(raw_path)
        if not path.is_absolute():
            return None
        text: str | None = None
        try:
            if path.stat().st_size <= MAX_SCRIPT_BYTES:
                text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            log_and_continue(
                logger,
                exc,
                reason="an unreadable scriptPath leaves the call unparsed; it is allowed",
                level=logging.DEBUG,
            )
        return text

    def _probe_shape(self, untracked: Path, session: str, tool_input: object) -> None:
        """Write the payload's key names and value types once per session (ruling section 3)."""
        marker = state_path(untracked, session, _STATE_KIND, _STATE_KEY)
        if read_state(marker).get(_WRITTEN) is True:
            return
        keys = (
            {str(key): json_type(value) for key, value in sorted(tool_input.items())}
            if isinstance(tool_input, dict)
            else {}
        )
        shape = {
            "session_id": session,
            "ts": datetime.now(UTC).isoformat(),
            "tool_input_type": json_type(tool_input),
            "keys": keys,
        }
        write_state(untracked / SHAPE_SUBDIR / SHAPE_FILE, shape)
        write_state(marker, {_WRITTEN: True})

    @staticmethod
    def _verdict(untracked: Path, session: str, verdict: str, detail: dict[str, Any]) -> None:
        from claude_code_hooks_daemon.daemon.verdict_log import append_handler_note

        try:
            append_handler_note(
                log_dir=untracked.joinpath(*_LOG_SUBDIR),
                session_id=session,
                event="PreToolUse",
                tool_name=ToolName.WORKFLOW,
                handler=HandlerID.WORKFLOW_FANOUT_ADVISOR.display_name,
                verdict=verdict,
                detail=detail,
            )
        except OSError as exc:
            log_and_continue(
                logger,
                exc,
                reason="a lost verdict line costs one probe reading; the Workflow call proceeds",
                level=logging.WARNING,
            )

    def get_claude_md(self) -> str | None:
        """T2: the advice arrives with the Workflow call and governs the next script."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One case, harness-undrivable: a Workflow call needs the owner's opt-in."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="workflow fan-out advisor - names the fan-out of a Workflow script",
                command="Run a small Workflow whose script fans agent() out over args",
                description=(
                    "The call is allowed with a WORKFLOW FAN-OUT advisory, and the first call "
                    "of the session writes payload-capture/workflow-shape.json. The fixture "
                    "matrix is in tests/unit/handlers/pre_tool_use/test_workflow_fanout_advisor.py."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"WORKFLOW FAN-OUT"],
                safety_notes="Advisory only; a Workflow runs only with the owner's opt-in.",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                harness_cannot_produce=(
                    "A Workflow call runs only when the user has opted into multi-agent "
                    "orchestration, which an unattended acceptance run cannot give."
                ),
            )
        ]
