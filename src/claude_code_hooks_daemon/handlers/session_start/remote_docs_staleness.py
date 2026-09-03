"""SessionStart staleness report for the vendored remote-docs tree.

Plan 00326 Task 4.3. A ``stale_after`` date sitting in a file nobody opens
changes nothing; this is the surface that delivers it without anyone running
a command.

It ADVISES and never blocks (D7). Staleness is a judgement a human may
knowingly accept -- an upstream that has not changed in a year is not a
problem, and a pinned archival snapshot is stale on purpose. Absent
provenance is a different thing entirely: a fact, checkable offline, which
is the write-time gate's job rather than this one's.

The report walks the tree directly rather than through the docs-QA corpus,
because D12's top-level tree is deliberately outside corpus scope and
``store.check_staleness`` already parses exactly what is reported here.
"""

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision, ProjectContext
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

_SOURCE_FIELD: Final[str] = "source"
_SOURCE_STARTUP: Final[str] = "startup"
_FALLBACK_REMOTE_DOCS_DIR: Final[str] = "remote-docs"
# A corpus can be large and this is one advisory among several at session
# start. Naming a bounded sample plus a total says the same thing without
# pushing everything else out of view.
_MAX_LISTED: Final[int] = 10


class RemoteDocsStalenessHandler(SessionStartHandlerBase):
    """Report vendored documents that are stale or no longer parse."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.REMOTE_DOCS_STALENESS,
            priority=Priority.REMOTE_DOCS_STALENESS,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )
        self.config: dict[str, Any] = {"enabled": True}
        # Injection points for tests; production resolves both for real.
        self.tree_reader: Callable[[], Path] = self._resolve_tree
        self.today_reader: Callable[[], date] = date.today

    def configure(self, config: dict[str, Any]) -> None:
        """Apply configuration."""
        self.config.update(config)

    def _resolve_tree(self) -> Path:
        """Absolute path of the configured remote-docs tree."""
        layout = self._project_layout
        name = layout.remote_docs_dir if layout is not None else _FALLBACK_REMOTE_DOCS_DIR
        return ProjectContext.project_root() / name

    def matches(self, hook_input: dict[str, Any] | None) -> bool:
        """Run on NEW SessionStart events only (never on resume)."""
        if not hook_input or not isinstance(hook_input, dict):
            return False
        if not self.config.get("enabled", True):
            return False
        if hook_input.get(HookInputField.HOOK_EVENT_NAME) != "SessionStart":
            return False
        source = hook_input.get(_SOURCE_FIELD)
        if isinstance(source, str):
            return source == _SOURCE_STARTUP
        return not is_resume_session(hook_input)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        """Report the documents needing attention, or stay silent."""
        from claude_code_hooks_daemon.remote_docs.store import check_staleness

        tree = self.tree_reader()
        if not tree.is_dir():
            # Most projects vendor nothing. They must never see this handler.
            return AdvisoryResult(decision=Decision.ALLOW, reason=None, context=[])

        needing_attention = check_staleness(tree, today=self.today_reader())
        if not needing_attention:
            return AdvisoryResult(decision=Decision.ALLOW, reason=None, context=[])

        return AdvisoryResult(
            decision=Decision.ALLOW,
            reason=None,
            context=self._report(tree, needing_attention),
        )

    def _report(self, tree: Path, documents: list[Any]) -> list[str]:
        """The advisory lines, bounded in length."""
        total = len(documents)
        lines = [
            f"📄 REMOTE DOCS: {total} vendored document(s) need attention",
            "",
        ]
        for document in documents[:_MAX_LISTED]:
            lines.append(f"  • {self._describe(tree, document)}")
        if total > _MAX_LISTED:
            lines.append(f"  … and {total - _MAX_LISTED} more")
        lines.extend(
            [
                "",
                "Refresh one, or the whole tree:",
                "  bin/hooks-daemon remote-docs refresh --path <file>",
                "  bin/hooks-daemon remote-docs refresh --all",
                "",
                "Staleness is advisory: an upstream that has not changed is not a "
                "problem, and a pinned snapshot is stale on purpose.",
            ]
        )
        return lines

    def _describe(self, tree: Path, document: Any) -> str:
        """One line per document: the path, and why it is listed."""
        try:
            shown = document.path.relative_to(tree)
        except ValueError:
            shown = document.path

        if document.provenance is None:
            return f"{shown} — provenance does not parse"
        return f"{shown} — stale since {document.provenance.stale_after}"

    def get_claude_md(self) -> str | None:
        """No resident guidance: the report carries its own next step."""
        return None

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests rendered into the release playbook."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="remote-docs staleness report",
                command="Start a new session in a project with a stale vendored document",
                description=(
                    "SessionStart reports the stale document and names the "
                    "refresh command, without blocking the session"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"REMOTE DOCS", r"remote-docs refresh"],
                safety_notes="Read-only walk of the vendored tree",
                test_type=TestType.ADVISORY,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
