"""MarkdownTableFormatterHandler - auto-format markdown tables via mdformat + mdformat-gfm.

Runs after Write/Edit of .md files, reformats the content with mdformat so tables
have aligned pipes and consistent column widths, then writes back only if changed.

Applies three mitigations to constrain mdformat's default behaviour:

1. `options={"number": True}` preserves consecutive ordered-list numbering
   (1. 2. 3.) instead of renumbering everything to 1.
2. Post-processes mdformat's output to restore `---` thematic breaks
   (mdformat hardcodes 70 underscores for thematic breaks with no config option).
3. Strips leading YAML frontmatter (``---`` block) before formatting and
   re-attaches it byte-for-byte afterwards. mdformat does not understand
   YAML frontmatter and would otherwise mangle it into a thematic break
   followed by collapsed heading text — which would break Claude Code
   SKILL.md files and any other frontmatter-bearing markdown document.
"""

import difflib
import re
from pathlib import Path
from typing import Any, Final

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import BlockingResult, Decision
from claude_code_hooks_daemon.core.handler_bases import PostToolUseHandlerBase
from claude_code_hooks_daemon.core.utils import get_file_path
from claude_code_hooks_daemon.plan_qa.paths import is_journal_file
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.markdown_format import format_markdown_text

# Extensions treated as markdown (lowercase match).
_MARKDOWN_EXTENSIONS: tuple[str, ...] = (".md", ".markdown")

# --- Advisory-message classification --------------------------------------
#
# The PostToolUse advisory names WHICH of the formatter's transformations
# actually fired on this file, derived by diffing the before/after text —
# never by instrumenting `format_markdown_text` (see markdown_format.py,
# the single source of truth for the transform itself). Order here is fixed
# and matches the order documented in `get_claude_md()` below, regardless of
# where in the document each change physically appears.
_LABEL_TABLE_PIPES: Final[str] = "aligned table pipes"
_LABEL_ORDERED_LISTS: Final[str] = "renumbered ordered lists"
_LABEL_THEMATIC_BREAKS: Final[str] = "restored thematic breaks"
_LABEL_ASTERISKS: Final[str] = "escaped stray asterisks"

# The post-processed thematic-break form `format_markdown_text` always
# produces (see `_THEMATIC_BREAK_DASHES` in markdown_format.py). Duplicated
# here deliberately rather than importing that module's private constant:
# this is the stable CommonMark thematic-break literal, not shared logic.
_THEMATIC_BREAK: Final[str] = "---"

# An ordered-list marker at the start of a line: leading whitespace, digits,
# a '.' or ')' delimiter, then the whitespace that must follow it.
_ORDERED_LIST_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"^(\s*)\d+([.)])(\s)")
# Same marker with the digits replaced by a placeholder, used to test
# whether two lines differ ONLY in their list number.
_ORDERED_LIST_MARKER_NORMALIZED: Final[str] = r"\1#\2\3"


def _ordered_list_renumbered(before_chunk: list[str], after_chunk: list[str]) -> bool:
    """Return True if this diff chunk's only change is an ordered-list number.

    `format_markdown_text` runs mdformat with `options={"number": True}`,
    which preserves already-consecutive numbering and only rewrites numbers
    that were NOT consecutive (e.g. `1. 1. 1.` -> `1. 2. 3.`). Comparing a
    line with its digits normalised to a placeholder isolates exactly that:
    if two same-position lines are equal once the digits are blanked out,
    the digits are the only thing that changed.
    """
    if len(before_chunk) != len(after_chunk):
        return False
    for before_line, after_line in zip(before_chunk, after_chunk, strict=True):
        if before_line == after_line:
            continue
        if not _ORDERED_LIST_MARKER_RE.match(before_line):
            continue
        if not _ORDERED_LIST_MARKER_RE.match(after_line):
            continue
        before_normalized = _ORDERED_LIST_MARKER_RE.sub(
            _ORDERED_LIST_MARKER_NORMALIZED, before_line
        )
        after_normalized = _ORDERED_LIST_MARKER_RE.sub(_ORDERED_LIST_MARKER_NORMALIZED, after_line)
        if before_normalized == after_normalized:
            return True
    return False


def _stray_asterisk_escaped(before_chunk: list[str], after_chunk: list[str]) -> bool:
    """Return True if this diff chunk added a backslash-escaped asterisk.

    mdformat only ever ADDS a backslash before a literal `*` it cannot parse
    as emphasis markup — it never removes one, and paired emphasis markers
    like `*word*` are left alone. Counting `\\*` occurrences on each side of
    the SAME diff chunk is therefore precise: a rise means an asterisk was
    newly escaped here, not that surrounding whitespace merely shifted.
    """
    before_escaped = "\n".join(before_chunk).count("\\*")
    after_escaped = "\n".join(after_chunk).count("\\*")
    return after_escaped > before_escaped


def classify_markdown_changes(before: str, formatted: str) -> list[str]:
    """Return the ordered labels of transformation categories that fired.

    Diffs `before` against `formatted` line-by-line and reports only the
    categories that genuinely differ in THIS pair — never the fixed menu of
    everything the formatter is capable of. Order is fixed (table pipes,
    ordered lists, thematic breaks, asterisks) regardless of where in the
    document each change appears.

    Frontmatter is never reported: `format_markdown_text` re-attaches it
    byte-for-byte, so its lines are identical before/after and never enter a
    diff chunk in the first place.

    Returns an empty list both when there is no diff at all, and when
    `formatted` differs from `before` in a way none of the four categories
    explains — callers distinguish the two via their own `formatted != before`
    check and fall back to a generic message for the latter.
    """
    before_lines = before.split("\n")
    after_lines = formatted.split("\n")
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)

    saw_table_pipes = False
    saw_ordered_lists = False
    saw_thematic_breaks = False
    saw_asterisks = False

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        before_chunk = before_lines[i1:i2]
        after_chunk = after_lines[j1:j2]

        if any("|" in line for line in before_chunk + after_chunk):
            saw_table_pipes = True
        if _THEMATIC_BREAK in after_chunk and _THEMATIC_BREAK not in before_chunk:
            saw_thematic_breaks = True
        if _ordered_list_renumbered(before_chunk, after_chunk):
            saw_ordered_lists = True
        if _stray_asterisk_escaped(before_chunk, after_chunk):
            saw_asterisks = True

    labels: list[str] = []
    if saw_table_pipes:
        labels.append(_LABEL_TABLE_PIPES)
    if saw_ordered_lists:
        labels.append(_LABEL_ORDERED_LISTS)
    if saw_thematic_breaks:
        labels.append(_LABEL_THEMATIC_BREAKS)
    if saw_asterisks:
        labels.append(_LABEL_ASTERISKS)
    return labels


def _build_reformat_message(file_name: str, labels: list[str]) -> str:
    """Build the PostToolUse advisory naming what changed in `file_name`.

    Only names transformations `classify_markdown_changes` actually found;
    when the file changed but no tracked category explains it, falls back
    to a truthful generic message rather than silently reporting nothing.
    """
    if not labels:
        return f"Reformatted markdown in {file_name}"
    return f"Reformatted markdown in {file_name}: {', '.join(labels)}"


class MarkdownTableFormatterHandler(PostToolUseHandlerBase):
    """Auto-format markdown tables after Write/Edit of .md files.

    Triggers on PostToolUse events for the Write and Edit tools when the target
    file has a `.md` or `.markdown` extension. Formats the file in place using
    mdformat + mdformat-gfm, then writes back only if the content changed.

    Non-terminal: other PostToolUse handlers still run after this one.
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.MARKDOWN_TABLE_FORMATTER,
            priority=Priority.MARKDOWN_TABLE_FORMATTER,
            terminal=False,
            tags=[
                HandlerTag.MARKDOWN,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Match Write/Edit of existing .md/.markdown files."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in (ToolName.WRITE, ToolName.EDIT):
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        if not file_path.lower().endswith(_MARKDOWN_EXTENSIONS):
            return False

        # Plan 00163: a journal is an append-only, byte-stable log;
        # reformatting one would rewrite earlier entries and trip the
        # journal-append-only check. Plan 00190: exempt the whole of journal
        # territory via the shared config-independent predicate — by LOCATION
        # as well as by day-file grammar — so a file inside JOURNAL/ whose
        # name does not parse is not silently rewritten.
        if is_journal_file(Path(file_path)):
            return False

        # PostToolUse runs after the write, so the file must exist on disk.
        return Path(file_path).exists()

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Reformat the markdown file in place if its content changes."""
        file_path = get_file_path(hook_input)
        if not file_path:
            return BlockingResult(decision=Decision.ALLOW)

        path = Path(file_path)
        if not path.exists():
            return BlockingResult(decision=Decision.ALLOW)

        try:
            before = path.read_text(encoding="utf-8")
            formatted = format_markdown_text(before)
        except Exception as exc:
            # FAIL SAFE: mdformat can raise many parser/IO/unicode errors.
            # Never crash the PostToolUse dispatch chain — surface the error
            # as advisory context and allow the write through unchanged.
            return BlockingResult(
                decision=Decision.ALLOW,
                context=[
                    f"markdown_table_formatter failed on {path.name}: {exc}",
                ],
            )

        if formatted == before:
            return BlockingResult(decision=Decision.ALLOW)

        # Re-read immediately before writing. `formatted` derives from the
        # snapshot taken above, and a PostToolUse dispatch can lag well behind
        # the edit that triggered it — so by now the file may hold NEWER
        # content. Writing the stale snapshot back would silently revert a
        # change this handler never made. Skipping costs nothing: that newer
        # write raises its own PostToolUse event and gets formatted by it.
        try:
            if path.read_text(encoding="utf-8") != before:
                return BlockingResult(
                    decision=Decision.ALLOW,
                    context=[
                        f"{path.name} changed while it was being formatted — skipped "
                        "the rewrite rather than revert the newer content",
                    ],
                )
        except Exception as exc:
            # FAIL SAFE, consistent with the read above: never crash the
            # dispatch chain. Unable to confirm the file is unchanged means we
            # must not write.
            return BlockingResult(
                decision=Decision.ALLOW,
                context=[
                    f"markdown_table_formatter could not re-read {path.name}: {exc}",
                ],
            )

        path.write_text(formatted, encoding="utf-8")
        labels = classify_markdown_changes(before, formatted)
        return BlockingResult(
            decision=Decision.ALLOW,
            context=[_build_reformat_message(path.name, labels)],
        )

    def get_claude_md(self) -> str | None:
        return (
            "## markdown_table_formatter — markdown tables are auto-aligned\n"
            "\n"
            "After every `Write` or `Edit` of a `.md` or `.markdown` file, the content is "
            "re-formatted via `mdformat + mdformat-gfm` so that table pipes are aligned "
            "and column widths are consistent. The handler is non-terminal and advisory — "
            "it never blocks, it just rewrites the file on disk.\n"
            "\n"
            "**What changes:**\n"
            "\n"
            "- Table pipes are aligned vertically and delimiter rows widened to match cell "
            "widths.\n"
            "- Ordered lists keep consecutive numbering (`1.` `2.` `3.`).\n"
            "- `---` thematic breaks are preserved (mdformat's 70-underscore default is "
            "post-processed back).\n"
            "- Asterisks in table cells are escaped (`*` → `\\*`) as required by GFM.\n"
            "\n"
            "**The advisory names exactly what changed in THIS file** — e.g. "
            "`Reformatted markdown in NOTES.md: aligned table pipes, renumbered ordered "
            "lists` — never the full menu above. If mdformat changed the file in a way none "
            "of the four categories explains, the advisory falls back to a generic "
            "`Reformatted markdown in NOTES.md` rather than naming a transformation that "
            "did not happen.\n"
            "\n"
            "**Exempt:** anything under a plan's `JOURNAL/` directory is NEVER "
            "reformatted — day-files (`JOURNAL/NNNNN-Journal-YY-MM-DD.md`, Plan 00163) "
            "and any other file in there. A journal is an append-only, byte-stable log; "
            "rewriting it would trip the `journal-append-only` check. The exemption is "
            "by LOCATION as well as by filename, so a mis-named day-file is still safe.\n"
            "\n"
            "**Ad-hoc formatting of existing files:**\n"
            "\n"
            "```\n"
            f"{daemon_cli_command_for_docs('format-markdown', '<path>')}\n"
            "```\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests for the handler — Write/Edit of .md files."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Markdown table auto-alignment after Write",
                command=(
                    "Use the Write tool to create "
                    "untracked/scratch/acceptance-test-mdformat/doc.md "
                    "with content:\n"
                    "# Test\n\n"
                    "| Name | Value |\n"
                    "|---|---|\n"
                    "| Short | x |\n"
                    "| Very Long Name | y |\n"
                ),
                description=(
                    "Writes a markdown file with unaligned table pipes. "
                    "PostToolUse handler reformats the file so pipes are "
                    "vertically aligned and delimiter row matches cell widths."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"Reformatted markdown in doc\.md.*table pipes"],
                safety_notes=(
                    "Creates a temporary markdown file inside the gitignored scratch "
                    "directory for formatting test"
                ),
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p untracked/scratch/acceptance-test-mdformat"],
                cleanup_commands=["rm -rf untracked/scratch/acceptance-test-mdformat"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
