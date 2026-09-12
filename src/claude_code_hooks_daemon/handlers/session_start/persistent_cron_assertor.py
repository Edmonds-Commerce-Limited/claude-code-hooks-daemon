"""PersistentCronAssertorHandler - re-establish declared crons (Plan 00384).

Claude Code's crons cannot persist. ``CronCreate`` documents its ``durable``
parameter as having no effect, every job lives in session memory only, and
recurring jobs auto-expire after 7 days. So a cron a project wants to ALWAYS
have is not something you create once — it has to be declared somewhere durable
and re-established each session.

This handler is the assertion half. The project declares its jobs under
``persistent_crons`` in ``.claude/hooks-daemon.yaml``; at session start this
states them in full and tells the agent to reconcile against ``CronList``.

**It asserts by instruction, never by verification, and the wording matters.**
The daemon cannot read Claude Code's session memory, so it does not know which
jobs exist. Phrasing a finding as "this cron is missing" would be a claim the
daemon cannot support, and the agent would act on it — creating a duplicate of
a job that was already running. Everything here is therefore framed as "these
are declared; check and create what is absent".

Inertness comes from ONE switch — ``persistent_crons.enabled`` — rather than
from the handler's own enabled flag as well. A project that declared jobs and
switched the section on would otherwise still get nothing, with no way to tell
why.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from claude_code_hooks_daemon.config.models import Config, PersistentCronConfig
from claude_code_hooks_daemon.constants.handlers import HandlerID
from claude_code_hooks_daemon.constants.priority import Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase

logger = logging.getLogger(__name__)


class PersistentCronAssertorHandler(SessionStartHandlerBase):
    """State the project's declared crons and instruct a CronList reconcile."""

    def __init__(self) -> None:
        """Initialise as a non-terminal advisory."""
        super().__init__(
            handler_id=HandlerID.PERSISTENT_CRON_ASSERTOR,
            priority=Priority.PERSISTENT_CRON_ASSERTOR,
            terminal=False,
        )

    def get_default_enabled(self) -> bool:
        """Enabled, but silent until the project declares a job.

        The config section is the master switch; a second handler-level switch
        would only create a state where a fully-configured project silently
        gets nothing.
        """
        return True

    def _project_root(self) -> Path:
        root = getattr(self, "_workspace_root", None)
        return Path(root) if root is not None else ProjectContext.project_root()

    def _load_config(self) -> Config:
        """The project's daemon config; defaults on an unloadable file.

        A config the daemon already reports as invalid must degrade this
        advisory to silent rather than raise out of the SessionStart chain and
        take every other advisory down with it.
        """
        config_path = self._project_root() / ".claude" / "hooks-daemon.yaml"
        try:
            return Config.load_or_default(config_path)
        except (ValidationError, OSError, ValueError) as exc:
            logger.debug("persistent_cron_assertor: cannot load %s: %s", config_path, exc)
            return Config()

    def _active_jobs(self) -> list[PersistentCronConfig]:
        return self._load_config().persistent_crons.active_jobs()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Fire only when the project has at least one active declared job."""
        return bool(self._active_jobs())

    @staticmethod
    def _render_job(job: PersistentCronConfig) -> list[str]:
        heading = f"  • {job.id}"
        if job.description:
            heading = f"{heading} — {job.description}"
        lines = [heading, f"    schedule (recurring): {job.schedule}", "    prompt:"]
        lines.extend(f"      {line}" for line in job.prompt.splitlines() or [""])
        return lines

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Emit the declared jobs plus the reconcile instruction."""
        jobs = self._active_jobs()
        if not jobs:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        plural = "job" if len(jobs) == 1 else "jobs"
        lines = [
            f"📌 DECLARED PERSISTENT CRONS ({len(jobs)} {plural}) — re-establish any that "
            "are absent.",
            "",
            "Claude Code crons do NOT persist: `durable` has no effect, jobs live in "
            "session memory only, and recurring jobs auto-expire after 7 days. This "
            "project therefore DECLARES the crons it wants in every session, and they "
            "have to be re-created after each new session starts.",
            "",
            "The daemon cannot read session memory, so it does not know which of these "
            "are already running — it is stating what the project DECLARED, not "
            "reporting which ones are absent. Reconcile it yourself:",
            "",
            "  1. Run CronList FIRST.",
            "  2. For each declared job below with no equivalent already listed, create "
            "it with CronCreate (recurring: true) using the schedule and prompt given.",
            "  3. If one IS already listed, create nothing for it — a duplicate fires "
            "twice an hour and costs a model turn each time.",
            "",
            f"DECLARED {plural.upper()}:",
        ]
        for job in jobs:
            lines.extend(self._render_job(job))
        return AdvisoryResult(decision=Decision.ALLOW, context=lines)

    def get_acceptance_tests(self) -> list[Any]:
        """One CONTEXT case: a declared job is stated at session start."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="persistent cron assertor - states declared crons at session start",
                command='echo "test"',
                description=(
                    "With persistent_crons.enabled true and at least one job "
                    "declared, session start carries the job's id, schedule and "
                    "prompt plus the instruction to reconcile against CronList."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"DECLARED PERSISTENT CRONS|CronList"],
                safety_notes="Advisory only — never creates a cron itself, never blocks.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="SessionStart event (new session only)",
                requires_main_thread=False,
            ),
        ]

    def get_claude_md(self) -> str | None:
        """Resident guidance for the active-handler block."""
        return (
            "## persistent_cron_assertor — declared crons are re-established each "
            "session\n\n"
            "**Claude Code crons do not persist, and this is the whole reason the "
            "handler exists.** `CronCreate`'s `durable` parameter has no effect, jobs "
            "live in session memory only, and recurring jobs auto-expire after 7 days. "
            "So a cron the project must ALWAYS have cannot be created once — it is "
            "declared under `persistent_crons` in `.claude/hooks-daemon.yaml` and "
            "re-created each session.\n\n"
            "At session start this states every active declared job in full (id, "
            "schedule, prompt). **It is telling you what is DECLARED, not what is "
            "missing** — the daemon cannot read Claude Code's session memory, so it "
            "cannot know which jobs are already running. Run `CronList` first and "
            "create only what is absent; creating a duplicate makes the job fire twice "
            "an hour, costing a model turn each time.\n\n"
            "Inertness is controlled by ONE switch, `persistent_crons.enabled`, which "
            "is off by default and overrides each job's own `enabled` flag. A project "
            "that declares nothing gets nothing."
        )
