"""PlanDoneRequiresHoldingAreaHandler — a plan cannot flip to Complete until
its Success Criteria say where its release-bound consequences went.

PROJECT-ONLY. This enforces step 0 of the Plan Completion Checklist in
`CLAUDE/core/PlanWorkflow.core.md` for THIS repository's plan tree and its
`CLAUDE/UPGRADES/UNRELEASED/` holding area. It is deliberately not a daemon
handler: the holding-area layout is this project's, and a client project
names its own.

Judged on the content the file WOULD have after the Write/Edit, in the
active plan root only — an archived plan is history, and correcting one is
not a status flip.
"""

import re
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult, TestType
from claude_code_hooks_daemon.core.acceptance_test import ToolPayload
from claude_code_hooks_daemon.core.hook_result import Decision

_PLAN_FILENAME = "PLAN.md"
_STATUS_RE = re.compile(r"^\*\*Status\*\*:\s*(?P<status>[^\n(]+)", re.MULTILINE)
_CRITERIA_HEADING = "## Success Criteria"
_NEXT_HEADING_RE = re.compile(r"^## ", re.MULTILINE)
# Either spelling the template offers: an artefact in the holding area, or
# an explicit statement that there is nothing to put there.
_CRITERION_RE = re.compile(r"holding area|release-bound consequence", re.IGNORECASE)
_TERMINAL_SHIPPED = ("complete",)


def _active_plan_path(file_path: str) -> bool:
    """True for ``CLAUDE/Plan/<folder>/PLAN.md`` directly under the active root."""
    parts = Path(file_path).parts
    try:
        idx = parts.index("Plan")
    except ValueError:
        return False
    if idx == 0 or parts[idx - 1] != "CLAUDE":
        return False
    remainder = parts[idx + 1 :]
    return len(remainder) == 2 and remainder[1] == _PLAN_FILENAME


def _prospective_content(tool_name: str, tool_input: dict[str, Any]) -> str | None:
    if tool_name == "Write":
        content = tool_input.get("content")
        return content if isinstance(content, str) else None
    old = tool_input.get("old_string")
    new = tool_input.get("new_string")
    path = tool_input.get("file_path")
    if not (isinstance(old, str) and isinstance(new, str) and isinstance(path, str)):
        return None
    try:
        current = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # The Edit tool refuses an unreadable target itself; nothing to judge.
        # Registered in error_hiding_exclusions.json.
        return None
    if tool_input.get("replace_all"):
        return current.replace(old, new)
    return current.replace(old, new, 1)


def _status(content: str) -> str:
    match = _STATUS_RE.search(content)
    return match.group("status").strip().lower() if match else ""


def _criteria_section(content: str) -> str:
    start = content.find(_CRITERIA_HEADING)
    if start < 0:
        return ""
    body_start = start + len(_CRITERIA_HEADING)
    nxt = _NEXT_HEADING_RE.search(content, body_start)
    return content[body_start : nxt.start() if nxt else len(content)]


class PlanDoneRequiresHoldingAreaHandler(Handler):
    """Deny a Complete flip whose Success Criteria never mention the holding area."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="plan-done-requires-holding-area",
            priority=20,
            terminal=True,
            tags=["project", "blocking", "plan"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        tool_name = hook_input.get("tool_name")
        if tool_name not in ("Write", "Edit"):
            return False
        tool_input = hook_input.get("tool_input")
        if not isinstance(tool_input, dict):
            return False
        file_path = tool_input.get("file_path")
        if not isinstance(file_path, str) or not _active_plan_path(file_path):
            return False
        content = _prospective_content(tool_name, tool_input)
        if content is None or _status(content) not in _TERMINAL_SHIPPED:
            return False
        return _CRITERION_RE.search(_criteria_section(content)) is None

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(
            decision=Decision.DENY,
            reason=(
                "PLAN NOT DONE: the holding area criterion is missing\n\n"
                "A plan is done when its work is merged into main AND its\n"
                "release-bound consequences are in the pending-release holding\n"
                "area (CLAUDE/UPGRADES/UNRELEASED/). This is step 0 of the Plan\n"
                "Completion Checklist (CLAUDE/core/PlanWorkflow.core.md).\n\n"
                "Before flipping to Complete, add ONE of these to Success Criteria:\n"
                "  - [x] Every release-bound consequence is in the pending-release\n"
                "        holding area: `UNRELEASED/<dir>/<file>.md`\n"
                "  - [x] This plan has no release-bound consequences: <why>\n\n"
                "Shapes: release-notes/ (a callout), post-upgrade-tasks/ (an action),\n"
                "config-changes/, truth-changes/. Write the artefact first, then cite it."
            ),
        )

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        # Both probes name a folder number no real plan uses. The denied Write
        # never lands; the allowed Edit is a status flip on a file that does
        # not exist, which this handler passes (nothing to judge) and the Edit
        # tool itself then refuses — so nothing lands there either.
        probe_content = (
            "# Plan 00000: probe\n\n**Status**: Complete\n\n"
            "## Success Criteria\n\n- [x] All QA checks passing\n"
        )
        probe_payload = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                # $CLAUDE_PROJECT_DIR-rooted, not `untracked/scratch/`: this
                # handler judges the path structurally (a "CLAUDE"/"Plan"
                # segment pair), so a scratch-relocated probe would exercise
                # nothing (Plan 00319 Task 4.6 -- see the matching entry in
                # test_acceptance_tool_payload_agrees_with_prose.py's
                # _OUTSIDE_SCRATCH_BY_CONTRACT).
                "file_path": "$CLAUDE_PROJECT_DIR/CLAUDE/Plan/00000-acceptance-probe/PLAN.md",
                "content": probe_content,
            },
        )
        return [
            AcceptanceTest(
                title="Deny a Complete flip with no holding-area criterion",
                command=probe_payload.as_instruction(),
                description=(
                    "A plan flipping to Complete whose Success Criteria never say "
                    "where its release-bound consequences went is not done."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"holding area", r"UNRELEASED"],
                safety_notes="Denied before anything is written.",
                test_type=TestType.BLOCKING,
                tool_payload=probe_payload,
            ),
            AcceptanceTest(
                title="Allow a status flip the handler has no content to judge",
                command=(
                    "Edit CLAUDE/Plan/00000-acceptance-probe/PLAN.md replacing "
                    "'**Status**: In Progress' with '**Status**: Complete'"
                ),
                description=(
                    "A near miss: the same Complete flip, but on a file that does "
                    "not exist. The handler fails open (the Edit tool refuses an "
                    "unreadable target itself), so the gate must not fire."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="The Edit tool rejects the missing file; nothing is written.",
                test_type=TestType.ADVISORY,
            ),
        ]
