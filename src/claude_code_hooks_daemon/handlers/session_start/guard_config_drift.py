"""GuardConfigDriftHandler — report a working-tree config that weakens the guards.

Plan 00412 class 2, `guard-self-disablement-unwatched`. F-GAP probed the routes
that switch a guard off -- `Edit`, `Write`, a Bash redirect, `cp`, `mv`,
`chmod 000`, `config set ... enabled false`, `stop`, `rm -rf` -- across four
files, and every result was `NOTHING DENIES`. The compounding property is that
every deny message prints the config key that disables the guard which just
fired, so the route is not merely open, it is advertised.

**This handler does not close that route, and is not trying to.** F-GAP's
judgement, which this follows, is that a PreToolUse deny on config writes is
owner-gated AND circular: an agent that can edit the config can edit the rule
guarding it. The non-circular remedies are a commit-time gate and this drift
report. What it buys is that a weakening stops being SILENT: it is named at the
top of the next session, before any advisory whose value depends on the guards
being live.

Silent when the config matches its committed form, which is almost always (Lean
SessionStart, Plan 00128). Also silent -- deliberately -- when there is no
committed config, when either document cannot be read, and when either cannot be
parsed. Each of those is a state this handler cannot interpret, and an advisory
that fires wrongly every session is one that gets switched off, which would be
the finding eating itself.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.git_repo import run_git
from claude_code_hooks_daemon.utils.guard_config_drift import (
    DriftReport,
    compare_guard_config,
)

logger = logging.getLogger(__name__)

_CONFIG_RELATIVE_PATH: Final[str] = ".claude/hooks-daemon.yaml"
_HEAD_REF: Final[str] = f"HEAD:{_CONFIG_RELATIVE_PATH}"


@dataclass(frozen=True)
class _ReadAttempt:
    """A file's text, or the reason there is none.

    Two outcomes that both used to be a bare ``None``: the file is absent, and
    the file is there but could not be read. Keeping the reason on the value
    means a silent session is explainable afterwards, which a discarded
    exception never is.
    """

    text: str | None = None
    reason: str | None = None


def _read_text_or_reason(path: Path) -> _ReadAttempt:
    """Read ``path``, carrying any failure back as a reason rather than raising."""
    try:
        return _ReadAttempt(text=path.read_text(encoding="utf-8"))
    except OSError as exc:
        logger.debug("guard_config_drift: %s unreadable: %s", path, exc)
        return _ReadAttempt(reason=str(exc))


class GuardConfigDriftHandler(SessionStartHandlerBase):
    """Name any uncommitted change that weakens this project's guards."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.GUARD_CONFIG_DRIFT,
            priority=Priority.GUARD_CONFIG_DRIFT,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.SAFETY,
                HandlerTag.NON_TERMINAL,
                HandlerTag.ENVIRONMENT,
            ],
        )
        #: Injected in tests so the comparison needs no git and no filesystem.
        self.committed_reader: Callable[[], str | None] = self._read_committed
        self.working_reader: Callable[[], str | None] = self._read_working

    @staticmethod
    def _project_root() -> Path | None:
        """The project root, or None when the daemon has not initialised one.

        ASKS rather than catches. ``project_root()`` raises when the context is
        not set up, and catching that to return None makes an ordinary,
        expected state look like a failure -- so the state is queried directly
        and no exception is involved.
        """
        if not ProjectContext.is_initialized():
            logger.debug("guard_config_drift: ProjectContext not initialised")
            return None
        return ProjectContext.project_root()

    def _read_committed(self) -> str | None:
        """The config as git has it, or None when there is nothing to compare."""
        root = self._project_root()
        if root is None:
            return None
        result = run_git(root, "show", _HEAD_REF)
        if result.returncode != 0:
            # Not a repo, no commits yet, or the config is untracked. All three
            # mean "no baseline", which is not the same as "no drift" and is
            # reported as neither.
            logger.debug("guard_config_drift: no committed config to compare against")
            return None
        return result.stdout

    def _read_working(self) -> str | None:
        """The config the daemon loaded, or None when it cannot be read.

        An unreadable config is reported as unavailable rather than raised: this
        runs at session start, and a handler that throws there costs the whole
        SessionStart response. The reason is carried on the returned value
        instead of being discarded, so "absent" and "unreadable" stay distinct
        to anyone debugging a silent session.
        """
        root = self._project_root()
        if root is None:
            return None
        return _read_text_or_reason(root / _CONFIG_RELATIVE_PATH).text

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Every session start, including resumes.

        A resumed session loads the same config a new one would, so exempting
        resumes would leave the weakening unreported for exactly as long as the
        session lasts -- which is the period that matters.
        """
        return True

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        committed = self.committed_reader()
        working = self.working_reader()
        if committed is None or working is None:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        report = compare_guard_config(committed, working)
        return AdvisoryResult(decision=Decision.ALLOW, context=_render(report))

    def get_claude_md(self) -> str | None:
        return None

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="guard config drift - reports an uncommitted guard weakening",
                command='echo "test"',
                description=(
                    "Tests that a working-tree hooks-daemon.yaml which disables a "
                    "handler, removes its block, or widens an exclusion relative to "
                    "the committed config is named at session start. Silent when the "
                    "two agree."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"GUARD CONFIG DRIFT|uncommitted"],
                safety_notes="Advisory handler - reports but never blocks",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]


def _render(report: DriftReport) -> list[str]:
    """The advisory text, or nothing at all when the config is unchanged."""
    if not report.has_drift:
        return []

    lines: list[str] = [
        "GUARD CONFIG DRIFT: the hooks-daemon config the daemon loaded differs "
        "from the committed one.",
        "",
    ]

    if report.guard_changes:
        lines.append(
            "These changes WEAKEN a guard, and are not in the committed config — "
            "so no review saw them:"
        )
        lines.append("")
        lines += [f"  - {change}" for change in report.guard_changes]
        lines.append("")

    if report.other_changes:
        # Named separately rather than folded in: these are differences the
        # enumerated kinds did not match, and saying so is the honest form.
        # Class 6 -- a weakening can always be spelled a way this rule does not
        # know, so the count must not read as "nothing else changed".
        lines.append(
            f"A further {report.other_changes} config difference(s) are not "
            "recognised as a weakening. That is not a claim they are harmless — "
            "only that this check cannot name them."
        )
        lines.append("")

    lines.append(
        "If the change is intended, commit it so it is reviewable. If it is not, "
        f"restore it: git checkout HEAD -- {_CONFIG_RELATIVE_PATH}"
    )
    return lines
