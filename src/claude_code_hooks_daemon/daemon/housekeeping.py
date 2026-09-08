"""The full housekeeping pass: an ordered step list and its dispositions.

Plan 00330 Phase 3. This module is pure data and pure functions -- it runs
nothing. The ``housekeeping`` CLI verb renders the pass as a procedure for the
agent to follow, and the ``idle_housekeeping_advisory`` handler names the same
report-only steps when it triggers the pass on an idle session, so the two
entry points cannot disagree about what "full housekeeping" means.

Three owner rulings shape the list:

- **Decision 5** -- report-only steps first, mutating steps after, ``optimise``
  last: it restarts the daemon, so every other step runs against the config
  the pass started with and ``optimise`` closes the pass.
- **Decision 6** -- only the idempotent formatters (``format-markdown``,
  ``regenerate-docs``) act without confirmation. Every other mutating step is
  HELD: the pass reports what it would do and acts only when the step is
  named on ``--apply``.
- **Decision 7** -- each step is delegated to a sub-agent that returns what
  it CHANGED, never what it read, so the coordinator's context does not
  accumulate every step's output.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Final

_DEFAULT_REPORTS_DIR: Final[str] = "untracked/reports"


@dataclass(frozen=True, slots=True)
class HousekeepingStep:
    """One step of the pass.

    Attributes:
        name: The step's stable id, the token ``--apply`` takes.
        purpose: One line saying what the step establishes or changes.
        cli_argv: The daemon CLI verb and arguments that run it. Empty for a
            step that runs through the skill instead (``via_skill``).
        via_skill: The hooks-daemon skill args that run the step, when it has
            no CLI verb of its own. ``optimise`` is the only such step: it is
            a confirmation-driven procedure with no CLI equivalent.
        mutates: Whether the step can change the tree, config or settings.
        confirmation_required: A mutating step that is HELD unless named on
            ``--apply``. Always False for a report-only step.
        restarts_daemon: The step bounces the daemon, so it must run last.
    """

    name: str
    purpose: str
    cli_argv: tuple[str, ...]
    mutates: bool
    confirmation_required: bool
    via_skill: str | None = None
    restarts_daemon: bool = False


def _report(name: str, purpose: str, *argv: str) -> HousekeepingStep:
    return HousekeepingStep(
        name=name, purpose=purpose, cli_argv=argv, mutates=False, confirmation_required=False
    )


def _mutating(name: str, purpose: str, *argv: str, confirm: bool = True) -> HousekeepingStep:
    return HousekeepingStep(
        name=name, purpose=purpose, cli_argv=argv, mutates=True, confirmation_required=confirm
    )


#: The pass, in the order it runs. Report-only first, mutating after,
#: ``optimise`` last (Decision 5).
HOUSEKEEPING_STEPS: Final[tuple[HousekeepingStep, ...]] = (
    _report(
        "plan-qa-sweep",
        "Plan-tree drift: every live plan against the plan QA checks",
        "plan-qa",
        "--sweep",
    ),
    _report(
        "docs-qa-sweep",
        "Documentation drift: the doc corpus against the docs QA checks",
        "docs-qa",
        "--sweep",
    ),
    _report(
        "check-worktree-seed",
        "Whether a fresh worktree would be seeded with what it needs",
        "check-worktree-seed",
    ),
    _report(
        "audit-handler-keys",
        "Config keys naming a handler the registry no longer has",
        "audit-handler-keys",
    ),
    _report(
        "check-permissions",
        "Group/other-writable daemon artefacts (report only)",
        "check-permissions",
    ),
    _report("disk-usage", "Venv and artefact disk usage, including stale venvs", "disk-usage"),
    _report(
        "remote-docs-check",
        "Vendored upstream documents past their staleness window",
        "remote-docs",
        "check",
    ),
    _report("verdicts", "Handler verdict frequencies since the last look", "verdicts"),
    _report("block-report", "Which rules blocked, how often, and what was retried", "block-report"),
    _report(
        "harvest-background",
        "Backgrounded processes that outlived their session",
        "harvest-background",
    ),
    _report(
        "worktree-reap", "Agent worktrees whose work is fully merged (report only)", "worktree-reap"
    ),
    _report("skill-scan", "Transcript mining for repeated workloads worth a skill", "skill-scan"),
    _mutating(
        "format-markdown",
        "Normalise markdown (idempotent; acts without confirmation)",
        "format-markdown",
        ".",
        confirm=False,
    ),
    _mutating(
        "regenerate-docs",
        "Rewrite the generated HOOKS-DAEMON.md and CLAUDE.md block (idempotent; acts without confirmation)",
        "regenerate-docs",
        confirm=False,
    ),
    _mutating(
        "reconcile-settings",
        "Reconcile settings.json hook registrations with the daemon's",
        "reconcile-settings",
    ),
    _mutating("remote-docs-refresh", "Re-fetch stale vendored documents", "remote-docs", "refresh"),
    _mutating("prune-venvs", "Delete stale fingerprint-keyed venvs", "prune-venvs"),
    _mutating(
        "check-permissions-fix",
        "Strip group/other bits from the artefacts check-permissions reported",
        "check-permissions",
        "--fix",
    ),
    _mutating(
        "worktree-reap-reap",
        "Remove the worktrees worktree-reap cleared, and their branches",
        "worktree-reap",
        "--reap",
    ),
    HousekeepingStep(
        name="optimise",
        purpose="Config-optimisation review; applies on confirmation and RESTARTS the daemon",
        cli_argv=(),
        via_skill="optimise",
        mutates=True,
        confirmation_required=True,
        restarts_daemon=True,
    ),
)

#: The mutating steps that act without confirmation (Decision 6).
UNCONFIRMED_STEP_NAMES: Final[tuple[str, ...]] = tuple(
    step.name for step in HOUSEKEEPING_STEPS if step.mutates and not step.confirmation_required
)


class Disposition(Enum):
    """What the pass does with a step this run."""

    RUN = "run"
    HELD = "held"


@dataclass(frozen=True, slots=True)
class PlannedStep:
    step: HousekeepingStep
    disposition: Disposition


class UnknownStepError(ValueError):
    """``--apply`` named a step the pass does not have."""


def step_names() -> tuple[str, ...]:
    return tuple(step.name for step in HOUSEKEEPING_STEPS)


def report_only_steps() -> tuple[HousekeepingStep, ...]:
    return tuple(step for step in HOUSEKEEPING_STEPS if not step.mutates)


def mutating_steps() -> tuple[HousekeepingStep, ...]:
    return tuple(step for step in HOUSEKEEPING_STEPS if step.mutates)


def plan_pass(apply: Iterable[str]) -> tuple[PlannedStep, ...]:
    """Assign a disposition to every step, in pass order.

    Args:
        apply: Step names the caller has explicitly released to act. Naming a
            report-only or unconfirmed step is accepted and changes nothing.

    Raises:
        UnknownStepError: A name in ``apply`` is not a step.
    """
    released = set(apply)
    known = set(step_names())
    unknown = sorted(released - known)
    if unknown:
        raise UnknownStepError(
            f"unknown housekeeping step(s): {', '.join(unknown)}. "
            f"Valid names: {', '.join(step_names())}"
        )
    planned: list[PlannedStep] = []
    for step in HOUSEKEEPING_STEPS:
        held = step.confirmation_required and step.name not in released
        planned.append(PlannedStep(step, Disposition.HELD if held else Disposition.RUN))
    return tuple(planned)


def _command_for(step: HousekeepingStep, cli: str) -> str:
    if step.via_skill is not None:
        return f"hooks-daemon skill (Skill tool: skill=hooks-daemon, args={step.via_skill})"
    return " ".join((cli, *step.cli_argv))


def render_procedure(
    planned: Iterable[PlannedStep],
    *,
    cli: str,
    reports_dir: str = _DEFAULT_REPORTS_DIR,
) -> str:
    """The procedure the agent follows to run the pass.

    Args:
        planned: The output of :func:`plan_pass`.
        cli: The daemon CLI wrapper path to print in front of each verb.
        reports_dir: Where each step's full report file goes.
    """
    steps = tuple(planned)
    report_lines: list[str] = []
    mutate_lines: list[str] = []
    for index, item in enumerate(steps, start=1):
        step = item.step
        command = _command_for(step, cli)
        if item.disposition is Disposition.HELD:
            status = f"HELD -- reports only; release with `--apply {step.name}`"
        elif step.mutates:
            status = "RUN -- acts without confirmation (idempotent)"
        else:
            status = "RUN -- report only"
        line = f"{index:2d}. `{step.name}` -- {step.purpose}\n    {command}\n    {status}"
        (mutate_lines if step.mutates else report_lines).append(line)

    return "\n".join(
        (
            "# Hooks Daemon Housekeeping Pass",
            "",
            "You are running the full housekeeping pass. Follow this procedure "
            "exactly; the ORDER is load-bearing.",
            "",
            "## Phase A: report-only steps (independent -- dispatch in parallel)",
            "",
            "Dispatch ONE sub-agent per step. Each sub-agent runs its command, "
            f"writes its full findings to `{reports_dir}/YYYY-MM-DD-<step>.md`, "
            "and returns a final message of AT MOST five lines: the step name, "
            "its verdict (clean / findings / error), a count of findings, the "
            "report path, and what it CHANGED -- which for a report-only step is "
            "always `nothing`. It must NOT paste the command's output into its "
            "reply: the coordinator collates verdicts, not transcripts.",
            "",
            *report_lines,
            "",
            "## Phase B: mutating steps (in this order, one at a time)",
            "",
            "Run these sequentially, after every Phase A sub-agent has returned. "
            "A step marked RUN acts; a step marked HELD runs its report-only "
            "twin's findings forward and changes nothing. Each sub-agent's final "
            "message lists exactly what it CHANGED (paths, keys, deleted "
            "artefacts) or `nothing changed`. A HELD step is released only by "
            "re-running with `--apply <step>`; never infer consent from the "
            "findings.",
            "",
            *mutate_lines,
            "",
            "## Phase C: close",
            "",
            "Print one table -- step, disposition, verdict, changed -- and the "
            "report paths. Restart the daemon only through `optimise` (last "
            "step); nothing earlier may bounce it. Stop with `STOPPING BECAUSE: "
            "housekeeping pass complete; reports under "
            f"{reports_dir}`.",
        )
    )
