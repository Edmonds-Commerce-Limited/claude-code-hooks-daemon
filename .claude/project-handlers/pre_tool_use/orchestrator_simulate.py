"""Orchestrator-only mode — SIMULATE ONLY (Plan 00418, Phase 1, from issue #14).

Restricts the MAIN THREAD to coordination-only tools, so heavy work is
delegated to sub-agents and the lead agent's context stays clean. This was
built once (`0da21754`) and deliberately deleted (`b91f0012`, "dead code,
superseded by upstream delegate mode"): `PreToolUse` gave no way to tell WHICH
agent fired a call, so enabling it blocked every agent equally and made agent
teams unusable.

That distinction now exists. `agent_id` is delivered to `PreToolUse` only
INSIDE a subagent call — Task 1.1 confirmed this empirically against the live
daemon before this file was written (captured payloads in the plan's subagent
report), rather than trusting the vendored contract alone, which is what cost
the original attempt (Ledger 00413 N12: a CONDITIONAL field invisible in an
`input_example` read as "never present").

**Greenfield, by owner ruling** — not a revival of the archived
`CLAUDE/Plan/Cancelled/00032-.../archived-code/orchestrator_only.py`, which
predates `agent_id` and could not have made this distinction. Read for prior
art; not copied.

**SIMULATE ONLY.** `handle()` has exactly one `return`, and it is always
`Decision.ALLOW`. There is no blocking code path in this module at all, so
none can be reached by a future edit that forgets to check a flag — the
absence is structural, not configured. Every fire is what the main thread
WOULD have been denied doing; Phase 2 reviews that record (via
`bin/hooks-daemon verdicts`, filtered to this handler) to settle the
coordination-tool boundary and decide whether to promote to blocking.

**The Bash boundary is deliberately unresolved here.** The owner named
read-only Bash inspection as the awkward middle: most of what a coordinator
actually does. This handler does NOT special-case it — every Bash call is
flagged, unconditionally — because pre-filtering by a guessed "looks
read-only" prefix list would throw away exactly the data Phase 2 needs to
answer that question from evidence instead of taste.
"""

import re
from typing import Any, Final

from claude_code_hooks_daemon.core import AcceptanceTest, Decision, GatingResult, TestType
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_bash_command, get_file_path

# Task/Agent (subagent dispatch), TodoWrite, Read and the search/web tools are
# obviously coordination — the owner's own framing in PLAN.md. SendMessage is
# how an agent-team teammate coordinates with the rest of the team, which is
# the same category. Edit/Write/Bash/NotebookEdit are obviously not, and
# anything this set does not name is treated as not-coordination too, so a
# future tool the daemon does not yet recognise is flagged rather than
# silently exempted.
_COORDINATION_TOOLS: frozenset[str] = frozenset(
    {
        "Task",
        "Agent",
        "TodoWrite",
        "Read",
        "Glob",
        "Grep",
        "WebSearch",
        "WebFetch",
        "AskUserQuestion",
        "EnterPlanMode",
        "ExitPlanMode",
        "Skill",
        "SendMessage",
    }
)


# ── Bash classification (Plan 00418 Task 2.1) ──────────────────────────────
# Phase 1 gathered 640 would-be denials and the boundary stayed unsettled:
# 63% were Bash, and `verdicts.jsonl` stores `tool` without the command, so
# `git status` and a QA run are the same record. This labels the call with its
# command HEADS and nothing else, carried on `HookResult.rule` — the field
# that already exists for a handler-set sub-classification (pipe_blocker's
# "blacklisted" vs "unknown"), so no new log and no new file.
#
# Heads only, deliberately. It is the privacy floor (a label is written to a
# log, so it must never become a channel for arguments, paths, tokens or
# hostnames) AND the right granularity: `git status` versus `git commit` is
# the distinction the boundary decision turns on, and the rest of the command
# line cannot inform it.

# Segment separators. A deliberately naive split: this produces a LABEL, not a
# parse, and anything it mishandles falls through to `_OTHER` rather than
# being echoed.
_SEGMENT_SPLIT: Final[re.Pattern[str]] = re.compile(r"&&|\|\||[;|]")
# A plain command name — anything else is not emitted at all.
_PLAIN_NAME: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._-]+$")
# A bare subcommand word (`status`, `commit`, `pr`), never a flag or a value.
_BARE_WORD: Final[re.Pattern[str]] = re.compile(r"^[a-z][a-z0-9_-]*$")
# `NAME=value` prefixes, which precede the real command head.
_ENV_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# Tools whose FIRST ARGUMENT carries the meaning. `git` alone says nothing
# about which side of the boundary a call sits on; `git status` says it all.
_SUBCOMMAND_TOOLS: Final[frozenset[str]] = frozenset(
    {"git", "gh", "npm", "npx", "uv", "pip", "pip3", "docker", "podman", "cargo", "go", "apt"}
)
# `cd <somewhere> && <the real command>` is the dominant shape in this repo;
# labelling the whole thing "cd" would erase the record it exists to build.
_TRANSPARENT_HEADS: Final[frozenset[str]] = frozenset({"cd", "pushd", "popd"})
_LABEL_SEPARATOR: Final[str] = "+"
_MAX_LABELS: Final[int] = 3
_TRUNCATION_MARKER: Final[str] = "…"
_OTHER: Final[str] = "<other>"
_NONE: Final[str] = "<none>"


def _segment_label(segment: str) -> str | None:
    """The command head(s) of one segment, or None when there is nothing to say."""
    tokens = segment.split()
    while tokens and _ENV_ASSIGNMENT.match(tokens[0]):
        tokens.pop(0)
    if not tokens:
        return None

    head = tokens[0].rsplit("/", 1)[-1]
    if head in _TRANSPARENT_HEADS:
        return None
    if not _PLAIN_NAME.match(head):
        # Substitutions, quoting, redirects — not a name, so say so rather
        # than emit the text.
        return _OTHER
    if head in _SUBCOMMAND_TOOLS and len(tokens) > 1 and _BARE_WORD.match(tokens[1]):
        return f"{head} {tokens[1]}"
    return head


def classify_bash_command(command: str) -> str:
    """A low-cardinality label naming what a Bash call RUNS, never its arguments.

    Deduped in first-seen order and capped at :data:`_MAX_LABELS`, because the
    label is aggregated: an uncapped compound command would mint a unique
    bucket per invocation and the tally would count nothing.
    """
    labels: list[str] = []
    for segment in _SEGMENT_SPLIT.split(command):
        label = _segment_label(segment)
        if label is not None and label not in labels:
            labels.append(label)
    if not labels:
        return _NONE
    if len(labels) > _MAX_LABELS:
        return _LABEL_SEPARATOR.join([*labels[:_MAX_LABELS], _TRUNCATION_MARKER])
    return _LABEL_SEPARATOR.join(labels)


def _call_detail(hook_input: dict[str, Any]) -> str:
    """A short human-readable description of what this call would have done."""
    tool_name = hook_input.get("tool_name", "Unknown")
    command = get_bash_command(hook_input)
    if command:
        return f"Bash: {command}"
    file_path = get_file_path(hook_input)
    if file_path:
        return f"{tool_name}: {file_path}"
    return f"{tool_name}"


class OrchestratorSimulateHandler(PreToolUseHandlerBase):
    """Record what orchestrator-only mode WOULD deny on the main thread; deny nothing."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="orchestrator-simulate",
            # 8, 24, 41 and 51 are already taken by this repo's other project
            # handlers (release_blocker, daemon_restart_verifier,
            # enforce_llm_qa, plan_done_requires_holding_area), and 55 is
            # taken by a built-in (validate-websearch-year); verified against
            # the live router by
            # tests/integration/test_project_handler_priority_collisions.py
            # rather than assumed.
            priority=56,
            terminal=False,  # Advisory — records and allows, never blocks.
            tags=["project", "workflow", "advisory", "simulate"],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for a main-thread call to a non-coordination tool.

        `agent_id` present means this fired inside a subagent call — exempt
        unconditionally, regardless of tool. This is the check the original
        handler could not make.
        """
        if hook_input.get("agent_id"):
            return False
        tool_name = hook_input.get("tool_name")
        if not tool_name:
            return False
        return tool_name not in _COORDINATION_TOOLS

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Always ALLOW. Records what would have been denied, as context only.

        `rule` carries the Bash classification (Task 2.1) so `verdicts.jsonl`
        records WHICH command, not just "Bash" — 63% of Phase 1's record was
        Bash and could not be classified from it. Set for Bash only:
        `Write`/`Edit` need no sub-classification, because the tool name
        already is one.
        """
        command = get_bash_command(hook_input)
        return GatingResult(
            decision=Decision.ALLOW,
            rule=classify_bash_command(command) if command is not None else None,
            context=[
                "SIMULATED orchestrator-only mode (Plan 00418, Phase 1 — "
                "record only, never blocks): main thread would have been "
                f"denied — {_call_detail(hook_input)}",
            ],
        )

    def get_claude_md(self) -> str | None:
        return (
            "## orchestrator-simulate — orchestrator-only mode, SIMULATE ONLY (Plan 00418)\n\n"
            "Records what a main-thread orchestrator-only policy WOULD have "
            "denied. Never blocks — every call is allowed regardless of what "
            "this handler matches. A subagent call (`agent_id` present) is "
            "always exempt.\n\n"
            "**Why**: gathering evidence for where the coordination-tool "
            "boundary should sit, before any blocking decision is made.\n\n"
            "**Review the record**: `bin/hooks-daemon verdicts`, filtered to "
            "the `orchestrator-simulate` handler."
        )

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [
            AcceptanceTest(
                title="Main-thread Bash call is flagged, never denied",
                command='echo "rm -rf /tmp/scratch"',
                description=(
                    "Simulated orchestrator-only mode records a would-be "
                    "denial for a non-coordination tool on the main thread, "
                    "and still allows it"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"SIMULATED", r"Bash"],
                safety_notes="Uses echo - safe to execute. Handler only ever allows.",
                test_type=TestType.ADVISORY,
                requires_event="PreToolUse for a main-thread (no agent_id) Bash call",
            ),
        ]
