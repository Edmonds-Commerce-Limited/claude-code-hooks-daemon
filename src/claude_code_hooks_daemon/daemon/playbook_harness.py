"""Turn a playbook block into a dispatchable probe (Plan 00243 Phase 2).

`playbook_generator` renders the acceptance tests; this module decides what a
harness can actually DO with each rendered block. The two live side by side
because they are two halves of one contract: what the generator declares in
`tool_payload`, this consumes.

**Everything here is pure.** No dispatch, no subprocess, no filesystem. The
harness that owns those lives in `tests/acceptance/` and needs a running
daemon; the judgement calls do not, and they are the part that decides whether
the harness is trustworthy. Plan 00243 Task 1.2 measured an ad-hoc checker that
reported 29 failures, all 29 of them artefacts of the checker rather than
defects in what it checked. Each of those artefacts is a named rule below.

**A probe is inert.** A command payload is DATA: it is placed in `tool_input`
and handed to the daemon, which answers what it would decide. No shell ever
runs it. That is what makes it safe to probe a destructive command at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: One rendered playbook entry, as `generate_json` emits it. Named rather than
#: spelled `dict[str, Any]` at each use: it is the input format this whole
#: module is written against, and a reader should be able to see that.
PlaybookBlock = dict[str, Any]

#: The events a tool payload can drive. A payload describes a TOOL CALL, so an
#: event that carries no tool call cannot be dispatched from one however
#: complete the block is -- `SessionStart` has no `tool_name` to populate.
DISPATCHABLE_EVENTS = frozenset({"PreToolUse", "PostToolUse"})

#: Written unexpanded into the playbook so it stays portable across installs
#: (`scratch_path`, `project_dir_path`); a client's root is not this one's.
_PROJECT_DIR_PATTERN = re.compile(r"\$\{CLAUDE_PROJECT_DIR\}|\$CLAUDE_PROJECT_DIR")

_FILE_PATH_KEY = "file_path"

#: One `Decision.DENY`, two wire spellings. The daemon's own
#: `REFUSAL_CAPABLE_EVENTS` table records both against the same enum member:
#: `PreToolUse # permissionDecision: deny` beside `PostToolUse # decision:
#: block`. A harness that knows only the first reports every PostToolUse deny
#: probe as a failure — 7 of this harness's own first-run mismatches.
_REFUSAL_SPELLINGS = frozenset({"deny", "block"})


@dataclass(frozen=True)
class ExecutableProbe:
    """One playbook block, resolved into something a harness can dispatch."""

    test_number: int
    handler_name: str
    title: str
    event_type: str
    tool_name: str
    tool_input: dict[str, Any]
    expected_decision: str
    #: The checkout this probe was planned against, and the directory its
    #: event reports as the session's. Carried here rather than passed to
    #: `build_event` so no caller can point a probe at a directory that is not
    #: the project -- see that function for what the temp-dir caller broke.
    project_root: Path = Path()
    expected_message_patterns: list[str] = field(default_factory=list)
    requires_existing_file: bool = False
    requires_absent_file: bool = False
    #: Already translated and contained by `vet_probe_commands`, so a probe
    #: carrying any command the harness will not run is a SkippedProbe instead.
    #: The dispatcher performs these as plain filesystem operations -- there is
    #: no shell anywhere in this path.
    setup_actions: list[FixtureAction] = field(default_factory=list)
    cleanup_actions: list[FixtureAction] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tool_name or not self.tool_name.strip():
            raise ValueError("tool_name must be a non-empty string")

    @property
    def file_path(self) -> str | None:
        """The path this probe writes to, if it declares one."""
        value = self.tool_input.get(_FILE_PATH_KEY)
        return value if isinstance(value, str) and value else None


#: The ONLY command shapes the harness will execute, and the reason the list is
#: closed rather than a path check. Measured across all 79 blocks that carry
#: setup: 77 are `mkdir -p`, and the remaining handful author a small fixture
#: file. Nothing else appears, so nothing else is permitted -- refusing an
#: unrecognised shape costs one skipped probe and says so in the report, while
#: running an unreviewed one because its path looked acceptable is unbounded.
#:
#: Anchored end to end, so a shape cannot be reached by appending to a
#: permitted one: `mkdir -p <scratch> && rm -rf /` matches none of these.
_PERMITTED_PROBE_COMMANDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^mkdir -p (?P<path>[^\s;&|<>]+)$"), "mkdir"),
    (re.compile(r"^install -d (?P<path>[^\s;&|<>]+)$"), "mkdir"),
    (re.compile(r"^rm -[rf]{1,2} (?P<path>[^\s;&|<>]+)$"), "remove"),
    (re.compile(r"^printf '(?P<printf>[^']*)' > (?P<path>[^\s;&|<>]+)$"), "write"),
    (
        re.compile(r"""^echo (?:'(?P<echo>[^']*)'|"(?P<echo2>[^"]*)") > (?P<path>[^\s;&|<>]+)$"""),
        "write",
    ),
)

#: Where a probe is allowed to act, relative to the checkout. The same rule the
#: harness applies to its own deletes.
_PROBE_SCRATCH = ("untracked", "scratch")


@dataclass(frozen=True)
class RefusedCommands:
    """A probe whose fixture commands the harness declines to run, and why.

    Returned rather than raised: a refusal turns into a SKIP with a reason,
    which is this harness's whole contract for anything it will not do. Raising
    would abort a run of ~190 probes over one unrecognised fixture command.
    """

    reason: str

    def __post_init__(self) -> None:
        if not self.reason or not self.reason.strip():
            raise ValueError("a refusal must carry a reason")


@dataclass(frozen=True)
class FixtureAction:
    """One filesystem effect a probe's setup or cleanup asks for.

    A probe's fixture commands are TRANSLATED into these rather than handed to
    a shell. That is the whole reason the permitted list is closed: each shape
    corresponds to a plain filesystem operation, so the harness needs no shell
    at all and there is no command-injection surface to reason about. A shape
    nobody has translated is a shape nobody runs.
    """

    kind: str
    path: Path
    content: str = ""


def vet_probe_commands(
    commands: list[str] | None, project_root: Path
) -> RefusedCommands | list[FixtureAction]:
    """Translate a probe's fixture commands, or refuse them.

    Fixture commands are the one part of this harness that is NOT inert.
    Everywhere else a command is data placed in `tool_input` and answered by
    the daemon; these describe real changes to the tree. So each is checked
    twice -- the shape must be on the closed list above, and the path it acts
    on must resolve inside the checkout's scratch directory -- and then
    converted to a `FixtureAction` the caller performs directly.

    Resolved, not string-matched: `untracked/scratch/../../etc` starts with the
    sanctioned prefix and is not inside it.
    """
    actions: list[FixtureAction] = []
    for command in commands or []:
        stripped = command.strip()
        for pattern, kind in _PERMITTED_PROBE_COMMANDS:
            match = pattern.match(stripped)
            if match is None:
                continue
            target = expand_project_dir(match.group("path"), project_root)
            resolved = Path(target)
            if not resolved.is_absolute():
                resolved = project_root / resolved
            scratch = project_root.joinpath(*_PROBE_SCRATCH)
            try:
                inside = resolved.resolve().is_relative_to(scratch.resolve())
            except OSError as exc:
                # A path the filesystem cannot resolve is its own refusal, not a
                # quiet vote for "outside": the two have different remedies, and
                # a skip that says which one applies is the point of the reason.
                return RefusedCommands(
                    reason=f"fixture command path could not be resolved: {command!r} ({exc})"
                )
            if not inside:
                return RefusedCommands(
                    reason=f"fixture command acts outside {'/'.join(_PROBE_SCRATCH)}: {command!r}"
                )
            actions.append(
                FixtureAction(
                    kind=kind,
                    path=resolved,
                    content=_fixture_content(match),
                )
            )
            break
        else:
            return RefusedCommands(
                reason=f"fixture command is not one the harness will run: {command!r}"
            )
    return actions


def _fixture_content(match: re.Match[str]) -> str:
    """The bytes a writing shape puts on disk, with shell escapes resolved.

    `printf 'def broken(\\n'` writes a real newline; `echo` does not interpret
    the escape. Getting this backwards would author a fixture whose content is
    not what the playbook shows, which is the same class of defect as a payload
    disagreeing with its prose.
    """
    groups = match.groupdict()
    if groups.get("printf") is not None:
        return groups["printf"].replace("\\n", "\n").replace("\\t", "\t")
    literal = groups.get("echo") if groups.get("echo") is not None else groups.get("echo2")
    return f"{literal}\n" if literal is not None else ""


@dataclass(frozen=True)
class SkippedProbe:
    """A block the harness deliberately does not run, and why.

    The reason is mandatory. Plan 00241 Phase 2 discarded a 23-handler guard
    because it reported failures that were not real, and a skip with no reason
    is the same defect one step earlier: indistinguishable from a test that was
    silently never covered.
    """

    test_number: int
    handler_name: str
    title: str
    reason: str

    def __post_init__(self) -> None:
        if not self.reason or not self.reason.strip():
            raise ValueError("a skipped probe must carry a reason")


def expand_project_dir(value: str, project_root: Path) -> str:
    """Resolve `$CLAUDE_PROJECT_DIR` against this checkout.

    Substring replacement rather than a prefix strip: the variable appears
    mid-string in Bash payloads, not only as a path prefix.
    """
    return _PROJECT_DIR_PATTERN.sub(str(project_root), value)


def _expand(value: Any, project_root: Path) -> Any:
    """Expand strings anywhere in a payload, leaving other types alone.

    Recursive because `tool_input` is not flat -- `AskUserQuestion` carries a
    list of dicts, and a path could be nested under any of them.
    """
    if isinstance(value, str):
        return expand_project_dir(value, project_root)
    if isinstance(value, dict):
        return {key: _expand(item, project_root) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand(item, project_root) for item in value]
    return value


def _skip(block: PlaybookBlock, reason: str) -> SkippedProbe:
    return SkippedProbe(
        test_number=block.get("test_number", 0),
        handler_name=block.get("handler_name", "unknown"),
        title=block.get("title", ""),
        reason=reason,
    )


def plan_probe(block: PlaybookBlock, project_root: Path) -> ExecutableProbe | SkippedProbe:
    """Decide what the harness does with one block: dispatch it, or skip it.

    Never guesses. A block that does not declare how to produce its input is
    skipped rather than reconstructed from its prose -- reconstructing it with
    regexes is the failure this plan exists to remove.
    """
    if block.get("harness_cannot_produce"):
        return _skip(block, str(block["harness_cannot_produce"]))

    if block.get("tools_available") is False:
        required = block.get("required_tools") or []
        missing = ", ".join(str(tool) for tool in required) or "an unnamed tool"
        return _skip(block, f"required tool not installed: {missing}")

    # Event type is asked FIRST so the residual reads honestly. A SessionStart
    # block has no payload either, but calling it "prose a human runs" would
    # misreport an OBSERVABLE/VERIFIED_BY_LOAD test as unfinished conversion
    # work -- and the point of reporting a skip at all is that someone can act
    # on it. Only the tests a payload COULD drive should read that way.
    event_type = block.get("event_type") or "none"
    if event_type not in DISPATCHABLE_EVENTS:
        return _skip(block, f"{event_type} carries no tool call for a payload to drive")

    payload = block.get("tool_payload")
    if not payload:
        return _skip(block, "declares no tool payload, so it is prose a human runs")

    tool_input = _expand(dict(payload.get("tool_input") or {}), project_root)

    # An event states WHEN it fires relative to the tool call, so the world
    # has to match that claim or the handler answers a different question.
    # Both directions were measured, and both produced failures that said
    # nothing about the handler under test:
    #
    # PostToolUse says the call ALREADY happened, so the file must exist.
    # `lint_on_edit._is_lintable` ends with `Path(file_path).exists()` --
    # load-bearing and documented as such -- so without the write first, all
    # ten "invalid code blocked" probes report a failure that is not there.
    #
    # PreToolUse says it has NOT happened, so the file must be absent. At a
    # path that already exists the event describes a CLOBBER instead, and
    # `write_clobber_guard` correctly denies it -- which turned three ALLOW
    # probes into failures on nothing worse than residue from an earlier run.
    # Vetted while PLANNING, before anything runs, so a block carrying one
    # unacceptable command is skipped whole rather than half-executed.
    setup = vet_probe_commands(block.get("setup_commands"), project_root)
    if isinstance(setup, RefusedCommands):
        return _skip(block, setup.reason)
    cleanup = vet_probe_commands(block.get("cleanup_commands"), project_root)
    if isinstance(cleanup, RefusedCommands):
        return _skip(block, cleanup.reason)

    names_a_file = bool(tool_input.get(_FILE_PATH_KEY))
    requires_existing_file = event_type == "PostToolUse" and names_a_file
    requires_absent_file = event_type == "PreToolUse" and names_a_file

    return ExecutableProbe(
        test_number=block.get("test_number", 0),
        handler_name=block.get("handler_name", "unknown"),
        title=block.get("title", ""),
        event_type=event_type,
        tool_name=str(payload.get("tool_name") or ""),
        tool_input=tool_input,
        expected_decision=str(block.get("expected_decision") or "").lower(),
        project_root=project_root,
        expected_message_patterns=list(block.get("expected_message_patterns") or []),
        requires_existing_file=requires_existing_file,
        requires_absent_file=requires_absent_file,
        setup_actions=setup,
        cleanup_actions=cleanup,
    )


def split_playbook(
    blocks: list[PlaybookBlock], project_root: Path
) -> tuple[list[ExecutableProbe], list[SkippedProbe]]:
    """Partition every block into exactly one of the two buckets.

    Total by construction, which is the point: this plan's second success
    criterion is that no test can silently fail to be covered by either route,
    and a partition makes "covered by neither" unrepresentable rather than
    merely unlikely.
    """
    executable: list[ExecutableProbe] = []
    skipped: list[SkippedProbe] = []
    for block in blocks:
        planned = plan_probe(block, project_root)
        if isinstance(planned, ExecutableProbe):
            executable.append(planned)
        else:
            skipped.append(planned)
    return executable, skipped


def daemon_error(payload: PlaybookBlock) -> str | None:
    """Report a daemon-level rejection, which is NOT a verdict on the probe.

    This is the subtlest way the harness could pass everything while checking
    nothing. A malformed event is refused by the input schema before any
    handler runs, and the refusal carries no decision at all. Folded into the
    "no decision means allow" rule it makes every ALLOW probe pass vacuously,
    while the DENY probes fail -- which reads like a scatter of handler bugs
    rather than the single harness bug it is.

    It was not hypothetical: this harness's first run sent all 26 PostToolUse
    probes without the `tool_response` that `POST_TOOL_USE_INPUT_SCHEMA`
    requires, and the ALLOW half reported green.
    """
    error = payload.get("error")
    if not error:
        return None
    details = payload.get("details") or []
    rendered = "; ".join(str(detail) for detail in details)
    return f"{error}: {rendered}" if rendered else str(error)


def build_event(probe: ExecutableProbe, run_id: str) -> dict[str, Any]:
    """Assemble the hook event that carries this probe to the daemon.

    The `session_id` is unique in BOTH directions, and each half was measured.

    Per probe, because handlers here carry disclosure ladders that go terse on
    a second fire for the same agent -- a shared session would let one probe
    mute the message another asserts on.

    Per RUN, because some handlers are once-per-session by design.
    `lsp_enforcement` defaults to `block_once`: the first symbol-lookup grep
    in a session is denied and later ones are allowed. A session id fixed to
    the test number means the daemon has already spent that block, so the
    second run sees an allow and reports a perfectly working handler as
    broken. A harness that is only truthful on its first run is worse than no
    harness, because nobody re-reads a green one.

    **`cwd` is the probe's own project root, and deliberately not an
    argument.** An isolated temp directory here is safe for a WRITE payload,
    whose `file_path` is absolute -- which is why measuring isolation over
    those probes shows no difference and makes it look free. It is unsafe for
    a BASH payload, where a relative path resolves against `cwd` and the
    isolation silently relocates the command: `mkdir -p
    CLAUDE/Plan/99999-probe` then lands outside the repository, and
    `project_containment` answers in `plan_number_helper`'s place -- a deny
    that still reads as a pass, plus a sibling allow-probe that denies. 14
    dispatchable handlers read this field, and none wants a directory that is
    not the project, so there is no caller-supplied cwd to get wrong.
    """
    event: dict[str, Any] = {
        "hook_event_name": probe.event_type,
        "tool_name": probe.tool_name,
        "tool_input": probe.tool_input,
        "session_id": f"playbook-probe-{run_id}-{probe.test_number}",
        "cwd": str(probe.project_root),
    }
    if probe.event_type == "PostToolUse":
        # Required by the schema, and its absence is rejected before any
        # handler runs. Minimal rather than tool-specific: no handler reached
        # by a declared payload reads it, and inventing a richer shape per
        # tool would be fabricating detail the playbook never declared.
        event["tool_response"] = {"success": True}
    return event


def verdict(probe: ExecutableProbe, observed_decision: str, observed_text: str) -> str | None:
    """Judge one dispatched probe. `None` is a pass; a string is the failure.

    Two asymmetries, both deliberate and both measured rather than assumed.

    **An absent decision is an allow.** A handler that correctly declines to
    match an allowed input returns no decision at all -- there is nothing to
    report, so nothing is reported. Reading that silence as a failure produced
    18 of Task 1.2's 29 false failures.

    **Patterns are asserted on a deny, not on an allow.** A deny always
    carries its own reason, so the reason can be required, and requiring it is
    the point of Task 2.3: a deny for the WRONG reason is a passing test
    today. An allow's patterns describe advisory text, and this project's
    handlers carry disclosure ladders that deliberately vary that text between
    a first and a later fire. Asserting it would make the harness report
    defects that are not there, which is how a harness gets switched off.
    """
    decision = (observed_decision or "").strip().lower()
    denied = decision in _REFUSAL_SPELLINGS

    if probe.expected_decision == "deny":
        if not denied:
            return (
                f"expected deny, observed {decision or 'no decision at all'} "
                f"(handler {probe.handler_name})"
            )
        missing = [
            pattern
            for pattern in probe.expected_message_patterns
            if not re.search(pattern, observed_text)
        ]
        if missing:
            return (
                "denied, but for a reason that does not match "
                f"{missing!r} -- observed: {observed_text[:300]!r}"
            )
        return None

    if denied:
        return (
            f"expected allow, observed deny (handler {probe.handler_name}): {observed_text[:300]!r}"
        )
    return None
