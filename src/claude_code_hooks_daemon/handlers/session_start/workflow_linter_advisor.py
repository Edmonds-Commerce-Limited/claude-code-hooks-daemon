"""WorkflowLinterAdvisorHandler - suggest the GitHub workflow linter (Plan 00621 Task 2.2).

``lint_on_edit`` runs ``actions-qa`` (the ``LongTermSupport/actions-qa-ci``
project) on a written workflow file, but only where the linter is installed,
and it says nothing when it is not: a line on every workflow edit in every
project that has not adopted the linter would be noise. This advisory is the
one place the linter is suggested.

It speaks at a new session (not a resume) when ``<root>/.github/workflows/``
holds at least one ``.yml``/``.yaml`` file and no such file has a ``uses:``
line naming ``actions-qa-ci``. It never runs the linter, never blocks, and
prints no install command: it links the release page. A workflow file it cannot
read is named in the advisory and never counts as using the linter.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

logger = logging.getLogger(__name__)

_PROJECT: Final = "actions-qa-ci"
RELEASES_URL: Final = f"https://github.com/LongTermSupport/{_PROJECT}/releases"
_WORKFLOWS_RELATIVE: Final = Path(".github") / "workflows"
_WORKFLOW_SUFFIXES: Final[frozenset[str]] = frozenset({".yml", ".yaml"})

#: A ``uses:`` key (a step's, optionally list-item form, or a job's reusable
#: workflow) whose value names the linter. Anchored at the line start so a
#: comment or a ``run:`` line mentioning the name does not count as adoption.
_USES_LINTER: Final = re.compile(
    r"^\s*(?:-\s+)?uses:\s*['\"]?[^\s'\"#]*" + re.escape(_PROJECT),
    re.MULTILINE,
)


class WorkflowLinterAdvisorHandler(SessionStartHandlerBase):
    """Suggest actions-qa-ci when a project has workflows and none uses it."""

    def __init__(self) -> None:
        """Initialise as a non-terminal, silent-when-not-applicable advisory."""
        super().__init__(
            handler_id=HandlerID.WORKFLOW_LINTER_ADVISOR,
            priority=Priority.WORKFLOW_LINTER_ADVISOR,
            terminal=False,
            tags=[HandlerTag.ADVISORY, HandlerTag.GITHUB, HandlerTag.NON_TERMINAL],
        )
        #: Set in tests so the scan needs no initialised ProjectContext.
        self.workspace_root: Path | None = None

    def _project_root(self) -> Path | None:
        """The project root, or None when the daemon has not initialised one."""
        if self.workspace_root is not None:
            return self.workspace_root
        if not ProjectContext.is_initialized():
            return None
        return ProjectContext.project_root()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Once per session: a new session only, never a resume."""
        return not is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Suggest the linter when workflows exist and none uses it; nothing otherwise."""
        root = self._project_root()
        if root is None:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])
        directory = root / _WORKFLOWS_RELATIVE
        if not directory.is_dir():
            return AdvisoryResult(decision=Decision.ALLOW, context=[])
        try:
            workflows = sorted(
                entry
                for entry in directory.iterdir()
                if entry.suffix in _WORKFLOW_SUFFIXES and entry.is_file()
            )
        except OSError as error:
            logger.warning("workflow_linter_advisor: cannot list %s: %s", directory, error)
            return AdvisoryResult(
                decision=Decision.ALLOW,
                context=[
                    f"Workflow linter check: {_WORKFLOWS_RELATIVE} could not be listed "
                    f"({error}), so whether a workflow uses {_PROJECT} is unknown."
                ],
            )
        if not workflows:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        unreadable: list[str] = []
        for workflow in workflows:
            try:
                text = workflow.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                logger.warning("workflow_linter_advisor: cannot read %s: %s", workflow, error)
                unreadable.append(f"{workflow.name} ({type(error).__name__})")
                continue
            if _USES_LINTER.search(text):
                return AdvisoryResult(decision=Decision.ALLOW, context=[])

        return AdvisoryResult(decision=Decision.ALLOW, context=_advice(len(workflows), unreadable))

    def get_acceptance_tests(self) -> list[Any]:
        """One CONTEXT case: a project with workflows and no linter gets the suggestion."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="workflow linter advisor - suggests actions-qa-ci for unlinted workflows",
                command='echo "test"',
                description=(
                    "In a project whose .github/workflows/ holds a workflow and none "
                    "uses actions-qa-ci, a new session start names the linter, what it "
                    "checks and its release page. Silent with no workflows, when one "
                    "already uses it, and on resume."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"actions-qa-ci"],
                safety_notes="Advisory only - never runs the linter or blocks.",
                test_type=TestType.CONTEXT,
                recommended_model=RecommendedModel.HAIKU,
                requires_event="SessionStart event (new session only)",
                requires_main_thread=False,
            ),
        ]

    def get_claude_md(self) -> str | None:
        """No resident guidance: the advisory carries its own text when it fires."""
        return None


def _advice(workflow_count: int, unreadable: list[str]) -> list[str]:
    """The advisory lines: the tool, what it checks, where to get it, unread files."""
    lines = [
        f"GitHub workflow linter: {workflow_count} workflow file(s) in "
        f"{_WORKFLOWS_RELATIVE}/ and none uses {_PROJECT}.",
        f"{_PROJECT} (executable `actions-qa`) checks workflows for costly CI patterns "
        "(docs-only pushes, missing push concurrency, workflow_run fan-out, schedule "
        "budget) on top of actionlint.",
        f"Once `actions-qa` is on PATH, every workflow edit is linted. Releases: {RELEASES_URL}",
    ]
    if unreadable:
        lines.append(
            "These workflow files could not be read, so whether they use it is unknown: "
            + ", ".join(unreadable)
        )
    return lines
