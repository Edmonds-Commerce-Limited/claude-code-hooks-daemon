"""CommentSizeHandler - caps over-long comments, tiered like plan-doc-size.

Comment LENGTH is mostly a symptom (`comment_changelog` is the actual
defect this project cares about — see that handler's docstring), but a
single comment can still grow unboundedly even without changelog-shaped
phrasing. This handler mirrors the `plan-doc-size` check's tiering
philosophy (Plan 00190) applied to a single comment instead of a whole
document: only an edit that GROWS the total comment volume in the touched
region can be blocked; shrinking is silent; a same-size edit only advises.
That keeps an already-over-limit legacy comment editable so it can be
refactored down, instead of freezing the file.

Two independent signals trip the limit (either is enough):
- a single comment LINE longer than `max_comment_line_chars` (default 400)
- a contiguous comment BLOCK longer than `max_comment_block_lines` (40)

Docstrings/JSDoc (`is_doc=True` spans) are API documentation, not
"comments" for size purposes -- exempt here, still subject to
`comment_changelog`.
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler import WorkspaceScope
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_file_path
from claude_code_hooks_daemon.strategies.comments.extractor import (
    CommentSpan,
    extract_comment_spans,
)
from claude_code_hooks_daemon.strategies.comments.protocol import CommentStrategy
from claude_code_hooks_daemon.strategies.comments.registry import (
    CommentStrategyRegistry,
)
from claude_code_hooks_daemon.utils.path_exclusion import (
    handler_excludes_path,
    vendored_exclude_globs,
)
from claude_code_hooks_daemon.utils.scratch_dir import scratch_path

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.project_layout import ProjectLayout

_MODE_BLOCK: Final[str] = "block"
_MODE_WARN: Final[str] = "warn"
_DEFAULT_MAX_COMMENT_LINE_CHARS: Final[int] = 400
_DEFAULT_MAX_COMMENT_BLOCK_LINES: Final[int] = 40

#: Acceptance-test fixture directories, below the sanctioned scratch root.
_FIXTURE_DIR: Final[str] = "acceptance-test-comment-size"
_FIXTURE_DIR_OK: Final[str] = "acceptance-test-comment-size-ok"

# Built-in default excludes so the "vendor/build/fixture dirs are skipped by
# default" guidance in get_claude_md() below is actually true (Plan 00288
# Task 4.6/C8 — it previously named these defaults without passing any to
# handler_excludes_path). The vendored/build half derives from the canonical
# core (Task 3.2); the fixture-semantics half is a different category and
# mirrors error_hiding_blocker's local convention.
_FIXTURE_EXCLUDE_GLOBS: Final[tuple[str, ...]] = (
    "**/tests/fixtures/**",
    "**/tests/assets/**",
    "**/__fixtures__/**",
)


def _default_exclude_globs(layout: "ProjectLayout | None") -> tuple[str, ...]:
    """Built-in excludes for one dispatch: vendored dirs + fixture dirs.

    Computed per call, not at module import (Plan 00331): the vendored half
    is configurable via ``layout.vendor_dirs``, and freezing it at import
    time meant a project could declare a directory vendored and this handler
    would still judge every file inside it. The fixture half has no config
    axis and is a plain constant.
    """
    vendored = vendored_exclude_globs(None if layout is None else layout.vendor_dirs)
    return vendored + _FIXTURE_EXCLUDE_GLOBS


_FIELD_CONTENT: Final[str] = "content"
_FIELD_OLD_STRING: Final[str] = "old_string"
_FIELD_NEW_STRING: Final[str] = "new_string"

_MAX_SPANS_SHOWN: Final[int] = 5
_PREVIEW_MAX_CHARS: Final[int] = 120

# In-content escape hatch (Write/Edit carries no shell command to prefix a
# MUST_..._BECAUSE env-var onto), matching the daemon's existing convention
# (e.g. plan-doc-size's MUST_EXCEED_PLAN_SIZE_BECAUSE).
_ESCAPE_HATCH_RE: Final[re.Pattern[str]] = re.compile(
    r"MUST_EXCEED_COMMENT_SIZE_BECAUSE\s*[:=]\s*(?P<reason>.*)"
)

# Single rule (Plan 00116): both size limits (line length, block line-count)
# are the same concept -- a comment growing past the configured cap.
_COMMENT_SIZE_RULE = Rule(
    rule_id=RuleID.COMMENT_SIZE,
    blocked="a comment growing past its configured size limit",
    why="Comments should describe current state, not accumulate",
    fix="Shorten the comment, or declare MUST_EXCEED_COMMENT_SIZE_BECAUSE",
    verbose=(
        "Comments should describe current state, not accumulate. If this comment "
        "is genuinely necessary at this size, declare why in the file:\n"
        "  # MUST_EXCEED_COMMENT_SIZE_BECAUSE: <reason>\n\n"
        "Otherwise, shorten it — shrinking edits are never blocked, so an "
        "over-limit legacy comment can always be refactored down."
    ),
)


def _has_justified_escape_hatch(content: str) -> bool:
    """Whether ``content`` declares a non-empty reason for exceeding the limit."""
    match = _ESCAPE_HATCH_RE.search(content)
    if match is None:
        return False
    return bool(match.group("reason").strip())


def _regular_spans(content: str, syntax: Any) -> list[CommentSpan]:
    """Comment spans EXCLUDING docstrings/JSDoc -- those are API docs, not comments."""
    return [span for span in extract_comment_spans(content, syntax) if not span.is_doc]


def _total_comment_chars(content: str, syntax: Any) -> int:
    """Aggregate character count across all non-doc comment spans.

    Aggregate, not per-span matching (mirroring plan-doc-size's whole-file
    byte-count philosophy): a genuine append increases this total, a
    genuine deletion decreases it, and an untouched comment elsewhere in
    the SAME touched region contributes equally to both sides so it never
    biases the comparison on its own.
    """
    return sum(len(span.text) for span in _regular_spans(content, syntax))


def _breaches(span: CommentSpan, max_line_chars: int, max_block_lines: int) -> bool:
    return span.max_line_length > max_line_chars or span.line_count > max_block_lines


class CommentSizeHandler(PreToolUseHandlerBase):
    """Block/advise on over-long comments, tiered like plan-doc-size.

    Configuration options (set via config YAML):
        max_comment_line_chars: int - single comment line character limit
            (default 400).
        max_comment_block_lines: int - contiguous comment block line-count
            limit (default 40).
        mode: "block" | "warn" - block denies a GROWING breach; warn
            downgrades every finding to advisory context (default "block").
        languages: list[str] | None - restrict to specific languages.
        exclude_paths: list[str] | None - additional glob excludes.
    """

    # PROJECT-scoped: the exclusion check consults the OWNING project's
    # vendored set via `layout_for()` (Plan 00331 Task 1.3), and the REPO
    # contract forbids a repo-singular handler consuming per-project
    # resolution.
    workspace_scope: ClassVar[WorkspaceScope] = WorkspaceScope.PROJECT

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.COMMENT_SIZE,
            priority=Priority.COMMENT_SIZE,
            # NOT terminal -- same reasoning as comment_changelog. The
            # shrink and same-size tiers deliberately return ALLOW, and the
            # chain breaks on ANY terminal match whatever it decided, so a
            # terminal ALLOW at priority 33 ended dispatch and disabled
            # every higher-numbered handler for that write. Shrinking an
            # over-long comment is meant to be silent, not to switch off
            # tdd_enforcement. A non-terminal deny still denies: chain.py
            # keeps the most restrictive decision seen.
            terminal=False,
            tags=[
                HandlerTag.MULTI_LANGUAGE,
                HandlerTag.CONTENT_QUALITY,
                HandlerTag.BLOCKING,
            ],
        )
        self._registry = CommentStrategyRegistry.create_default()
        self._languages: list[str] | None = None
        self._languages_applied: bool = False
        self._max_comment_line_chars: int = _DEFAULT_MAX_COMMENT_LINE_CHARS
        self._max_comment_block_lines: int = _DEFAULT_MAX_COMMENT_BLOCK_LINES
        self._mode: str = _MODE_BLOCK
        self._exclude_paths: list[str] | None = None
        self._formatter = RuleFormatter()

    def _apply_language_filter(self) -> None:
        if self._languages_applied:
            return
        self._languages_applied = True
        effective_languages = self._languages or self._project_languages
        if effective_languages:
            self._registry.filter_by_languages(effective_languages)

    def _region_after(self, hook_input: dict[str, Any]) -> str:
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        if tool_name == ToolName.EDIT:
            return str(tool_input.get(_FIELD_NEW_STRING, ""))
        return str(tool_input.get(_FIELD_CONTENT, ""))

    def _region_before(self, hook_input: dict[str, Any], file_path: str) -> str | None:
        """The pre-edit text to compare against, or None if there is none.

        Edit: the literal ``old_string`` being replaced. Write: the file's
        current on-disk content, or None for a brand-new file (which always
        counts as growth -- there was nothing here before).
        """
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        if tool_name == ToolName.EDIT:
            return str(tool_input.get(_FIELD_OLD_STRING, ""))
        path = Path(file_path)
        if path.is_file():
            # errors="replace", never a bare decode. This reads a file the
            # daemon did not write and has no encoding contract with:
            # latin-1/CP1252 sources are ordinary in PHP and C# trees, both
            # of which are in this handler's language registry. An unguarded
            # decode raised UnicodeDecodeError straight out of handle(),
            # which fail-open turned into user-visible exception text and
            # strict_mode turned into a hard DENY of a legitimate write.
            # A replacement char cannot change the outcome here either way:
            # this content is only ever measured for LENGTH.
            return path.read_text(encoding="utf-8", errors="replace")
        return None

    def _is_excluded(self, file_path: str) -> bool:
        layout = self.layout_for(file_path)
        return handler_excludes_path(
            file_path,
            handler_patterns=self._exclude_paths,
            project_patterns=self._project_exclude_paths,
            defaults=_default_exclude_globs(layout),
            layout=layout,
        )

    def _breaching_spans(self, content: str, strategy: CommentStrategy) -> list[CommentSpan]:
        return [
            span
            for span in _regular_spans(content, strategy.syntax)
            if _breaches(span, self._max_comment_line_chars, self._max_comment_block_lines)
        ]

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check whether the content being written has an over-limit comment."""
        self._apply_language_filter()

        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in (ToolName.WRITE, ToolName.EDIT):
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        strategy = self._registry.get_strategy(file_path)
        if strategy is None:
            return False

        if any(skip_dir in file_path for skip_dir in strategy.skip_directories):
            return False
        if self._is_excluded(file_path):
            return False

        content = self._region_after(hook_input)
        if not content:
            return False

        return bool(self._breaching_spans(content, strategy))

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny a GROWING over-limit comment; advise on same-size; silent on shrink."""
        file_path = get_file_path(hook_input)
        if not file_path:
            return GatingResult(decision=Decision.ALLOW)

        strategy = self._registry.get_strategy(file_path)
        if strategy is None:
            return GatingResult(decision=Decision.ALLOW)

        content_after = self._region_after(hook_input)
        if not content_after:
            return GatingResult(decision=Decision.ALLOW)

        breaching = self._breaching_spans(content_after, strategy)
        if not breaching:
            return GatingResult(decision=Decision.ALLOW)

        content_before = self._region_before(hook_input, file_path)
        chars_after = _total_comment_chars(content_after, strategy.syntax)
        chars_before = (
            None
            if content_before is None
            else _total_comment_chars(content_before, strategy.syntax)
        )

        grows = chars_before is None or chars_after > chars_before
        if not grows:
            if chars_before is not None and chars_after < chars_before:
                # Shrinking is the remedy in progress -- always silent, or an
                # over-limit comment could never be refactored down.
                return GatingResult(decision=Decision.ALLOW)
            return GatingResult(
                decision=Decision.ALLOW, context=[self._build_advisory(breaching, grew=False)]
            )

        if _has_justified_escape_hatch(content_after):
            return GatingResult(
                decision=Decision.ALLOW, context=[self._build_advisory(breaching, grew=True)]
            )
        if self._mode == _MODE_WARN:
            return GatingResult(
                decision=Decision.ALLOW, context=[self._build_advisory(breaching, grew=True)]
            )

        return GatingResult(
            decision=Decision.DENY, reason=self._build_deny_reason(hook_input, breaching)
        )

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's blocking behaviour."""
        return [_COMMENT_SIZE_RULE]

    def _describe(self, span: CommentSpan) -> str:
        parts: list[str] = []
        if span.max_line_length > self._max_comment_line_chars:
            parts.append(
                f"{span.max_line_length} chars on one line (limit {self._max_comment_line_chars})"
            )
        if span.line_count > self._max_comment_block_lines:
            parts.append(f"{span.line_count} lines (limit {self._max_comment_block_lines})")
        return " and ".join(parts)

    def _preview(self, span: CommentSpan) -> str:
        text = span.text
        return text if len(text) <= _PREVIEW_MAX_CHARS else text[: _PREVIEW_MAX_CHARS - 3] + "..."

    def _build_deny_reason(self, hook_input: dict[str, Any], breaching: list[CommentSpan]) -> str:
        """Build the DENY reason.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G). The per-invocation
        diagnostic (which spans, how far over the limit) is dynamic and
        always fully present -- only the surrounding "why/how to fix" prose
        goes terse on repeat fires.
        """
        lines = [
            f"  - {self._describe(span)}\n    {self._preview(span)!r}"
            for span in breaching[:_MAX_SPANS_SHOWN]
        ]
        spans_text = "\n".join(lines)
        dynamic_detail = f"{len(breaching)} comment(s) exceed the size limit:\n\n{spans_text}"

        rule = _COMMENT_SIZE_RULE
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, rule.rule_id):
            message = self._formatter.terse(rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, rule.rule_id)
            message = self._formatter.verbose(rule)

        return f"{message}\n\n{dynamic_detail}"

    def _build_advisory(self, breaching: list[CommentSpan], *, grew: bool) -> str:
        prefix = (
            "ADVISORY: over-long comment (growth-check bypassed)"
            if grew
            else ("ADVISORY: over-long comment (not growing — never blocked)")
        )
        lines = [prefix]
        for span in breaching[:_MAX_SPANS_SHOWN]:
            lines.append(f"  - {self._describe(span)}: {self._preview(span)!r}")
        return "\n".join(lines)

    def get_claude_md(self) -> str | None:
        return (
            "## comment_size — over-long comments are capped, tiered like plan-doc-size\n\n"
            "A `Write`/`Edit` whose content contains an over-limit comment is blocked "
            "or advised, using the SAME grow/shrink/same-size tiering as `plan-doc-size`: "
            "only an edit that GROWS an already-over-limit comment can be denied.\n\n"
            "**Two independent limits (either trips it)**:\n"
            f"- a single comment line longer than `max_comment_line_chars` "
            f"(default {_DEFAULT_MAX_COMMENT_LINE_CHARS})\n"
            f"- a contiguous comment block longer than `max_comment_block_lines` "
            f"(default {_DEFAULT_MAX_COMMENT_BLOCK_LINES})\n\n"
            "**Tiering**:\n"
            "- **Shrinking is silent** — always allowed, no context, so an "
            "over-commented legacy file stays editable and can be refactored down.\n"
            "- **Same-size only advises** — never blocks, so a legitimately-unchanged "
            "oversized comment does not trap the file.\n"
            "- **Growing an already-over-limit comment is BLOCKED** unless the escape "
            "hatch is declared or `mode: warn` is configured.\n\n"
            "**Escape hatch** (in-content, matching the daemon's `MUST_..._BECAUSE` "
            "convention):\n"
            "```\n"
            "# MUST_EXCEED_COMMENT_SIZE_BECAUSE: verbatim upstream licence text, "
            "must not be reflowed\n"
            "```\n\n"
            "**Docstrings and JSDoc are API documentation, not comments** — exempt "
            "from this handler entirely (still subject to `comment_changelog`).\n\n"
            "**Excluded paths**: vendor/build/fixture dirs are skipped by default. "
            "Exempt more paths via "
            "`handlers.pre_tool_use.comment_size.options.exclude_paths` or the "
            "project-wide `daemon.exclude_paths`."
        )

    def get_acceptance_tests(self) -> list[Any]:
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
        )

        return [
            AcceptanceTest(
                title="comment_size: over-long trailing comment on a new file is blocked",
                command=(
                    "Use the Write tool to create "
                    f"{scratch_path(_FIXTURE_DIR, 'example.py')} whose "
                    "content has a trailing '#' comment on one line longer than 400 characters"
                ),
                description=(
                    "Blocks creation of a file whose comment already exceeds the "
                    "size limit (a brand-new file has no 'before', so it always "
                    "counts as growth)"
                ),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    "comment",
                    "BLOCKED",
                    "MUST_EXCEED_COMMENT_SIZE_BECAUSE",
                ],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. Handler blocks "
                    "Write before file is created."
                ),
                test_type=TestType.BLOCKING,
                setup_commands=[f"mkdir -p untracked/scratch/{_FIXTURE_DIR}"],
                cleanup_commands=[f"rm -rf untracked/scratch/{_FIXTURE_DIR}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="comment_size: a normal, reasonably-sized comment is allowed",
                command=(
                    "Use the Write tool to create "
                    f"{scratch_path(_FIXTURE_DIR_OK, 'example.py')} whose "
                    "content has an ordinary short '#' comment (well under 400 chars, "
                    "well under 40 lines) explaining a single function"
                ),
                description=(
                    "Near-miss ALLOW case: an ordinary explanatory comment is never "
                    "blocked -- only comments that actually exceed the size limit are"
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes=(
                    "Inside the gitignored scratch directory - safe. Verify the file "
                    "is created, not blocked."
                ),
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p untracked/scratch/{_FIXTURE_DIR_OK}"],
                cleanup_commands=[f"rm -rf untracked/scratch/{_FIXTURE_DIR_OK}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
        ]
