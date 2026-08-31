"""DocsQaEditHandler — EDIT-stage docs QA lint at Write/Edit time (Plan 00284).

Runs the EDIT-stage docs QA checks against the WOULD-BE content of a
documentation-scoped file: for Write that is the payload itself; for Edit
the old/new replacement is applied to the current file first. A finding is
only denied when it is BLOCK severity AND the resolved mode for its check
id (``check_modes`` override, falling back to ``qa.edit_mode``) is
``block`` — the structural block-eligibility rule (DESIGN §2.2): a check
that decided ADVISE for THIS finding (grandfathered, unchanged-but-
violating, a SWEEP-only signal) can never be escalated by mode alone.

Scope is the union docs_qa recognises for EDIT-stage checking: the doc
corpus's own scope (the two audience trees, ``.claude/rules``,
``.claude/skills``, ``.claude/agents``, root-level ``.md``), OR a path
declared in the generated-docs manifest — the manifest may legitimately
name a path outside the corpus scope (``.claude/HOOKS-DAEMON.md`` is
exactly this case, see ``docs_qa.checks.generated_doc_hand_edit``) — OR any
module-scoped ``CLAUDE.md`` (:func:`docs_qa.corpus.is_module_doc_path`).
That third arm is deliberately WIDER than the corpus scope: a file like
``src/CLAUDE.md`` or ``.claude/ccy/CLAUDE.md`` sits outside every tree the
corpus tracks, yet is exactly what ``module-doc-budget`` exists to police
(RULESET section 2) — without this arm the check would be permanently
unreachable at EDIT time for the very files it targets, catching drift
only retrospectively at the next SWEEP.

Deliberately hot-path cheap: the primary checks (``pointer-resolves``,
``generated-doc-hand-edit``, ``rules-file-shape``, ``quote-drift``) need no
corpus and no git subprocess — single-file invariants only. One check,
``quote-source-stale``, DOES need the corpus's reverse quote index, so this
handler loads (never BUILDS) the cached corpus via
:func:`docs_qa.corpus.load_or_cold_corpus` — one cheap JSON read, not a
filesystem scan (the cold-index rule: building is SessionStart/CLI-only).
If no cache exists yet (a session before the sweep has run), the corpus is
``cold`` and ``quote-source-stale`` degrades to silence — never a false
positive, never a crash. Not yet covering a Bash-authored ``.md`` write
(the same detection ``lint_on_edit`` uses) — deferred; Write/Edit is the
primary surface for this slice.
"""

from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, HookInputField, Priority
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.docs_qa.context import edit_context
from claude_code_hooks_daemon.docs_qa.corpus import (
    is_lintable_path,
    load_or_cold_corpus,
    refresh_own_record,
)
from claude_code_hooks_daemon.docs_qa.policy import DocumentationPolicy
from claude_code_hooks_daemon.docs_qa.report import format_advisory, format_block_reason
from claude_code_hooks_daemon.docs_qa.runner import run_stage
from claude_code_hooks_daemon.docs_qa.types import CheckStage, Finding, Severity
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs

_MODE_BLOCK: Final[str] = "block"

# Single source of truth for the one rule this handler's DENY path enforces
# (Plan 00116, gate-level granularity: one Rule per GATE, not one per docs QA
# check). The per-check findings from format_block_reason() are dynamic
# content and stay FULLY present in both verbose and terse forms; only the
# surrounding teaching prose about the gate itself goes terse-after-first-fire.
_RULE_WHY = (
    "A finding only denies the write when it is BLOCK severity AND the "
    "resolved mode for that check is block"
)
_RULE_FIX = "Fix the content per each finding's remediation below and retry"
_RULE_VERBOSE = (
    "Every Write/Edit of a documentation-scoped file is checked against the "
    "docs QA EDIT-stage catalogue on the content the file WOULD have. Each "
    "finding below names its own remediation -- fix the content accordingly "
    "and retry. An ADVISE-severity finding, or a BLOCK finding under a "
    "warn-mode check, surfaces as advisory context instead and never denies."
)

_FIELD_FILE_PATH: Final[str] = "file_path"
_FIELD_CONTENT: Final[str] = "content"
_FIELD_OLD_STRING: Final[str] = "old_string"
_FIELD_NEW_STRING: Final[str] = "new_string"
_FIELD_REPLACE_ALL: Final[str] = "replace_all"

_INDEX_DIR_NAME: Final[str] = "docs-qa"
_INDEX_FILE_NAME: Final[str] = "index.json"

_SINGLE_REPLACEMENT: Final[int] = 1


class DocsQaEditHandler(PreToolUseHandlerBase):
    """Blocking/advisory EDIT-time lint for documentation-scoped files."""

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.DOCS_QA_EDIT,
            priority=Priority.DOCS_QA_EDIT,
            terminal=False,
            tags=[
                HandlerTag.DOCUMENTATION,
                HandlerTag.VALIDATION,
                HandlerTag.CONTENT_QUALITY,
            ],
        )
        # Injected by the registry for DOCUMENTATION-tagged handlers.
        self._documentation: DocumentationPolicy | None = None
        self._rule = Rule(
            rule_id=RuleID.DOCS_QA_EDIT,
            blocked="a documentation Write/Edit violates a block-level docs QA check",
            why=_RULE_WHY,
            fix=_RULE_FIX,
            verbose=_RULE_VERBOSE,
        )
        self._formatter = RuleFormatter()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        if hook_input.get(HookInputField.TOOL_NAME) not in (ToolName.WRITE, ToolName.EDIT):
            return False
        policy = self._documentation
        if policy is None or not policy.enabled:
            return False

        file_path_raw = hook_input.get(HookInputField.TOOL_INPUT, {}).get(_FIELD_FILE_PATH, "")
        if not file_path_raw:
            return False
        project_root = ProjectContext.project_root()
        file_path = Path(file_path_raw)
        rel_path = self._rel_path(file_path, project_root)
        if rel_path is None:
            return False
        return is_lintable_path(rel_path, file_path, project_root, policy)

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        project_root = ProjectContext.project_root()
        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        file_path = Path(tool_input.get(_FIELD_FILE_PATH, ""))
        exists_before = file_path.is_file()

        content = self._would_be_content(hook_input, file_path, exists_before)
        if content is None:
            # Edit on a missing file / unmatched old_string: the tool call
            # itself will fail with its own error — nothing to lint.
            return GatingResult(decision=Decision.ALLOW, context=[])

        policy = self._documentation
        assert policy is not None  # matches() only returns True when this is set

        content_before = file_path.read_text(encoding="utf-8") if exists_before else None
        index_path = ProjectContext.daemon_untracked_dir() / _INDEX_DIR_NAME / _INDEX_FILE_NAME
        corpus = load_or_cold_corpus(project_root, index_path)
        # Task 3.5: the cache read above performs NO staleness check, so
        # without this the edited file's own record can lag the WOULD-BE
        # content -- refresh it in place before any cross-document check runs.
        corpus = refresh_own_record(corpus, project_root, file_path, content)
        context = edit_context(
            project_root=project_root,
            policy=policy,
            file_path=file_path,
            file_content=content,
            file_exists_before=exists_before,
            file_content_before=content_before,
            corpus=corpus,
        )
        findings = run_stage(CheckStage.EDIT, context)
        if not findings:
            return GatingResult(decision=Decision.ALLOW, context=[])

        blockers = [finding for finding in findings if self._is_deny_eligible(finding)]
        if blockers:
            return GatingResult(
                decision=Decision.DENY,
                reason=self._blocking_message(blockers, hook_input),
            )
        return GatingResult(decision=Decision.ALLOW, context=[format_advisory(findings)])

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's block-eligible denial."""
        return [self._rule]

    def _blocking_message(self, blockers: list[Finding], hook_input: dict[str, Any]) -> str:
        """Build the deny message: verbose-first/terse-after teaching prose
        (Plan 00116, Decision G), with the per-check findings from
        ``format_block_reason`` ALWAYS fully present -- they are dynamic
        content, not the static teaching text the disclosure ladder governs.
        """
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, RuleID.DOCS_QA_EDIT):
            prose = self._formatter.terse(self._rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, RuleID.DOCS_QA_EDIT)
            prose = self._formatter.verbose(self._rule)

        return f"{prose}\n\n{format_block_reason(blockers)}"

    def _is_deny_eligible(self, finding: Finding) -> bool:
        """BLOCK severity AND the resolved mode for this check id is block."""
        if finding.severity != Severity.BLOCK:
            return False
        policy = self._documentation
        assert policy is not None  # handle() only runs after matches() confirmed this
        resolved_mode = policy.qa.check_modes.get(finding.check_id, policy.qa.edit_mode)
        return resolved_mode == _MODE_BLOCK

    @staticmethod
    def _rel_path(file_path: Path, project_root: Path) -> str | None:
        try:
            return str(file_path.resolve().relative_to(project_root.resolve()))
        except ValueError:
            return None

    def _would_be_content(
        self,
        hook_input: dict[str, Any],
        file_path: Path,
        exists_before: bool,
    ) -> str | None:
        """Content the file WOULD have after the tool call, or None to skip."""
        tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
        if hook_input.get(HookInputField.TOOL_NAME) == ToolName.WRITE:
            raw: Any = tool_input.get(_FIELD_CONTENT, "")
            return str(raw)

        if not exists_before:
            return None
        old_string = str(tool_input.get(_FIELD_OLD_STRING, ""))
        new_string = str(tool_input.get(_FIELD_NEW_STRING, ""))
        current = file_path.read_text(encoding="utf-8")
        if not old_string or old_string not in current:
            return None
        if bool(tool_input.get(_FIELD_REPLACE_ALL, False)):
            return current.replace(old_string, new_string)
        return current.replace(old_string, new_string, _SINGLE_REPLACEMENT)

    def get_claude_md(self) -> str | None:
        return (
            "## docs_qa_edit — documentation writes are linted in real time\n"
            "\n"
            "Every Write/Edit of a documentation-scoped file (the two audience\n"
            "trees, `.claude/rules`, `.claude/skills`, `.claude/agents`, a\n"
            "root-level `.md`, a path declared in the generated-docs manifest,\n"
            "or ANY sub-folder `CLAUDE.md` regardless of tree — that last arm\n"
            "is deliberately wider than the corpus scope, since a module doc\n"
            "like `src/CLAUDE.md` sits outside every tracked tree yet is\n"
            "exactly what `module-doc-budget` polices) is checked against the\n"
            "docs QA EDIT-stage catalogue on the content the file WOULD have.\n"
            "\n"
            "**Checks**: `pointer-resolves` (a plain markdown link whose target\n"
            "file does not exist — block-eligible only for a link NEW in this\n"
            "edit), `generated-doc-hand-edit` (hand-editing a file the\n"
            "generated-docs manifest declares — regenerate it instead),\n"
            "`rules-file-shape` (`.claude/rules/*.md` must stay pointer-only:\n"
            "no fences, tables, numbered procedures or ssot-quote blocks, and a\n"
            "15-line body budget — block-eligible only when an edit ADDS a\n"
            "violation or GROWS an already-over-budget body; shrinking is\n"
            "silent), `quote-drift` (an `<!-- ssot-quote: file.md#anchor -->`\n"
            "block whose body no longer matches its source section — or whose\n"
            "source file/anchor is missing entirely — block-eligible on the\n"
            "QUOTING edit; a too-short quote, below the documented minimum\n"
            "length, is flagged the same way since it verifies trivially and\n"
            "protects nothing), `at-import-census` (an `@path.md` import\n"
            "outside `documentation.qa.resident_at_imports` re-inlines eagerly\n"
            "and defeats progressive disclosure — block-eligible only for an\n"
            "import NEW in this edit; backtick spans and fenced code are\n"
            "skipped so a doc may still quote the pattern to describe it),\n"
            "`module-doc-budget` (a sub-folder `CLAUDE.md` outside the two\n"
            "canonical roots gets a line budget: unregistered stays\n"
            "advisory-only under ~40 lines; a doc listed in\n"
            "`documentation.qa.registered_module_docs` gets the larger\n"
            "plan-doc-size block tier instead, worse-only — growing past it is\n"
            "block-eligible, unchanged advises, shrinking is silent).\n"
            "\n"
            "**Advisory only, never blocks**: `quote-source-stale` — editing a\n"
            "SOURCE section that other documents quote from names which\n"
            "quoting files now need re-checking (via the corpus's reverse quote\n"
            "index); the sweep re-verifies every quote anyway, so this is a\n"
            "heads-up, not a gate. `duplicate-block` — a structured block\n"
            "(fenced code, table, or list run of 3+ items) whose content, after\n"
            "normalisation, is identical to one already in a DIFFERENT indexed\n"
            "document; requires a warm corpus (silent on a cold one — no\n"
            "cross-document comparison is possible yet) and is hard-coded\n"
            "advisory-only: it has no block path at all, pending a hand-triaged\n"
            "whole-repo run before any promotion (see\n"
            "`CLAUDE/Plan/00284-documentation-ssot-enforcement/`).\n"
            "\n"
            "A finding only denies the write when it is BLOCK severity AND the\n"
            "resolved mode for that check (`documentation.qa.check_modes`\n"
            "override, or `documentation.qa.edit_mode` otherwise) is `block`.\n"
            "Everything else — an ADVISE-severity finding, or a BLOCK finding\n"
            "under a `warn`-mode check — surfaces as advisory context instead.\n"
            "\n"
            "Lint any file on demand:\n"
            f"`{daemon_cli_command_for_docs('docs-qa', '--lint', '<file>')}`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="docs-qa edit lint - blocks a brand-new rules file with a fence",
                command=(
                    "Use the Write tool to create a NEW file under .claude/rules/ "
                    "whose body contains a fenced code block (```...```)"
                ),
                description=(
                    "A brand-new .claude/rules/*.md file with a forbidden fenced "
                    "code block is worse than absent, so it is deny-eligible under "
                    "rules-file-shape when documentation.qa.edit_mode is block."
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[r"rules-file-shape", r"pointers only"],
                safety_notes="Deny path — no file is written; retry without the fence",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
            AcceptanceTest(
                title="docs-qa edit lint - allows a clean documentation write",
                command=(
                    "Use the Write tool to create a new .md file under CLAUDE/ "
                    "with no broken links and no forbidden rules-file elements"
                ),
                description="A well-formed documentation write passes the edit lint silently.",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Creates a scratch doc file; remove it after the test",
                test_type=TestType.BLOCKING,
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
