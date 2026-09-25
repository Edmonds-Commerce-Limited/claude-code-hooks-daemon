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
reasoning holds for a TRACKED destination; it does not apply here, because
this handler ONLY ever writes under a gitignored path (default
``untracked/agent-reports/auto/``) — but "gitignored" is now a GUARANTEE
this code enforces at runtime (a code review found the earlier version's
only evidence was a test against THIS repo's own ``.gitignore``, which said
nothing about a client project with no matching rule):
``write_new_file_never_overwrite`` drops a self-ignoring ``*`` ``.gitignore``
into the report directory the first time it creates it, so the guarantee
travels WITH the directory into every project. No sensitive-content,
secret-file or markdown-location check runs on the content itself — a
persisted reply is NOT vetted the way a real ``Write`` call would be, only
kept out of git's view.

``.../auto/`` is a subdirectory the daemon exclusively writes into, distinct
from the ``untracked/agent-reports/`` a coordinator or agent may be
told to hand-author a non-plan report into (``dispatch_declaration``'s
fallback). Retention (below) only ever prunes ``.../auto/`` — an earlier
version pruned the shared parent directory too, which deleted
deliberately-authored reports a review found still sitting there.

Never blocks (a sensor, like ``subagent_cache_aggregator``): persistence
failing must never strand a stopping agent. Never overwrites (each write is
a NEW file; a same-second collision still gets a numeric suffix). Matches
EVERY SubagentStop, including a re-entry after another handler's block —
there is no deny loop to guard against here, and skipping a re-entry would
mean the agent's real, corrected final reply is never the one saved. Bounded
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

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SubagentStopHandlerBase
from claude_code_hooks_daemon.daemon.synthetic_traffic import is_synthetic_event
from claude_code_hooks_daemon.utils.option_coercion import coerce_int_option
from claude_code_hooks_daemon.utils.path_exclusion import resolve_lookup_root
from claude_code_hooks_daemon.utils.retention import prune_directory
from claude_code_hooks_daemon.utils.subagent_report_paths import (
    DEFAULT_PERSISTED_REPORT_DIR,
    report_filename,
    resolve_confined_report_dir,
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
    (nothing to persist) and on an unsafe ``report_dir`` (empty, ``.``,
    absolute or ``..``-escaping). Matches every SubagentStop, INCLUDING a
    re-entry (review M2) -- unlike its BLOCKING sibling handlers, this one
    never denies, so there is no deny loop to guard against.
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
        self._report_dir: str = DEFAULT_PERSISTED_REPORT_DIR
        self._max_kept_reports: Any = _DEFAULT_MAX_KEPT_REPORTS
        self._max_report_age_days: Any = _DEFAULT_MAX_REPORT_AGE_DAYS
        # Test-only override (mirrors subagent_report_size_blocker's
        # identically-named attribute): production resolves lazily via
        # `_root()` so the handler is never pinned to whatever directory the
        # daemon happened to start in.
        self._project_root: Path | None = None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for every real SubagentStop, including a re-entry.

        Review M2: the ``stop_hook_active`` skip other SubagentStop
        handlers use guards against a BLOCKING handler looping on its own
        deny. This handler never denies, so there is no loop to guard
        against -- and dropping a re-entry stop would mean the agent's
        real, corrected final reply (the one that survived a block from
        another handler and kept working) is never the one persisted.

        A synthetic stop is skipped (Plan 00466 N12): a probe standing for a
        subagent is not a teammate, and persisting it would file a report
        no agent wrote.
        """
        return not is_synthetic_event(hook_input)

    def _root(self) -> Path:
        """The checkout the report directory is resolved under.

        Review m5: this precedence (test override, then the registry's
        ``workspace_root`` option, then :func:`resolve_project_root` with a
        cwd fallback) used to be duplicated here line-for-line against
        ``subagent_tool_resolution.resolve_lookup_root`` — delegates to the
        shared :func:`resolve_lookup_root` (``path_exclusion.py``) instead.
        """
        return resolve_lookup_root(self._project_root, getattr(self, "_workspace_root", None))

    def _target_dir(self) -> Path | None:
        """The validated, confined write target, or ``None`` when unsafe.

        Review M1: ``report_dir`` arrives from YAML unvalidated; an empty,
        ``.``, absolute or ``..``-escaping value would otherwise write (and
        let retention prune) somewhere far wider than intended. Delegates
        the actual check to :func:`resolve_confined_report_dir` so the
        persister and any future caller share one definition of "safe".
        """
        return resolve_confined_report_dir(self._root(), self._report_dir)

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

        target_dir = self._target_dir()
        if target_dir is None:
            _LOGGER.warning(
                "subagent_report_persistence: report_dir %r is empty, '.', "
                "absolute or escapes the project root -- skipping persistence",
                self._report_dir,
            )
            return BlockingResult(decision=Decision.ALLOW)

        agent_type = hook_input.get(HookInputField.AGENT_TYPE)
        agent_id = hook_input.get(HookInputField.AGENT_ID)
        filename = report_filename(
            agent_type if isinstance(agent_type, str) else "",
            agent_id if isinstance(agent_id, str) else "",
            when=datetime.now(UTC),
        )
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
            "At every SubagentStop, including a re-entry, the daemon saves the "
            "stopping agent's final message to a file under "
            f"`{DEFAULT_PERSISTED_REPORT_DIR}` "
            "(`<yymmdd>-<HHMMSS>-<agent_type>-<agent_id>.md`), regardless of "
            "agent type or `Write` access — so persistence never depends on "
            "the agent's own cooperation. That directory is exclusively the "
            "daemon's own: never the shared `untracked/agent-reports/` a "
            "coordinator may separately declare as a hand-authored, non-plan "
            "report destination.\n\n"
            "Genuinely gitignored, not just conventionally so: a `*` "
            "`.gitignore` is written into the directory the first time it is "
            "created, so the guarantee holds even in a project whose own "
            "ignore rules do not mention it. The content itself is NOT "
            "vetted — no sensitive-content, secret-file or markdown-location "
            "check runs, only kept out of git's view.\n\n"
            "Never overwrites (a collision gets a numeric suffix); pruned to "
            "a configured cap (default 500 files / 30 days, "
            "`options.max_kept_reports` / `options.max_report_age_days`) "
            "after every write — pruning only ever touches this directory, "
            "never a hand-authored report elsewhere. Never blocks a stop — "
            "persistence failing, or an unsafe `report_dir`, is logged, not "
            "fatal.\n\n"
            "`subagent_report_size_blocker` looks up what this handler already "
            "saved (by agent type/id AND matching content, not an exact "
            "filename) and points an over-threshold agent at that path "
            "instead of asking it to write one itself."
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for the subagent report persistence handler."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Subagent stop persists the final reply to a gitignored file",
                command="Dispatch any subagent and let it finish with a short reply",
                description=(
                    f"Every SubagentStop saves last_assistant_message to "
                    f"{DEFAULT_PERSISTED_REPORT_DIR}, whether or not the reply is "
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
