"""The remote-docs commit gate (Plan 00326).

``remote_docs_provenance`` keys on ``Write``/``Edit``, so a Bash heredoc or
redirect into the tree reaches disk unexamined. That hole is real and is
recorded as BLIND in this project's bash-write-blindness register. This is
the backstop: however a file reached disk, it cannot be COMMITTED without
provenance.

The session-start sweep also reports such a file, but later and only as a
notice. Stopping it at the commit matters more, because an unattributed
document that reaches history needs a rewrite to remove -- and a vendored
document with no recorded source is indistinguishable from something we
wrote ourselves.

Deletions are never blocked. Removing a bad document must not be harder
than adding one.
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority, ToolName
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.core.utils import get_bash_command
from claude_code_hooks_daemon.utils.git_commit_parsing import is_git_commit, tokenise_command

logger = logging.getLogger(__name__)

_MARKDOWN_SUFFIX: Final[str] = ".md"
_FALLBACK_REMOTE_DOCS_DIR: Final[str] = "remote-docs"
# Added, Copied, Modified: a Deleted path is not a document being introduced.
_DIFF_FILTER: Final[str] = "ACM"

_RULE_STAGED_PROVENANCE: Final[Rule] = Rule(
    rule_id=RuleID.REMOTE_DOCS_STAGED_PROVENANCE,
    blocked="a commit staging a remote-docs file without valid provenance frontmatter",
    why=(
        "An unattributed vendored document that reaches history needs a rewrite "
        "to remove, and cannot be refreshed, dated or trusted meanwhile"
    ),
    fix="Capture with `hooks-daemon remote-docs add <url>` and re-stage",
    verbose=(
        "The write-time gate (`remote_docs_provenance`) inspects `Write` and "
        "`Edit`. A file authored through Bash -- a heredoc, `>`, `>>`, `tee` "
        "-- never reaches it, so this gate checks the INDEX instead: whatever "
        "route a file took to disk, it cannot be committed without saying "
        "where it came from.\n\n"
        "Every offending file is named at once rather than one per retry, so "
        "a bulk import is one fix rather than a slog.\n\n"
        "Capture properly instead of hand-authoring:\n"
        "  bin/hooks-daemon remote-docs add <url>\n\n"
        "Deleting a vendored document is never blocked -- removing a bad one "
        "must not be harder than adding it."
    ),
)


class RemoteDocsCommitGateHandler(PreToolUseHandlerBase):
    """Deny a commit that would enter an unattributed vendored document."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.REMOTE_DOCS_COMMIT_GATE,
            priority=Priority.REMOTE_DOCS_COMMIT_GATE,
            tags=[HandlerTag.WORKFLOW, HandlerTag.BLOCKING, HandlerTag.TERMINAL],
        )
        # Injection points for tests; production reads the real index.
        self.project_root_reader: Callable[[], Path] = ProjectContext.project_root
        self.staged_reader: Callable[[], list[str]] = self._read_staged

    def _read_staged(self) -> list[str]:
        """Repository-relative paths added/copied/modified in the index."""
        from claude_code_hooks_daemon.utils.git_repo import run_git

        result = run_git(
            self.project_root_reader(),
            "diff",
            "--cached",
            "--name-only",
            f"--diff-filter={_DIFF_FILTER}",
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def _tree_name(self) -> str:
        layout = self._project_layout
        return layout.remote_docs_dir if layout is not None else _FALLBACK_REMOTE_DOCS_DIR

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """True for a git commit; the staged contents decide the verdict."""
        if hook_input.get("tool_name") != ToolName.BASH:
            return False
        command = get_bash_command(hook_input)
        if not command:
            return False
        return is_git_commit(tokenise_command(command))

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny when a staged remote-docs file lacks valid provenance."""
        from claude_code_hooks_daemon.remote_docs.provenance import parse_provenance

        try:
            staged = self.staged_reader()
            project_root = self.project_root_reader()
        except OSError as exc:
            # A gate that cannot read the index must not block every commit.
            logger.debug("remote-docs commit gate could not read the index: %s", exc)
            return GatingResult(decision=Decision.ALLOW)

        prefix = self._tree_name().strip("/") + "/"
        offenders: list[tuple[str, str]] = []

        for relpath in staged:
            if not relpath.startswith(prefix) or not relpath.endswith(_MARKDOWN_SUFFIX):
                continue
            path = project_root / relpath
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                # Staged-but-absent (a race, or a path we cannot decode) is
                # not evidence of a missing source; say nothing about it.
                logger.debug("remote-docs commit gate skipped %s: %s", relpath, exc)
                continue
            result = parse_provenance(content)
            if result.provenance is not None:
                continue
            problems = "; ".join(f"{error.field}: {error.message}" for error in result.errors)
            offenders.append((relpath, problems or "no provenance frontmatter"))

        if not offenders:
            return GatingResult(decision=Decision.ALLOW)

        listing = "\n".join(f"  - {path}\n      {problem}" for path, problem in offenders)
        return GatingResult(
            decision=Decision.DENY,
            reason=(
                "REMOTE-DOCS PROVENANCE MISSING IN THE STAGED TREE\n\n"
                "These staged files are in the vendored remote-docs tree but do "
                "not say where they came from:\n\n"
                f"{listing}\n\n"
                "A file authored through Bash never reaches the write-time gate, "
                "which is why this one checks the index.\n\n"
                "This tree is CAPTURED, not authored:\n"
                "  bin/hooks-daemon remote-docs add <url>\n\n"
                "Then re-stage. Deleting a vendored document is never blocked."
            ),
        )

    def get_rules(self) -> list[Rule]:
        """The Rule backing this handler's denial."""
        return [_RULE_STAGED_PROVENANCE]

    def get_claude_md(self) -> str | None:
        """No resident guidance: the write-time gate's section covers this."""
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
                title="remote-docs staged provenance gate",
                command=(
                    "Write remote-docs/example.com/p.md via a Bash heredoc, "
                    "git add it, then git commit"
                ),
                description=(
                    "The commit is denied, naming the file and the capture "
                    "command — closing the Bash-write route around the "
                    "write-time gate"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"STAGED TREE", r"remote-docs add"],
                safety_notes="Nothing is written; the index is read only",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="remote-docs staged gate near-miss",
                command="git commit with a properly captured vendored document staged",
                description=(
                    "A document with valid provenance commits normally; the "
                    "gate only fires on a missing or invalid record"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Read-only inspection of the staged tree",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
