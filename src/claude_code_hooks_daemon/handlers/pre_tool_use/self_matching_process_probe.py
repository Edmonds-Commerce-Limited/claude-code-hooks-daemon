"""Deny a liveness probe that matches the shell asking the question.

A field report (``CLAUDE/Plan/00363-…/INCIDENT-REPORT.md``) records a waiter
that cost a session an idle night::

    until ! pgrep -f "provision.bash target-host" >/dev/null; do sleep 20; done

The Bash tool runs every command through ``bash -c "<command>"``, so
``provision.bash target-host`` sat in the waiting shell's OWN argv — and
``pgrep -f`` matches argv. The waiter always found at least one process:
itself. The run it was waiting for finished at 22:23; the waiter was still
sleeping at 08:44 the next morning. The agent also checked by hand twice
during the night with the same ``pgrep -f`` and was told "still running" both
times, so the bug produced a false positive in the check meant to catch it.

**Deny, do not advise.** An advisory in a background waiter is read by nobody,
which is why a self-match is refused wherever it appears rather than only
inside a loop. The one-shot form is the same lie with a shorter fuse: the
report's own timeline has the agent believing a hand-run ``pgrep -f`` twice.

Four rules, one family — a liveness signal that cannot be trusted:

* ``R-PGREP-SELF-MATCH`` (deny) — the pattern matches this command's argv.
* ``R-WAIT-ON-WRAPPER-PID`` (deny for ``setsid``, else advise) — ``$!`` after a
  wrapper that forks names the WRAPPER. The same report's first waiter died of
  this: ``setsid``'s parent exits at once, so ``kill -0 $!`` reported the job
  finished while it was in its fourth minute.
* ``R-UNBOUNDED-LIVENESS-LOOP`` (advise) — a ``while``/``until`` wait on a
  process, with a sleep-only body and nothing capping it. The Bash tool caps a
  FOREGROUND call at ten minutes; ``run_in_background`` has no cap, and that is
  where the night went.
* ``R-PGREP-UNRESOLVED-PATTERN`` (advise) — the pattern is built by expansion,
  so it cannot be judged. Never denied: the daemon does not know what it says.

Detection lives in :mod:`claude_code_hooks_daemon.utils.process_probe`, which
applies the tools' own semantics rather than a pattern list. This handler
decides; it never rewrites the command.

Relevance is deliberately NOT overridden. Every project runs Bash through the
same ``bash -c`` wrapper, so no project state could make this inapplicable —
the case ``Relevance.always()`` is the default for
(``CLAUDE/HANDLER_DEVELOPMENT.md``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import AcceptanceTest, Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.process_probe import (
    LivenessLoop,
    ProbeKind,
    ProbeVerdict,
    ProcessProbe,
    WaitConstruct,
    WrapperPidWait,
    classify_liveness_loops,
    classify_process_probes,
    classify_wrapper_pid_waits,
)

#: Cheap pre-filter. A command naming none of these words cannot carry a probe,
#: and that is nearly all of them. Word-anchored so `https` does not read as
#: `ps`, which a substring test would — except for `$!`, which is punctuation
#: and has no word boundary to anchor on.
_PROBE_WORDS: Final[re.Pattern[str]] = re.compile(r"\b(?:pgrep|pkill|ps|kill|wait)\b|\$!")

#: Why each probe shape cannot answer honestly about itself.
_KIND_HAZARDS: Final[dict[ProbeKind, str]] = {
    ProbeKind.PGREP: (
        "the shell running this command has the pattern on its command line, "
        "and `pgrep -f` matches command lines, so it always finds at least one "
        "process: itself. As a loop condition that never becomes false; as a "
        'liveness check it always says "running".'
    ),
    ProbeKind.PKILL: (
        "the shell running this command has the pattern on its command line, "
        "and `pkill -f` SIGNALS every match rather than reporting it, so this "
        "would kill the shell running it."
    ),
    ProbeKind.PS_GREP: (
        "the `grep` stage's own command line appears in the `ps` output it is "
        "filtering, so the pipeline always matches itself and never reports "
        "zero."
    ),
}

_UNKNOWN_HAZARD: Final = "the probe can match the shell running it."

#: What an unresolvable pattern means, said once.
_UNRESOLVED_HAZARD: Final = (
    "the pattern is built by expansion, so the daemon cannot tell what it "
    "searches for. If it expands to text that also appears in this command, "
    "the probe counts the shell running it and never reports zero."
)

#: How each waiting construct turns a wrong answer into a stuck session.
_LOCATION_PHRASES: Final[dict[WaitConstruct, str]] = {
    WaitConstruct.LOOP: "inside a loop, so the wait can never end",
    WaitConstruct.WATCH: "under `watch`, so it repeats for ever",
    WaitConstruct.TIMEOUT: "inside a timed wait, so it can only ever time out",
}

#: The remedies, in the order the incident report puts them. Waiting on the
#: ARTEFACT leads because it is the only one that removes the class rather than
#: dodging this instance: a log marker cannot match the waiter.
_ALTERNATIVES: Final = (
    "SAFE ALTERNATIVES, best first:\n"
    "  1. Wait on the ARTEFACT, not the process — the shape Claude Code's own "
    "background-task guidance recommends:\n"
    '       until grep -q "PLAY RECAP" run.log; do sleep 10; done\n'
    "     A terminal marker in a log cannot match the waiter.\n"
    "  2. Better still, do not poll at all: a task started with "
    "run_in_background is tracked by the harness, which notifies you when it "
    "finishes. A wait loop costs a turn per poll and still answers late.\n"
    "  3. Bracket the pattern's first character, e.g. "
    "`pgrep -f '[p]rovision.bash'`. It still matches provision.bash in every "
    "OTHER process, while this shell's own command line reads "
    "`[p]rovision.bash`, which the pattern does not match.\n"
    "  4. Match the process NAME instead: `pgrep -x <name>`. This shell is "
    "named `bash`, so a name match can never hit it.\n"
    '  5. Probe a REAL captured pid: `kill -0 "$pid"`, or '
    '`ps -o pid= -p "$pid"`. Beware `$!` after a wrapper such as `setsid` — '
    "that is the wrapper's pid, not the job's.\n"
    "  6. For a `ps … | grep` pipeline, exclude the filter itself with "
    "`| grep -v grep`."
)

_REWRITE_LABEL: Final = "REWRITE THIS COMMAND AS: "

#: Why a wrapper's pid may not be the job's. Two hazards, because the
#: difference decides the verdict: `setsid` ALWAYS abandons the pid, while for
#: the others it depends on what the wrapper was handed.
_DETACHING_HAZARD: Final = (
    "`$!` is the pid of `{wrapper}`, not of the job. `setsid` forks when it is "
    "not already a process-group leader, and its parent exits AT ONCE — so "
    "that pid is gone in milliseconds while the job runs on under a different "
    "one. The wait ends on its first pass and reports the job finished."
)

_FORKING_HAZARD: Final = (
    "`$!` is the pid of `{wrapper}`, and the wrapper is not the job. Whether "
    "that pid gets handed on or kept depends on what the wrapper was asked to "
    "run — `timeout` keeps it, to enforce its own deadline, and `sh -c` execs "
    "a single simple command but forks for anything longer. Advisory rather "
    "than denied because the command text alone does not say which you have."
)

#: Where a wrapper-pid wait sits. Separate from `_LOCATION_PHRASES`, whose
#: "the wait can never end" is the opposite of this fault: a detached pid ends
#: the wait immediately.
_WRAPPER_PLACEMENTS: Final[dict[WaitConstruct, str]] = {
    WaitConstruct.LOOP: "as a loop condition",
    WaitConstruct.WATCH: "under `watch`",
    WaitConstruct.TIMEOUT: "inside a timed wait",
}

#: The remedies the incident report asks for, in the order it puts them.
_WRAPPER_REMEDIES: Final = (
    "SAFE ALTERNATIVES, best first:\n"
    "  1. Wait on the ARTEFACT, not on a pid:\n"
    '       until grep -q "MARKER" run.log; do sleep 10; done\n'
    "     A terminal marker in the log outlives every wrapper that wrote it.\n"
    "  2. Better still, do not poll: a task started with run_in_background is "
    "tracked by the harness, which notifies you when it finishes.\n"
    "  3. Have the JOB record its own pid, inside the same `sh -c`:\n"
    "       nohup sh -c './job.bash > run.log 2>&1 & echo $! > job.pid' &\n"
    "     `$(cat job.pid)` is then the job's pid, not a wrapper's.\n"
    "  4. Resolve the child ONCE from the wrapper's pid: "
    "`pgrep -P <wrapper-pid>`. Do it immediately — after `setsid` the parent "
    "is already gone and there is nothing left to ask.\n"
    "  5. `setsid -w ./job.bash &` also keeps `$!` honest: `-w` makes the "
    "wrapper wait for the job, so the pid lives exactly as long as the job "
    "does. The job still gets its own session; only the wrapper stays in the "
    "process tree."
)


@dataclass(frozen=True, slots=True)
class _Finding:
    """One thing worth saying about a command, and the rule that says it."""

    rule: Rule
    detail: str


def _placement(probe: ProcessProbe) -> str:
    """The clause naming where a probe sits, when that compounds the damage."""
    if probe.wait_construct is None:
        return ""
    return f" — {_LOCATION_PHRASES[probe.wait_construct]}"


def _hazard(probe: ProcessProbe) -> str:
    """The sentence explaining why this probe cannot answer about itself."""
    if probe.verdict is ProbeVerdict.UNRESOLVED:
        return _UNRESOLVED_HAZARD
    hazard = _KIND_HAZARDS.get(probe.kind, _UNKNOWN_HAZARD)
    if probe.lethal and probe.kind is not ProbeKind.PKILL:
        return (
            f"{hazard} The pipeline then signals what it matched, so it would "
            "kill the shell running it."
        )
    return hazard


def _probe_detail(probe: ProcessProbe) -> str:
    """The dynamic, per-probe half of every message this handler emits.

    Carried by BOTH the verbose and the terse deny, because the rewrite for the
    pattern actually typed is the only part a reader cannot reconstruct from
    the rule ID.
    """
    lines = [f"Probe: `{probe.text.strip()}`{_placement(probe)}", f"WHY: {_hazard(probe)}"]
    rewrite = probe.safe_rewrite
    if rewrite is not None:
        lines.append(f"{_REWRITE_LABEL}{rewrite}")
    return "\n".join(lines)


def _wrapper_detail(wait: WrapperPidWait) -> str:
    """The per-site half of the wrapper-pid message, deny or advisory alike."""
    hazard = _DETACHING_HAZARD if wait.detaching else _FORKING_HAZARD
    placement = (
        "" if wait.wait_construct is None else f" {_WRAPPER_PLACEMENTS[wait.wait_construct]}"
    )
    return (
        f"Backgrounded: `{wait.job}`\n"
        f"Waiting on `{wait.reference}` in `{wait.site.strip()}`{placement}\n"
        f"WHY: {hazard.format(wrapper=wait.wrapper)}"
    )


def _loop_detail(loop: LivenessLoop) -> str:
    """The per-loop half of the unbounded-wait advisory."""
    return (
        f"Loop: `{loop.keyword} {loop.condition.strip()}` with a sleep-only body "
        "and no iteration cap.\n"
        "WHY: a run_in_background call has no time limit, so if the probe is "
        "ever wrong this waits for ever and looks exactly like patience."
    )


def _worth_a_word(probe: ProcessProbe) -> bool:
    """Whether an unjudgeable probe is in a shape where being wrong is costly.

    An UNRESOLVABLE pattern earns a word only inside a wait, or where a match
    is signalled. Outside those, a pattern the daemon cannot read costs nothing
    to get wrong, and saying so on every ``pgrep -f "$x"`` would be the noise
    that gets a guard switched off.
    """
    if probe.verdict is not ProbeVerdict.UNRESOLVED:
        return False
    return probe.wait_construct is not None or probe.signals


class SelfMatchingProcessProbeHandler(PreToolUseHandlerBase):
    """Block a liveness probe whose pattern matches the shell running it."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SELF_MATCHING_PROCESS_PROBE,
            priority=Priority.SELF_MATCHING_PROCESS_PROBE,
            terminal=True,
            tags=[
                HandlerTag.SAFETY,
                HandlerTag.BASH,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
            ],
        )
        self._deny_rule = Rule(
            rule_id=RuleID.PGREP_SELF_MATCH,
            # No literal `|` here: `blocked` is rendered into a markdown TABLE
            # cell, and a pipe inside backticks still splits the row (see the
            # mangled R-CURL-PIPE-SHELL row for what that looks like).
            blocked=(
                "a `pgrep -f`/`pkill -f`/`ps`-piped-to-`grep` probe whose literal "
                "pattern matches this command's own argv"
            ),
            why="The probe always finds itself, so a wait never ends and a check always lies",
            fix=(
                "Bracket the first character (`pgrep -f '[p]rovision.bash'`), "
                "or wait on a log marker"
            ),
            verbose=(
                'The Bash tool runs every command through `bash -c "<command>"`, '
                "so the pattern being searched for is ALWAYS on the searching "
                "shell's own command line. `pgrep -f` matches command lines, so "
                "it finds that shell every time.\n\n"
                "The field incident:\n"
                '  until ! pgrep -f "provision.bash target-host" >/dev/null; '
                "do sleep 20; done\n"
                "The run finished at 22:23. The waiter was still sleeping at "
                "08:44 the next morning, and two hand-run checks with the same "
                'pattern had each reported "still running".\n\n'
                f"{_ALTERNATIVES}"
            ),
        )
        self._loop_rule = Rule(
            rule_id=RuleID.UNBOUNDED_LIVENESS_LOOP,
            blocked="a `while`/`until` wait on a process with a sleep-only body and no cap",
            why="run_in_background has no time limit, so a wrong probe waits for ever",
            fix="Wrap it in `timeout 3600 bash -c '…'`, add a counter, or wait on a log marker",
            verbose=(
                "The Bash tool caps a FOREGROUND call at ten minutes. A "
                "`run_in_background` call has no cap at all, so an uncapped wait "
                "on a process can idle indefinitely — and it looks exactly like "
                "patience the whole time.\n\n"
                "Bound it, or remove the need for it:\n"
                "  timeout 3600 bash -c 'until ! <probe>; do sleep 10; done'\n"
                '  i=0; until ! <probe> || [ "$i" -ge 60 ]; do sleep 10; '
                "i=$((i+1)); done\n"
                '  until grep -q "PLAY RECAP" run.log; do sleep 10; done\n\n'
                "A loop whose condition reads an ARTEFACT is never flagged here: "
                "a log marker cannot match the waiter, which is what makes it the "
                "recommended shape."
            ),
        )
        self._wrapper_rule = Rule(
            rule_id=RuleID.WAIT_ON_WRAPPER_PID,
            blocked=(
                "a wait on `$!` when the backgrounded command starts with a "
                "wrapper that forks — denied for `setsid`, advisory for "
                "`nohup sh -c`, `timeout` and `env`"
            ),
            why=(
                "`$!` is the wrapper's pid, and setsid's parent exits at once, "
                "so the wait ends immediately and reports success"
            ),
            fix=(
                "Let the job write its own pidfile, resolve the child with "
                "`pgrep -P`, or wait on a log marker"
            ),
            verbose=(
                "`$!` holds the pid of the last command the shell "
                "BACKGROUNDED, which is the wrapper — not the job the wrapper "
                "goes on to run.\n\n"
                "The field incident's FIRST waiter:\n"
                "  setsid nohup ./job.bash > run.log 2>&1 &\n"
                "  until ! kill -0 $!; do sleep 15; done\n"
                "`setsid` forks and its parent exits at once, so that pid died "
                "in milliseconds while the real run continued under the next "
                'one. The waiter announced "finished" with the job in its '
                "fourth minute; a truncated log was the only clue.\n\n"
                "`setsid` is denied because it is unambiguous: its parent "
                "always exits. `nohup sh -c`, `nohup bash -c`, `timeout` and "
                "`env` only advise — some of them exec in place and hand the "
                "pid straight on, and which you get depends on what you asked "
                "them to run.\n\n"
                f"{_WRAPPER_REMEDIES}"
            ),
        )
        self._unresolved_rule = Rule(
            rule_id=RuleID.PGREP_UNRESOLVED_PATTERN,
            blocked="a process probe whose pattern is built by expansion, inside a wait or a kill",
            why="If it expands to text in this command's argv, the probe counts the caller",
            fix="Bracket the pattern where it is built, or wait on a log marker",
            verbose=(
                "This is NEVER denied: the daemon cannot read what an expansion "
                "says, so it cannot claim the probe is wrong. It is worth a word "
                "only here — inside a wait, or where a match would be signalled — "
                "because those are the shapes where being wrong is expensive.\n\n"
                "If the variable holds a literal that also appears in this "
                "command, the probe matches the shell running it exactly as a "
                "written-out literal would.\n\n"
                f"{_ALTERNATIVES}"
            ),
        )
        self._formatter = RuleFormatter()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True only when there is something worth reporting on."""
        command = get_bash_command(hook_input)
        if hook_input.get(HookInputField.TOOL_NAME) != ToolName.BASH or not command:
            return False
        if _PROBE_WORDS.search(command) is None:
            return False
        denials, advisories = self._collect(command)
        return bool(denials or advisories)

    def get_rules(self) -> list[Rule]:
        """Every rule in the family, blocking and advisory alike."""
        return [self._deny_rule, self._wrapper_rule, self._loop_rule, self._unresolved_rule]

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny a self-match; advise on an uncapped wait or an unreadable pattern."""
        command = get_bash_command(hook_input)
        if not command:
            return GatingResult(decision=Decision.ALLOW)
        denials, advisories = self._collect(command)
        if denials:
            return GatingResult(
                decision=Decision.DENY,
                reason=self._deny_reason(hook_input, denials[0]),
            )
        if advisories:
            return GatingResult(
                decision=Decision.ALLOW,
                context=[f"[{finding.rule.rule_id}] {finding.detail}" for finding in advisories],
                guidance=self._advisory_guidance(advisories),
            )
        return GatingResult(decision=Decision.ALLOW)

    def _collect(self, command: str) -> tuple[list[_Finding], list[_Finding]]:
        """Split this command's findings into the denials and the advisories."""
        denials: list[_Finding] = []
        advisories: list[_Finding] = []

        for probe in classify_process_probes(command):
            if probe.is_self_matching:
                denials.append(_Finding(self._deny_rule, _probe_detail(probe)))
            elif _worth_a_word(probe):
                advisories.append(_Finding(self._unresolved_rule, _probe_detail(probe)))

        # A detaching wrapper is a denial; the rest advise. Reported AFTER the
        # self-match so that, when a command carries both, the denial the
        # reader gets is the one that names a concrete rewrite.
        for wait in classify_wrapper_pid_waits(command):
            finding = _Finding(self._wrapper_rule, _wrapper_detail(wait))
            (denials if wait.detaching else advisories).append(finding)

        for loop in classify_liveness_loops(command):
            if loop.is_unbounded_liveness_wait:
                advisories.append(_Finding(self._loop_rule, _loop_detail(loop)))

        return denials, advisories

    def _deny_reason(self, hook_input: dict[str, Any], finding: _Finding) -> str:
        """Verbose on first fire per agent, terse after (Plan 00116, Decision G).

        The per-probe detail — including the concrete rewrite — is appended to
        BOTH forms. The static rule text can only show an example pattern; the
        rewrite for the pattern actually typed is what saves the retry.
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure
        rule_id = finding.rule.rule_id

        if transcript_path and tracker.was_disclosed(transcript_path, rule_id):
            return f"{self._formatter.terse(finding.rule)}\n\n{finding.detail}"
        if transcript_path:
            tracker.mark_disclosed(transcript_path, rule_id)
        return f"{self._formatter.verbose(finding.rule)}\n\n{finding.detail}"

    def _advisory_guidance(self, advisories: list[_Finding]) -> str:
        """The teaching text for each DISTINCT advisory rule that fired.

        Deduplicated by rule: two uncapped loops in one command are two
        findings but one lesson, and repeating it would bill the reader twice.
        """
        seen: list[Rule] = []
        for finding in advisories:
            if finding.rule not in seen:
                seen.append(finding.rule)
        return "\n\n".join(self._formatter.verbose(rule) for rule in seen)

    def get_claude_md(self) -> str | None:
        """Earns a section under Test 1: this handler DENIES a Bash command.

        It also passes Test 4 against every neighbouring section: nothing else
        in the block explains why a liveness probe reports success for ever, and
        that invisibility is what made the field incident cost a whole night
        rather than a turn.
        """
        return (
            "## self_matching_process_probe — a liveness probe must not count itself\n\n"
            'The Bash tool runs every command as `bash -c "<command>"`, so the '
            "pattern you search for is ALWAYS on the searching shell's own command "
            "line. `pgrep -f` matches command lines, so it finds that shell every "
            'time and reports "still running" for ever. In the field incident that '
            "cost an idle night, and two hand-run checks with the same pattern "
            "confirmed the wrong answer.\n\n"
            "**Blocked** — the pattern matches this command's own argv:\n\n"
            "- `pgrep -f \"provision.bash\"` / `pgrep -af 'provisioner'`\n"
            "- `pkill -f <literal>` (signals the shell that asked)\n"
            '- `ps aux | grep "provisioner"` with no self-exclusion\n\n'
            "Denied wherever it appears, not just in a loop: an advisory inside a "
            "background waiter is read by nobody.\n\n"
            "**Allowed, and these are the fixes**:\n\n"
            '- **Wait on the artefact**: `until grep -q "PLAY RECAP" run.log; do '
            "sleep 10; done`. A log marker cannot match the waiter.\n"
            "- **Better, do not poll**: a `run_in_background` task is tracked by "
            "the harness, which notifies you when it finishes.\n"
            "- `pgrep -f '[p]rovision.bash'` — the bracket still matches "
            "`provision.bash` in every OTHER process; this shell's line now reads "
            "`[p]rovision.bash`, which the pattern does not match.\n"
            "- `pgrep -x <name>` — matches the process NAME, and this shell is "
            "named `bash`.\n"
            '- `kill -0 "$pid"` / `ps -o pid= -p "$pid"` with a REAL pid. `$!` '
            "after `setsid` is the wrapper's pid, not the job's.\n"
            "- `ps aux | grep foo | grep -v grep` — the filter excludes its own "
            "line.\n\n"
            "**Also blocked — waiting on a WRAPPER's `$!`** "
            "(`R-WAIT-ON-WRAPPER-PID`). `setsid nohup ./job.bash &` makes `$!` "
            "the pid of `setsid`, which forks and whose parent exits at once, "
            "so `kill -0 $!` says the job finished while it is still running — "
            "the same incident's FIRST waiter. Denied for `setsid`; advisory "
            "for `nohup sh -c`, `timeout` and `env`, where whether the pid is "
            "the job's turns on what the wrapper was asked to run. Fix: let "
            "the job record its own pid "
            "(`nohup sh -c './job.bash > run.log 2>&1 & echo $! > job.pid' &`), "
            "resolve the child once with `pgrep -P <wrapper-pid>`, or wait on "
            "the log marker. A plain `./job.bash & pid=$!` needs none of this: "
            "with no wrapper, `$!` already is the job.\n\n"
            "**Advisory, never blocking**: a `while`/`until` wait on a process "
            "with a sleep-only body and no cap (`run_in_background` has no time "
            'limit), and a pattern built by expansion (`pgrep -f "$job"`), which '
            "the daemon cannot read."
        )

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        """Deny, advise and allow, driven as real Bash payloads."""
        from claude_code_hooks_daemon.core import RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Self-matching pgrep wait loop is blocked",
                command=(
                    'false && until ! pgrep -f "provision.bash target-host" >/dev/null; '
                    "do sleep 20; done"
                ),
                dispatch_as_bash=True,
                description=(
                    "The field incident verbatim: the pattern is on the waiting "
                    "shell's own command line, so the loop can never exit."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED",
                    RuleID.PGREP_SELF_MATCH,
                    r"\[p\]rovision\.bash target-host",
                    r"PLAY RECAP",
                ],
                safety_notes=(
                    "'false &&' short-circuits, so the loop never runs even if the "
                    "deny were to fail. Detection happens at the PreToolUse hook "
                    "before the shell starts, so the short-circuit is a second "
                    "layer rather than the mechanism. This must NOT be wrapped in "
                    "echo: the classifier reads command positions, so echo would "
                    "make the whole loop a quoted argument and detect nothing."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="pkill -f on a literal pattern is blocked",
                command="false && pkill -f probe-demo-job",
                dispatch_as_bash=True,
                description=(
                    "`pkill -f` signals every match, and the pattern is on this "
                    "shell's own command line, so it would kill the caller."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED",
                    r"kill the shell running it",
                    r"\[p\]robe-demo-job",
                ],
                safety_notes=(
                    "'false &&' short-circuits so pkill never runs. The pattern "
                    "names nothing real, so even a mis-fire could only match the "
                    "shell this handler exists to protect."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="ps piped to grep with no self-exclusion is blocked",
                command='false && ps aux | grep "probe-demo-job" | wc -l',
                dispatch_as_bash=True,
                description=(
                    "The grep's own line appears in the ps output it filters, so "
                    "the count is never zero."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"BLOCKED", r"grep -v grep"],
                safety_notes=(
                    "'false &&' short-circuits. Even run, ps and grep are "
                    "read-only and the pattern names nothing real."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Waiting on a setsid wrapper's $! is blocked",
                command="false && setsid ./probe-demo-job.bash & wait $!",
                dispatch_as_bash=True,
                description=(
                    "The incident's FIRST waiter: `$!` is `setsid`'s pid, and "
                    "setsid's parent exits at once, so the wait ends before "
                    "the job has started."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED",
                    RuleID.WAIT_ON_WRAPPER_PID,
                    r"setsid",
                    r"job\.pid",
                    r"pgrep -P",
                ],
                safety_notes=(
                    "'false &&' short-circuits, so the backgrounded list exits "
                    "immediately and `wait` returns at once — it cannot hang. "
                    "The job name points at nothing real. Detection happens at "
                    "the PreToolUse hook before any shell starts."
                ),
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Waiting on a timeout wrapper's $! is advisory",
                command="false && timeout 600 ./probe-demo-job.bash & wait $!",
                dispatch_as_bash=True,
                description=(
                    "`timeout` stays alive beside the job, so the pid is the "
                    "wrong one rather than a dead one — worth a word, not a "
                    "denial."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[RuleID.WAIT_ON_WRAPPER_PID],
                safety_notes=(
                    "'false &&' short-circuits, so nothing is launched and "
                    "`wait` returns immediately on an already-exited shell."
                ),
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Waiting on an unwrapped job's $! is allowed",
                command="false && ./probe-demo-job.bash & wait $!",
                dispatch_as_bash=True,
                description=(
                    "The near-miss ALLOW: same wait, no wrapper, so `$!` "
                    "really is the job's pid and there is nothing to say."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "'false &&' short-circuits, so nothing runs and `wait` " "returns immediately."
                ),
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="An uncapped wait on a real pid is advisory",
                command='false && until ! kill -0 "$pid" 2>/dev/null; do sleep 5; done',
                dispatch_as_bash=True,
                description=(
                    "The pid probe is honest, so nothing is denied — but the loop "
                    "has no cap, and run_in_background imposes none either."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[RuleID.UNBOUNDED_LIVENESS_LOOP],
                safety_notes=(
                    "'false &&' short-circuits so nothing loops. `kill -0` sends "
                    "no signal; it only tests whether a pid exists."
                ),
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="A bracket-tricked pattern is allowed inside a loop",
                command=(
                    'false && until ! pgrep -f "[p]robe-demo-job" >/dev/null; do sleep 1; done'
                ),
                dispatch_as_bash=True,
                description=(
                    "The near-miss ALLOW: same loop, same tool, pattern rewritten "
                    "so it can no longer match the shell running it."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "'false &&' short-circuits so nothing loops. Were it to run, "
                    "the probe matches nothing, so the until-condition is true "
                    "immediately and the body never executes."
                ),
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="pgrep -x is allowed",
                command="pgrep -x probe-demo-job",
                dispatch_as_bash=True,
                description=(
                    "Name mode compares against `comm`, which for this shell is "
                    "`bash`, so the probe cannot match itself."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Read-only. Exits 1 because no process is named that, which is "
                    "the correct outcome and not a test failure."
                ),
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="ps piped to grep with a self-exclusion is allowed",
                command="ps aux | grep probe-demo-job | grep -v grep",
                dispatch_as_bash=True,
                description=(
                    "`grep -v grep` removes the filter's own line from the ps "
                    "output, which is the documented remedy for this pipeline."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Read-only. grep is on pipe_blocker's cheap-filter whitelist, "
                    "so the pipeline is not truncating anything. The pattern is "
                    "HYPHENATED on purpose: an identifier-shaped one such as "
                    "`probe_demo_job` reads as a class/function name to "
                    "lsp_enforcement, which denies the first symbol-lookup grep "
                    "of a session and would fail this ALLOW case in a live run."
                ),
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Waiting on a log marker is allowed",
                command='false && until grep -q "PLAY RECAP" run.log; do sleep 10; done',
                dispatch_as_bash=True,
                description=(
                    "The recommended shape: a log marker cannot match the waiter, "
                    "so neither rule has anything to say about it."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "'false &&' short-circuits. grep -q on a missing file exits "
                    "non-zero and writes nothing."
                ),
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
