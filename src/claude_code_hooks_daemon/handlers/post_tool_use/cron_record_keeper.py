"""CronRecordKeeperHandler - record when each session cron was created (Plan 00470 Task 2.1).

A recurring cron auto-expires 7 days after creation, and the ``session_crons``
list a Stop carries has no creation time. In an always-on session where every
job is created in the same reconcile, that is a silent total death: nothing is
left to produce the Stop that would notice. ``cron_stop_enforcer`` refreshes a
job before it dies, and it can only do that if something wrote down when the
job was born. This handler is that something: every ``CronCreate`` is recorded
and every ``CronDelete`` forgotten in ``utils.cron_records``.

Silent bookkeeping: it never blocks, never speaks, and fails open. It stays
active while a session is usage-paused, because the pause's resume cron is a
``CronCreate`` too and the record must not go stale for a state change it can
see.

**The ``CronCreate`` result's shape is not contract-documented**, so the id is
read from the shapes it plausibly takes (a mapping with an id key, or text
carrying ``id: <token>``). A result with none is not recorded rather than
recorded under an invented id: the enforcer stamps an unrecorded job at its
next Stop, which costs only the lost creation time.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.utils.cron_records import (
    CronRecord,
    default_records_path,
    forget_cron,
    prompt_fingerprint,
    record_cron,
)

logger = logging.getLogger(__name__)

_CRON_TOOLS: Final[frozenset[str]] = frozenset({ToolName.CRON_CREATE, ToolName.CRON_DELETE})

#: Mapping keys a tool result or input may carry its cron id under.
_ID_KEYS: Final[tuple[str, ...]] = (
    "id",
    "cron_id",
    "cronId",
    "job_id",
    "jobId",
    "task_id",
    "taskId",
)

#: ``id: abc-123`` / ``id=abc-123`` inside a textual result.
_TEXT_ID_RE: Final[re.Pattern[str]] = re.compile(r"\bid\s*[:=]\s*([A-Za-z0-9_-]+)", re.IGNORECASE)

_SCHEDULE_KEYS: Final[tuple[str, ...]] = ("cron", "schedule")


def _id_from_mapping(mapping: dict[str, Any]) -> str | None:
    for key in _ID_KEYS:
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _cron_id_from_result(response: object) -> str | None:
    """The id ``CronCreate`` reported, from whichever shape the result takes."""
    if isinstance(response, dict):
        return _id_from_mapping(response)
    if isinstance(response, str):
        match = _TEXT_ID_RE.search(response)
        return match.group(1) if match else None
    return None


class CronRecordKeeperHandler(PostToolUseHandlerBase):
    """Record every CronCreate and forget every CronDelete, silently."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.CRON_RECORD_KEEPER,
            priority=Priority.CRON_RECORD_KEEPER,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def _records_path(self) -> Path | None:
        """Where the records live; None without a project context."""
        return default_records_path()

    def _now(self) -> float:
        return time.time()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for a CronCreate or CronDelete result."""
        return hook_input.get(HookInputField.TOOL_NAME) in _CRON_TOOLS

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Record or forget the cron; always ALLOW and silent."""
        path = self._records_path()
        session_id = str(hook_input.get(HookInputField.SESSION_ID) or "")
        if path is not None and session_id:
            if hook_input.get(HookInputField.TOOL_NAME) == ToolName.CRON_CREATE:
                self._record_create(path, session_id, hook_input)
            else:
                self._record_delete(path, session_id, hook_input)
        return BlockingResult(decision=Decision.ALLOW)

    def _tool_input(self, hook_input: dict[str, Any]) -> dict[str, Any]:
        raw = hook_input.get(HookInputField.TOOL_INPUT)
        return raw if isinstance(raw, dict) else {}

    def _record_create(self, path: Path, session_id: str, hook_input: dict[str, Any]) -> None:
        tool_input = self._tool_input(hook_input)
        if tool_input.get("recurring") is False:
            return
        schedule = next(
            (v for k in _SCHEDULE_KEYS if isinstance(v := tool_input.get(k), str) and v), None
        )
        prompt = tool_input.get("prompt")
        cron_id = _cron_id_from_result(hook_input.get(HookInputField.TOOL_RESPONSE))
        if schedule is None or not isinstance(prompt, str) or not prompt:
            logger.debug("cron_record_keeper: CronCreate without a schedule and prompt")
            return
        if cron_id is None:
            logger.debug("cron_record_keeper: no readable cron id in the CronCreate result")
            return
        record_cron(
            path,
            CronRecord(
                session_id=session_id,
                cron_id=cron_id,
                schedule=schedule,
                prompt_hash=prompt_fingerprint(prompt),
                created_at=self._now(),
            ),
            now=self._now(),
        )

    def _record_delete(self, path: Path, session_id: str, hook_input: dict[str, Any]) -> None:
        cron_id = _id_from_mapping(self._tool_input(hook_input))
        if cron_id is None:
            logger.debug("cron_record_keeper: CronDelete without an id")
            return
        forget_cron(path, session_id=session_id, cron_id=cron_id, now=self._now())

    def get_claude_md(self) -> str | None:
        """No resident guidance: silent, and what an agent must do is in the enforcer's.

        ``cron_stop_enforcer``'s guidance and deny reason already carry the one
        instruction that follows from these records (refresh through
        ``CronDelete`` + ``CronCreate``).
        """
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """One case: an ordinary tool call is untouched (the effect is a file)."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="cron record keeper - an unrelated tool result is left alone",
                command="Run any Bash command and verify no cron record is written.",
                harness_cannot_produce=(
                    "The assertion is a file under the daemon's untracked directory, not "
                    "the hook's answer, and the harness compares decisions and message "
                    "patterns only. Covered by "
                    "tests/unit/handlers/post_tool_use/test_cron_record_keeper.py."
                ),
                description=(
                    "The keeper matches only CronCreate and CronDelete results, so "
                    "ordinary tool calls neither write a record nor produce context."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Observe-only: writes nothing for a tool that is not a cron tool.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
