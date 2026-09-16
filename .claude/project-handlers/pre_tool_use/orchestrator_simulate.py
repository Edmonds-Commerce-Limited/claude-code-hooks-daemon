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

**SIMULATE BY DEFAULT; BLOCKING IS OPT-IN.** :data:`BLOCKING_ENABLED` is
`False`, so out of the box this handler records what the main thread WOULD
have been denied doing and allows every call. Flipping that constant is the
project's explicit, reviewed, one-line choice — there is no config key,
because Plan 00418's ruling is that nothing about this ships to the library
yet, and a library config key would be shipping it.

**What blocking denies, and what it does not.** `Write`, `Edit` and
`NotebookEdit` on the main thread. Never `Bash` — on the real record 93% of
Bash calls run several commands at once and 22% straddle the boundary WITHIN
one invocation (`set+git add+git commit`), so no per-call verdict on a
command head can be right about both halves. That is arithmetic rather than
taste, which is why the handler forecloses it rather than offering it as an
option. The one path exemption is this project's plan tree, whose PLAN.md,
supporting documents and JOURNAL/ its own directory roles make the
coordinator's to write.

**The gate is porous, and that is accepted.** Bash stays open, so a heredoc
writes the file a `Write` denial refused. This is a BEHAVIOURAL gate for
context hygiene, not a security one: its instrument is the command-head
record, which is exactly what would show evasion (`cat`, `tee`, `<other>`
rising after enable). If that happens the boundary is wrong and the record
says so — it does not argue for denying Bash, which the arithmetic rules out.
"""

import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.core import AcceptanceTest, Decision, GatingResult, TestType
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.core.utils import get_bash_command, get_file_path
from claude_code_hooks_daemon.daemon.synthetic_traffic import is_synthetic_event

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


# ── Blocking mode (Plan 00418 Task 2.2a) ───────────────────────────────────
# THE SWITCH. It ships off, and turning it on is a one-line edit to a tracked,
# reviewed file rather than a config key: Plan 00418's Ruling 3 is that
# nothing about orchestrator-only mode reaches the shipped library yet, and a
# library config key IS a library surface — docs, config manifest, the
# config-optimiser's report, and a commitment to keep it correct — even while
# every client leaves it off.
#
# Reversal is the same one-line edit, or the file rename that disables any
# project handler.
BLOCKING_ENABLED: Final[bool] = False

# PUBLIC CONTRACT: this identifier appears in every deny message and is what
# `bin/hooks-daemon explain-rule` resolves. It cannot be renamed later, so it
# names the thing that is actually forbidden (a main-thread write) rather than
# the handler or the plan that introduced it.
ORCHESTRATOR_WRITE_RULE_ID: Final[str] = "R-ORCHESTRATOR-MAIN-THREAD-WRITE"

# The denial surface, and nothing beyond it. Not `Bash` (the arithmetic rules
# it out) and not an unrecognised future tool: simulate flags whatever it does
# not know, because recording a guess costs nothing, but DENYING a guess on a
# gate whose wrong answer stops all work is a different trade entirely.
_BLOCKED_TOOLS: Final[frozenset[str]] = frozenset({"Write", "Edit", "NotebookEdit"})

# The one exempt path, expressed as the directory-role truth it comes from:
# `CLAUDE/Plan/` is this project's plan root, and `CLAUDE/DirectoryRoles.md`
# gives its PLAN.md, supporting documents and JOURNAL/ to the coordinator.
# Matched as an adjacent SEGMENT PAIR rather than a prefix, because every path
# that reaches this gate is absolute and most are inside a worktree — and
# structurally rather than by substring, so `src/Plan/` is not exempted by
# having the word in it.
_PLAN_ROOT_SEGMENTS: Final[tuple[str, str]] = ("CLAUDE", "Plan")

# Where each tool carries its target. `NotebookEdit` is the reason this is not
# just `core.utils.get_file_path`, which handles Write/Edit only.
_PATH_KEYS: Final[tuple[str, ...]] = ("file_path", "notebook_path")


def _target_path(hook_input: dict[str, Any]) -> str | None:
    """The file this call would write, across all three blocked tools."""
    tool_input = hook_input.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for key in _PATH_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def is_plan_tree_path(file_path: str) -> bool:
    """True for a path under this project's plan root.

    Deterministic where any Bash heuristic would not be, which is the reason
    this is the ONLY exemption: it follows from a written directory role
    rather than from a guess about intent.
    """
    parts = Path(file_path).parts
    root, plan = _PLAN_ROOT_SEGMENTS
    return any(
        part == root and index + 1 < len(parts) and parts[index + 1] == plan
        for index, part in enumerate(parts)
    )


def _denial_reason(file_path: str | None) -> str:
    """The block message: terse, identified, and it names the way forward."""
    target = f" ({file_path})" if file_path else ""
    return (
        f"[{ORCHESTRATOR_WRITE_RULE_ID}] ORCHESTRATOR-ONLY MODE: the main "
        f"thread does not write files{target}.\n\n"
        "Dispatch the work to a sub-agent with the `Task` tool and let it do "
        "the writing — that is the whole point of the mode: the lead's "
        "context stays coordination, not implementation.\n\n"
        "Exempt: this project's plan tree (CLAUDE/Plan/), which the "
        "coordinator owns. Sub-agents are never affected. Bash is never "
        "denied by this rule."
    )


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

    def __init__(self, *, blocking: bool | None = None) -> None:
        # The tag set follows the ACTIVE mode, because the generated CLAUDE.md
        # groups handlers by it: a simulating handler advertised as blocking
        # teaches a rule that cannot fire, and a blocking one filed under
        # advisories hides a rule that can.
        mode_tag = (
            "blocking" if (BLOCKING_ENABLED if blocking is None else blocking) else "advisory"
        )
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
            # NOT terminal even when blocking. A terminal handler ends the
            # chain, and this one ALLOWS the overwhelming majority of what it
            # matches (every Bash call) — ending the chain there would silence
            # every guard registered behind it. A non-terminal DENY still
            # denies: the chain aggregates most-restrictive-wins.
            terminal=False,
            tags=["project", "workflow", mode_tag, "simulate"],
        )
        # Resolved once, in the constructor, so a test can construct a
        # blocking instance without mutating module state that another test
        # then inherits.
        self._blocking: bool = BLOCKING_ENABLED if blocking is None else blocking

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

    def _would_deny(self, hook_input: dict[str, Any]) -> bool:
        """True when blocking mode should refuse THIS call.

        Every condition is a narrowing, and each one is load-bearing:

        - the switch is on at all;
        - the tool is one of the three that mutate a file;
        - no ``agent_id``, so this is the main thread. ``matches()`` checks
          this too; repeating it here is defence in depth on the single
          misreading that killed the original handler;
        - the event was not fabricated by a test harness. The acceptance
          playbook builds events with no ``agent_id``, so without this the
          suite would go red — with hundreds of denied probes AND, under
          most-restrictive-wins, other handlers' expected ALLOWs turned into
          failures — on the day blocking was first enabled;
        - the target is not in the plan tree the coordinator owns.
        """
        if not self._blocking:
            return False
        if hook_input.get("tool_name") not in _BLOCKED_TOOLS:
            return False
        if hook_input.get("agent_id"):
            return False
        if is_synthetic_event(hook_input):
            return False
        file_path = _target_path(hook_input)
        return not (file_path and is_plan_tree_path(file_path))

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Record what orchestrator-only mode would deny; deny it only if armed.

        `rule` carries the Bash classification (Task 2.1) so `verdicts.jsonl`
        records WHICH command, not just "Bash" — 63% of Phase 1's record was
        Bash and could not be classified from it. Set for Bash only:
        `Write`/`Edit` need no sub-classification, because the tool name
        already is one. On a denial it carries the rule ID instead, which is
        the same field `pipe_blocker` uses to sub-classify its own blocks.
        """
        if self._would_deny(hook_input):
            return GatingResult(
                decision=Decision.DENY,
                rule=ORCHESTRATOR_WRITE_RULE_ID,
                reason=_denial_reason(_target_path(hook_input)),
            )

        command = get_bash_command(hook_input)
        mode = "blocking" if self._blocking else "record only, never blocks"
        return GatingResult(
            decision=Decision.ALLOW,
            rule=classify_bash_command(command) if command is not None else None,
            context=[
                f"SIMULATED orchestrator-only mode (Plan 00418 — {mode}): "
                "main thread would have been denied — "
                f"{_call_detail(hook_input)}",
            ],
        )

    def get_rules(self) -> list[Rule]:
        """The rule this handler can actually enforce — none, while simulating.

        A rule row in the generated CLAUDE.md is a promise that the rule can
        fire, and `explain-rule` resolving an ID is the same promise. Neither
        is true in the default mode, so neither is made.
        """
        if not self._blocking:
            return []
        return [
            Rule(
                rule_id=ORCHESTRATOR_WRITE_RULE_ID,
                blocked="`Write`/`Edit`/`NotebookEdit` from the MAIN THREAD",
                why=(
                    "Implementation work belongs in a sub-agent; 73% of this "
                    "repository's main-thread edits were implementation, which "
                    "is context the lead should never have spent"
                ),
                fix="Dispatch the work with the `Task` tool and let the sub-agent write",
                verbose=_denial_reason(None),
            )
        ]

    def get_claude_md(self) -> str | None:
        """Describe the mode that is actually ACTIVE, never both.

        Agent-facing guidance that hedges between two modes teaches neither;
        the reader has to know whether a write will be refused.
        """
        if self._blocking:
            return (
                "## orchestrator-simulate — orchestrator-only mode, BLOCKING (Plan 00418)\n\n"
                "**The main thread does not write files.** `Write`, `Edit` and "
                "`NotebookEdit` are DENIED "
                f"(`{ORCHESTRATOR_WRITE_RULE_ID}`) — dispatch the work to a "
                "sub-agent with the `Task` tool and let it do the writing.\n\n"
                "**Never denied**: `Bash` (93% of real calls run several "
                "commands at once, so no per-call verdict on a command head "
                "can be right about both halves), anything a SUB-AGENT does "
                "(`agent_id` present), and this project's plan tree "
                "(`CLAUDE/Plan/`), which the coordinator owns.\n\n"
                "**Consequence worth internalising**: because Bash is open, a "
                "heredoc writes the file the `Write` denial refused. That is "
                "not a loophole to use — it is the evasion the command-head "
                "record exists to make visible, and using it defeats the "
                "context hygiene the mode is for.\n\n"
                "**Review the record**: `bin/hooks-daemon verdicts` (harness "
                "traffic is excluded by default)."
            )
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
