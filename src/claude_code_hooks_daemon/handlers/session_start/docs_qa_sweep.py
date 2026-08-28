"""DocsQaSweepHandler — whole-corpus docs QA sweep at session start (Plan 00284).

Rebuilds/refreshes the doc corpus index and runs the SWEEP-stage docs QA
check catalogue against it, injecting ONE compact advisory. Silent when
the corpus is clean; new sessions only (a resumed session already saw the
report).

This is the explicit-build half of the cold-index rule (DESIGN §2.1): the
corpus is built/refreshed HERE, at SessionStart — never lazily inside a
PreToolUse budget (``docs_qa_edit`` never touches the corpus at all). The
persisted index lets any later cheap consumer read a warm cache instead of
rescanning the filesystem.

Policy comes from ``documentation`` via the registry's DOCUMENTATION-tag
injection (``_documentation``) — zero per-handler options.
"""

from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import AdvisoryResult, Decision
from claude_code_hooks_daemon.core.handler_bases import SessionStartHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.docs_qa.context import sweep_context
from claude_code_hooks_daemon.docs_qa.corpus import build_and_save_corpus
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.report import format_advisory
from claude_code_hooks_daemon.docs_qa.runner import run_stage
from claude_code_hooks_daemon.docs_qa.types import CheckStage
from claude_code_hooks_daemon.utils.cli_command import (
    daemon_cli_command,
    daemon_cli_command_for_docs,
)
from claude_code_hooks_daemon.utils.session_helpers import is_resume_session

_SWEEP_MODE_ADVISE: Final[str] = "advise"
_INDEX_DIR_NAME: Final[str] = "docs-qa"
_INDEX_FILE_NAME: Final[str] = "index.json"


def _cli_hint() -> str:
    """Re-check directive naming the deployed wrapper (mirrors plan_qa_sweep)."""
    return "Full report / re-check after fixing: " + daemon_cli_command("docs-qa", "--sweep")


class DocsQaSweepHandler(SessionStartHandlerBase):
    """Advisory SessionStart sweep over the documentation corpus (silent when clean)."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DOCS_QA_SWEEP,
            priority=Priority.DOCS_QA_SWEEP,
            terminal=False,
            tags=[
                HandlerTag.ADVISORY,
                HandlerTag.DOCUMENTATION,
                HandlerTag.NON_TERMINAL,
            ],
        )
        # Injected by the registry for DOCUMENTATION-tagged handlers.
        self._documentation: DocumentationPolicy | None = None

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if is_resume_session(hook_input):
            return False
        policy = self._documentation
        if policy is None or not policy.enabled:
            return False
        return bool(policy.qa.sweep_mode == _SWEEP_MODE_ADVISE)

    def handle(self, hook_input: dict[str, Any]) -> AdvisoryResult:
        policy = self._documentation
        if policy is None:  # pragma: no cover - matches() gates this
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        project_root = ProjectContext.project_root()
        index_path = ProjectContext.daemon_untracked_dir() / _INDEX_DIR_NAME / _INDEX_FILE_NAME
        corpus = build_and_save_corpus(project_root, policy, index_path)
        context = sweep_context(project_root=project_root, policy=policy, corpus=corpus)

        findings = run_stage(CheckStage.SWEEP, context)
        if not findings:
            return AdvisoryResult(decision=Decision.ALLOW, context=[])

        return AdvisoryResult(
            decision=Decision.ALLOW,
            context=[format_advisory(findings), "", _cli_hint()],
        )

    def get_claude_md(self) -> str | None:
        return (
            "## docs_qa_sweep — documentation drift report at session start\n"
            "\n"
            "At the start of each new session the doc corpus index is rebuilt\n"
            "(link graph over the two audience trees, `.claude/rules`,\n"
            "`.claude/skills`, `.claude/agents`, and root-level `.md` files) and\n"
            "checked with the docs QA SWEEP-stage catalogue: `pointer-resolves`\n"
            "(dead links), `generated-doc-hand-edit` (a generated doc that looks\n"
            "hand-edited or stale against the daemon's own version),\n"
            "`rules-file-shape` (a `.claude/rules/*.md` file violating the\n"
            "pointer-only contract), and `quote-drift` (an `ssot-quote` block\n"
            "whose body no longer matches its source section, or whose source\n"
            "file/anchor has disappeared — re-verified fresh from disk every\n"
            "sweep, so this is the backstop for `quote-source-stale`, which only\n"
            "advises at edit time). Findings are injected once as advisory\n"
            "context — the sweep never blocks.\n"
            "\n"
            "**When a drift report appears**: fix the listed findings (each names\n"
            "its exact remediation) as part of your documentation housekeeping,\n"
            "then re-check with:\n"
            "\n"
            "```\n"
            f"{daemon_cli_command_for_docs('docs-qa', '--sweep')}\n"
            "```\n"
            "\n"
            "The CLI exits 1 while findings remain (CI-able). Single-file lint:\n"
            "`docs-qa --lint <file>`. Policy lives under `documentation.qa` in\n"
            "`.claude/hooks-daemon.yaml` (modes, per-check overrides, grandfather\n"
            "allowlist, generated-docs manifest)."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="docs-qa sweep - session start drift report",
                command='echo "session start"',
                description=(
                    "On a NEW session in a project with documentation QA enabled "
                    "and doc drift present, the SessionStart context contains a "
                    "'Docs QA drift report' block naming check ids and "
                    "remediations. On a clean corpus the handler stays silent."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"Docs QA drift report|docs-qa --sweep"],
                safety_notes="Advisory handler - never blocks",
                test_type=TestType.CONTEXT,
                requires_event="SessionStart event (new session only)",
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
