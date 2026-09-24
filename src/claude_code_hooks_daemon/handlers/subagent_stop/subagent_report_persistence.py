"""SubagentReportPersistenceHandler - persist every reply to a gitignored file.

Plan 00460 Task 1.6. The owner asked directly: "is there a hook we can use
at main agent level to ensure sub agent reports are persisted to file?"
This handler is the daemon-level answer: EVERY SubagentStop's
``last_assistant_message`` is saved to a gitignored location, regardless of
agent type or ``Write`` access, so persistence never depends on the agent's
own cooperation or tool set.

Task 1.2 ruled out an EARLIER, similarly-shaped idea (the daemon saving an
over-long reply to the coordinator's DECLARED, tracked plan-folder path) on
the grounds that the daemon cannot cheaply replicate the live,
per-project-configured content checks a real ``Write`` call would get. That
reasoning holds for a TRACKED destination; it does not apply here. This
handler ONLY ever writes under a gitignored path (default
``untracked/agent-reports/``, confirmed gitignored by
``test_report_dir_is_gitignored``). ``last_assistant_message`` already
reaches the coordinator's context and Claude Code's own on-disk transcript,
so saving it to a path git never sees discloses nothing new — no
sensitive-content, secret-file or markdown-location check is needed.

Never blocks (a sensor, like ``subagent_cache_aggregator``): persistence
failing must never strand a stopping agent. Never overwrites (each write is
a NEW file; a same-second collision still gets a numeric suffix). Bounded
from day one via ``utils.retention.prune_directory`` — Plan 00181's
retention primitive, built specifically because an earlier untracked writer
with no pruner grew to 14 GB unnoticed (issue #52).

Runs BEFORE the terminal ``subagent_report_size_blocker`` (priority 10 vs
15) so a persisted file already exists by the time the size blocker's glob
lookup (``utils.subagent_report_paths.find_persisted_report``) runs. There
is no in-memory hand-off between the two handlers — only this priority
ordering plus the file this handler already wrote.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SubagentStopHandlerBase
from claude_code_hooks_daemon.utils.option_coercion import coerce_int_option
from claude_code_hooks_daemon.utils.path_exclusion import resolve_project_root
from claude_code_hooks_daemon.utils.retention import prune_directory
from claude_code_hooks_daemon.utils.subagent_report_paths import (
    DEFAULT_REPORT_DIR,
    report_filename,
    write_new_file_never_overwrite,
)

_LOGGER = logging.getLogger(__name__)

# Sane defaults, not policy: every project can override via
# subagent_report_persistence.options.{max_kept_reports,max_report_age_days}.
# A report is typically small (the threshold this project's size blocker
# uses is 4000 characters), so even the count cap alone bounds this well
# under a few MB; the age cap is the second, independent criterion
# prune_directory applies (excess by EITHER counts).
_DEFAULT_MAX_KEPT_REPORTS = 500
_DEFAULT_MAX_REPORT_AGE_DAYS = 30

_SECONDS_PER_DAY = 86_400
_REPORT_GLOB_PATTERN = "*.md"


class SubagentReportPersistenceHandler(SubagentStopHandlerBase):
    """Persist every stopping sub-agent's final reply to a gitignored file.

    Fails open on any missing/empty/non-string ``last_assistant_message``
    (nothing to persist) and never re-fires on ``stop_hook_active``
    re-entry, mirroring its sibling SubagentStop handlers.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SUBAGENT_REPORT_PERSISTENCE,
            priority=Priority.SUBAGENT_REPORT_PERSISTENCE,
            terminal=False,
            tags=[HandlerTag.WORKFLOW, HandlerTag.NON_TERMINAL],
        )
        # Config flags, declared here so mypy can verify them and a typo in a
        # config setter surfaces as a normal attribute (fail-fast). `Any` for
        # the two numeric options: they arrive by blind setattr from YAML, so
        # a string value is a real runtime possibility `_max_*()` guards
        # against via the shared `coerce_int_option` helper (same idiom as
        # subagent_report_size_blocker's `_threshold_chars: Any`).
        self._report_dir: str = DEFAULT_REPORT_DIR
        self._max_kept_reports: Any = _DEFAULT_MAX_KEPT_REPORTS
        self._max_report_age_days: Any = _DEFAULT_MAX_REPORT_AGE_DAYS
        # Test-only override (mirrors subagent_report_size_blocker's
        # identically-named attribute): production resolves lazily via
        # `_root()` so the handler is never pinned to whatever directory the
        # daemon happened to start in.
        self._project_root: Path | None = None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for every SubagentStop except a re-entry (loop guard)."""
        return not bool(hook_input.get("stop_hook_active", False))

    def _root(self) -> Path:
        """The checkout the report directory is resolved under.

        An injected test override wins, then the registry's
        ``workspace_root`` option, then :func:`resolve_project_root` (None
        when ``ProjectContext`` is not initialised, e.g. a bare unit test),
        falling back to the process cwd so this always returns a concrete
        path.
        """
        if self._project_root is not None:
            return self._project_root
        workspace_root = getattr(self, "_workspace_root", None)
        if workspace_root is not None:
            return Path(workspace_root)
        resolved = resolve_project_root()
        return Path(resolved) if resolved is not None else Path.cwd()

    def _target_dir(self) -> Path:
        return self._root() / self._report_dir

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Persist ``last_assistant_message`` to a new gitignored file, then ALLOW.

        Always ALLOW: a sensor on a blocking event, like
        ``subagent_cache_aggregator`` — a figure (or here, a file) that
        could not be recorded must never strand a stopping agent.
        """
        message = hook_input.get("last_assistant_message")
        if not isinstance(message, str) or not message.strip():
            _LOGGER.debug(
                "subagent_report_persistence: nothing to persist "
                "(missing/empty/non-string last_assistant_message)"
            )
            return BlockingResult(decision=Decision.ALLOW)

        agent_type = hook_input.get("agent_type")
        agent_id = hook_input.get("agent_id")
        filename = report_filename(
            agent_type if isinstance(agent_type, str) else "",
            agent_id if isinstance(agent_id, str) else "",
            when=datetime.now(UTC),
        )
        target_dir = self._target_dir()
        written = write_new_file_never_overwrite(target_dir, filename, message)
        if written is not None:
            prune_directory(
                target_dir,
                pattern=_REPORT_GLOB_PATTERN,
                max_count=coerce_int_option(
                    self._max_kept_reports, default=_DEFAULT_MAX_KEPT_REPORTS
                ),
                max_age_seconds=coerce_int_option(
                    self._max_report_age_days, default=_DEFAULT_MAX_REPORT_AGE_DAYS
                )
                * _SECONDS_PER_DAY,
                now=datetime.now(UTC).timestamp(),
                # The file JUST written must survive even a max_count of 1 --
                # pruning would otherwise be able to delete the write this
                # very call made, on its own next invocation's count check.
                protect=(written,),
            )

        return BlockingResult(decision=Decision.ALLOW)

    def get_claude_md(self) -> str | None:
        return (
            "## subagent_report_persistence — every sub-agent reply is saved to a file\n\n"
            "At every SubagentStop, the daemon saves the stopping agent's final "
            "message to a gitignored file under "
            f"`{DEFAULT_REPORT_DIR}` (`<yymmdd>-<HHMMSS>-<agent_type>-<agent_id>.md`), "
            "regardless of agent type or `Write` access — so persistence never "
            "depends on the agent's own cooperation. Never overwrites (a "
            "collision gets a numeric suffix); pruned to a configured cap "
            "(default 500 files / 30 days, `options.max_kept_reports` / "
            "`options.max_report_age_days`) after every write. Never blocks "
            "a stop — persistence failing is logged, not fatal.\n\n"
            "`subagent_report_size_blocker` looks up what this handler already "
            "saved (by agent type/id, not an exact filename) and points an "
            "over-threshold agent at that path instead of asking it to write "
            "one itself."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the subagent report persistence handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Subagent stop persists the final reply to a gitignored file",
                command="Dispatch any subagent and let it finish with a short reply",
                description=(
                    "Every SubagentStop saves last_assistant_message to "
                    "untracked/agent-reports/, whether or not the reply is "
                    "over the size threshold and regardless of agent type"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Never blocks -- a sensor. Persistence failing is logged, "
                    "never raised into the stop dispatch."
                ),
                test_type=TestType.ADVISORY,
                requires_event="SubagentStop",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
                # SubagentStop carries no tool call, so a ToolPayload cannot
                # describe it (Plan 00319 Task 4.6) -- hook_input drives the
                # CI-time contract test directly, matching the sibling
                # handlers' own note.
                hook_input={
                    "hook_event_name": "SubagentStop",
                    "agent_id": "agent-1",
                    "agent_type": "Explore",
                    "last_assistant_message": "done, found nothing notable",
                    "stop_hook_active": False,
                },
            ),
        ]
