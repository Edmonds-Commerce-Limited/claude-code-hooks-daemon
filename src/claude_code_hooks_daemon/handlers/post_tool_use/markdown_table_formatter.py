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
from claude_code_hooks_daemon.core.worktree_paths import nested_git_checkout_root
from claude_code_hooks_daemon.plan_qa.paths import is_journal_file
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command_for_docs
from claude_code_hooks_daemon.utils.git_repo import is_worktree_of_repo
from claude_code_hooks_daemon.utils.markdown_format import (
    UnresolvedConflictError,
    format_markdown_document,
)
from claude_code_hooks_daemon.utils.path_exclusion import (
    handler_excludes_path,
    resolve_project_root,
)
from claude_code_hooks_daemon.utils.path_predicates import path_exists
from claude_code_hooks_daemon.utils.scratch_dir import acceptance_path

# Extensions treated as markdown (lowercase match).
_MARKDOWN_EXTENSIONS: tuple[str, ...] = (".md", ".markdown")

#: Acceptance-test fixture directory, below the gitignored acceptance root.
_FIXTURE_DIR: Final[str] = "acceptance-test-mdformat"

#: Opens the advisory for a file left unformatted because it is conflicted.
_CONFLICT_HEADLINE: Final[str] = "MERGE CONFLICT MARKERS:"

# --- Advisory-message classification --------------------------------------
#
# The PostToolUse advisory names WHICH of the formatter's transformations
# actually fired on this file, derived by diffing the before/after text —
# never by instrumenting `format_markdown_text` (see markdown_format.py,
# the single source of truth for the transform itself). Order here is fixed
# and matches the order documented in `get_claude_md()` below, regardless of
# where in the document each change physically appears.
#
# mdformat rewrites the WHOLE file, so naming a category is only accurate
# when it accounts for the entire diff chunk. A chunk no category fully
# explains (bullet markers, blank lines, escaping, wrapping, ...) makes the
# advisory say the whole file was reformatted instead of a narrower claim.
_LABEL_TABLE_PIPES: Final[str] = "aligned table pipes"
_LABEL_ORDERED_LISTS: Final[str] = "renumbered ordered lists"
_LABEL_THEMATIC_BREAKS: Final[str] = "restored thematic breaks"
_LABEL_ASTERISKS: Final[str] = "escaped stray asterisks"

#: Opens the advisory when the change is not fully covered by the labels.
_WHOLE_FILE_HEADLINE: Final[str] = "Reformatted the whole file (mdformat):"
#: Names the changes the labels cannot, so the claim is never narrower than the edit.
_OTHER_CHANGES: Final[str] = (
    "other formatting changes (bullet markers, blank lines, escaping, wrapping)"
)

# The post-processed thematic-break form `format_markdown_text` always
# produces (see `_THEMATIC_BREAK_DASHES` in markdown_format.py). Duplicated
# here deliberately rather than importing that module's private constant:
# this is the stable CommonMark thematic-break literal, not shared logic.
_THEMATIC_BREAK: Final[str] = "---"

# Any CommonMark thematic-break spelling: three or more of one of - * _.
_THEMATIC_BREAK_SOURCE_RE: Final[re.Pattern[str]] = re.compile(
    r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$"
)

# An ordered-list marker at the start of a line: leading whitespace, digits,
# a '.' or ')' delimiter, then the whitespace that must follow it.
_ORDERED_LIST_MARKER_RE: Final[re.Pattern[str]] = re.compile(r"^(\s*)\d+([.)])(\s)")
# Same marker with the digits replaced by a placeholder, used to test
# whether two lines differ ONLY in their list number.
_ORDERED_LIST_MARKER_NORMALIZED: Final[str] = r"\1#\2\3"

_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")
_DASH_RUN_RE: Final[re.Pattern[str]] = re.compile(r"-+")
# A table delimiter row: only pipes, colons, dashes and spaces.
_TABLE_DELIMITER_ROW_RE: Final[re.Pattern[str]] = re.compile(r"^[\s|:-]+$")


def _squash(lines: list[str]) -> str:
    """Reduce lines to what survives table padding and asterisk escaping.

    Whitespace is dropped, a table delimiter row's dash run is collapsed and
    `\\*` is read as `*`, so two chunks that differ ONLY in column padding,
    delimiter width or asterisk escaping squash to the same string.
    """
    squashed: list[str] = []
    for line in lines:
        if _TABLE_DELIMITER_ROW_RE.match(line):
            line = _DASH_RUN_RE.sub("-", line)
        squashed.append(_WHITESPACE_RE.sub("", line.replace("\\*", "*")))
    return "".join(squashed)


def _table_pipes_realigned(before_chunk: list[str], after_chunk: list[str]) -> bool:
    """Return True if this chunk is table rows that differ only in padding."""
    lines = before_chunk + after_chunk
    if not lines or not all(line.lstrip().startswith("|") for line in lines):
        return False
    return _squash(before_chunk) == _squash(after_chunk)


def _thematic_break_restored(before_chunk: list[str], after_chunk: list[str]) -> bool:
    """Return True if this chunk's only change is a break respelled as `---`."""
    if len(before_chunk) != len(after_chunk):
        return False
    changed = False
    for before_line, after_line in zip(before_chunk, after_chunk, strict=True):
        if before_line == after_line:
            continue
        if after_line != _THEMATIC_BREAK or not _THEMATIC_BREAK_SOURCE_RE.match(before_line):
            return False
        changed = True
    return changed


def _ordered_list_renumbered(before_chunk: list[str], after_chunk: list[str]) -> bool:
    """Return True if this diff chunk's only change is ordered-list numbers.

    `format_markdown_text` runs mdformat with `options={"number": True}`,
    which preserves already-consecutive numbering and only rewrites numbers
    that were NOT consecutive (e.g. `1. 1. 1.` -> `1. 2. 3.`). Comparing a
    line with its digits normalised to a placeholder isolates exactly that:
    if every same-position line pair is equal once the digits are blanked
    out, the digits are the only thing that changed.
    """
    if len(before_chunk) != len(after_chunk):
        return False
    changed = False
    for before_line, after_line in zip(before_chunk, after_chunk, strict=True):
        if before_line == after_line:
            continue
        if not _ORDERED_LIST_MARKER_RE.match(before_line):
            return False
        if not _ORDERED_LIST_MARKER_RE.match(after_line):
            return False
        before_normalized = _ORDERED_LIST_MARKER_RE.sub(
            _ORDERED_LIST_MARKER_NORMALIZED, before_line
        )
        after_normalized = _ORDERED_LIST_MARKER_RE.sub(_ORDERED_LIST_MARKER_NORMALIZED, after_line)
        if before_normalized != after_normalized:
            return False
        changed = True
    return changed


def _stray_asterisk_escaped(before_chunk: list[str], after_chunk: list[str]) -> bool:
    """Return True if this diff chunk's only change is escaped asterisks.

    mdformat only ever ADDS a backslash before a literal `*` it cannot parse
    as emphasis markup — it never removes one, and paired emphasis markers
    like `*word*` are left alone. A chunk is an escape-only change when it
    holds more `\\*` after than before AND the two sides are otherwise equal
    (ignoring table padding).
    """
    before_escaped = "\n".join(before_chunk).count("\\*")
    after_escaped = "\n".join(after_chunk).count("\\*")
    if after_escaped <= before_escaped:
        return False
    return _squash(before_chunk) == _squash(after_chunk)


def _classify_changes(before: str, formatted: str) -> tuple[list[str], bool]:
    """Return the fired category labels and whether they explain the whole diff."""
    before_lines = before.split("\n")
    after_lines = formatted.split("\n")
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)

    saw_table_pipes = False
    saw_ordered_lists = False
    saw_thematic_breaks = False
    saw_asterisks = False
    fully_named = True

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        before_chunk = before_lines[i1:i2]
        after_chunk = after_lines[j1:j2]

        table = _table_pipes_realigned(before_chunk, after_chunk)
        ordered = _ordered_list_renumbered(before_chunk, after_chunk)
        thematic = _thematic_break_restored(before_chunk, after_chunk)
        asterisks = _stray_asterisk_escaped(before_chunk, after_chunk)

        saw_table_pipes = saw_table_pipes or table
        saw_ordered_lists = saw_ordered_lists or ordered
        saw_thematic_breaks = saw_thematic_breaks or thematic
        saw_asterisks = saw_asterisks or asterisks
        if not (table or ordered or thematic or asterisks):
            fully_named = False

    labels: list[str] = []
    if saw_table_pipes:
        labels.append(_LABEL_TABLE_PIPES)
    if saw_ordered_lists:
        labels.append(_LABEL_ORDERED_LISTS)
    if saw_thematic_breaks:
        labels.append(_LABEL_THEMATIC_BREAKS)
    if saw_asterisks:
        labels.append(_LABEL_ASTERISKS)
    return labels, fully_named


def classify_markdown_changes(before: str, formatted: str) -> list[str]:
    """Return the ordered labels of transformation categories that fired.

    Diffs `before` against `formatted` line-by-line and reports only the
    categories that fully explain a diff chunk of THIS pair — never the fixed
    menu of everything the formatter is capable of. Order is fixed (table
    pipes, ordered lists, thematic breaks, asterisks) regardless of where in
    the document each change appears.

    Frontmatter is never reported: `format_markdown_text` re-attaches it
    byte-for-byte, so its lines are identical before/after and never enter a
    diff chunk in the first place.

    The labels alone may not cover the whole diff; the handler asks
    `_classify_changes` for that as well and words the advisory accordingly.
    """
    return _classify_changes(before, formatted)[0]


def _build_reformat_message(file_name: str, labels: list[str], *, fully_named: bool = True) -> str:
    """Build the PostToolUse advisory naming what changed in `file_name`.

    When the labels cover the whole diff the advisory lists them. When some
    change falls outside them it says the whole file was reformatted, so the
    advisory is never narrower than the edit that was made.
    """
    if fully_named:
        return f"Reformatted markdown in {file_name}: {', '.join(labels)}"
    if not labels:
        return f"{_WHOLE_FILE_HEADLINE} {file_name}: {_OTHER_CHANGES}"
    return f"{_WHOLE_FILE_HEADLINE} {file_name}: {', '.join(labels)}, plus {_OTHER_CHANGES}"


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
        # Glob patterns exempted from formatting; unions with the project-wide
        # daemon.exclude_paths the registry injects. Set via setattr AFTER
        # __init__, like every handler option.
        self._exclude_paths: list[str] | None = None

    def _is_in_scope(self, file_path: str) -> bool:
        """Whether this handler may rewrite ``file_path``.

        Out of scope: a path the project excluded (handler option or
        ``daemon.exclude_paths``), and a file inside a nested separate git
        checkout, which belongs to another repository. A linked worktree of
        THIS repository (same common git dir) is not separate, so its files are
        still formatted; a worktree of any other repository is skipped.
        """
        if handler_excludes_path(
            file_path,
            handler_patterns=self._exclude_paths,
            project_patterns=self._project_exclude_paths,
            layout=self.layout_for(file_path),
        ):
            return False
        project_root = resolve_project_root()
        if project_root is None:
            return True
        nested = nested_git_checkout_root(file_path, Path(project_root))
        return nested is None or is_worktree_of_repo(nested, Path(project_root))

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

        # Issue #79: an excluded path, or another repository's checkout.
        if not self._is_in_scope(file_path):
            return False

        # PostToolUse runs after the write, so the file must exist on disk.
        # A file the daemon cannot stat cannot be read or rewritten either, so
        # it is out of scope for the same reason a missing one is.
        return path_exists(file_path, unreadable_means=False)

    def handle(self, hook_input: dict[str, Any]) -> BlockingResult:
        """Reformat the markdown file in place if its content changes."""
        file_path = get_file_path(hook_input)
        if not file_path:
            return BlockingResult(decision=Decision.ALLOW)

        path = Path(file_path)
        # A second, independent check: `handle()` is reachable without
        # `matches()` having run first, so guarding only the one above would
        # leave this raising. The scope check rides along for the same reason.
        if not self._is_in_scope(file_path) or not path_exists(path, unreadable_means=False):
            return BlockingResult(decision=Decision.ALLOW)

        try:
            before = path.read_text(encoding="utf-8")
            formatted = format_markdown_document(before)
        except UnresolvedConflictError as exc:
            # Plan 00466 N211: formatting would disguise the markers, so the
            # file is left as it is and the markers are named instead.
            return BlockingResult(
                decision=Decision.ALLOW,
                context=[f"{_CONFLICT_HEADLINE} {path.name} {exc}"],
            )
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
        labels, fully_named = _classify_changes(before, formatted)
        return BlockingResult(
            decision=Decision.ALLOW,
            context=[_build_reformat_message(path.name, labels, fully_named=fully_named)],
        )

    def get_claude_md(self) -> str | None:
        return (
            "## markdown_table_formatter — markdown tables are auto-aligned\n"
            "\n"
            "After every `Write` or `Edit` of a `.md` or `.markdown` file, the content is "
            "re-formatted via `mdformat + mdformat-gfm`. **The WHOLE file is formatted, "
            "not just its tables** (the same policy as `format-markdown`): table pipes are "
            "aligned, and bullet markers, blank lines, escaping and wrapping are normalised "
            "too. The handler is non-terminal and advisory — it never blocks, it just "
            "rewrites the file on disk.\n"
            "\n"
            "**Known transformations:**\n"
            "\n"
            "- Table pipes are aligned vertically and delimiter rows widened to match cell "
            "widths.\n"
            "- Ordered lists keep consecutive numbering (`1.` `2.` `3.`).\n"
            "- `---` thematic breaks are preserved (mdformat's 70-underscore default is "
            "post-processed back).\n"
            "- Asterisks in table cells are escaped (`*` → `\\*`) as required by GFM.\n"
            "\n"
            "**The advisory never claims a narrower change than the one made.** When the "
            "four known transformations account for the whole diff it names them, e.g. "
            "`Reformatted markdown in NOTES.md: aligned table pipes, renumbered ordered "
            "lists`. When anything else changed too, it says `Reformatted the whole file "
            "(mdformat): ...`, listing the known transformations that fired and "
            "`other formatting changes`.\n"
            "\n"
            "**Opt a path out** with `exclude_paths`: gitignore-style globs in "
            "`handlers.post_tool_use.markdown_table_formatter.options.exclude_paths`, "
            "added to the project-wide `daemon.exclude_paths`. Use it for generated or "
            "hand-formatted markdown that must stay byte-for-byte as written.\n"
            "\n"
            "**A file in a nested separate git checkout is NEVER reformatted** — a "
            "directory below the project root with its own `.git` (a vendored clone or a "
            "submodule) belongs to another repository. A linked worktree of this "
            "repository is still formatted.\n"
            "\n"
            "**Exempt:** anything under a plan's `JOURNAL/` directory is NEVER "
            "reformatted — day-files (`JOURNAL/NNNNN-Journal-YY-MM-DD.md`, Plan 00163) "
            "and any other file in there. A journal is an append-only, byte-stable log; "
            "rewriting it would trip the `journal-append-only` check. The exemption is "
            "by LOCATION as well as by filename, so a mis-named day-file is still safe.\n"
            "\n"
            "**A file holding merge-conflict markers is NEVER reformatted**, and the "
            "advisory names each marker's line instead. Formatting would escape the "
            "opener into a heading and turn the closer into a seven-deep blockquote, "
            "after which no check recognises either. A marker the formatter already "
            "disguised is recognised and reported too. Resolve the conflict, and the "
            "next Write/Edit formats the file as usual.\n"
            "\n"
            "**Ad-hoc formatting of existing files:**\n"
            "\n"
            "```\n"
            f"{daemon_cli_command_for_docs('format-markdown', '<path>')}\n"
            "```\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests for the handler — Write/Edit of .md files."""
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        # Stated once; the prose is rendered from it (Plan 00243). This one
        # shows why: the misaligned pipes ARE the fixture, so a tester
        # retyping them from a sentence could accidentally align them and
        # the handler would then correctly do nothing.
        probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": acceptance_path(_FIXTURE_DIR, "doc.md"),
                "content": (
                    "# Test\n\n| Name | Value |\n|---|---|\n| Short | x |\n| Very Long Name | y |\n"
                ),
            },
        )

        return [
            AcceptanceTest(
                title="Markdown table auto-alignment after Write",
                command=probe.as_instruction(),
                tool_payload=probe,
                description=(
                    "Writes a markdown file with unaligned table pipes. "
                    "PostToolUse handler reformats the file so pipes are "
                    "vertically aligned and delimiter row matches cell widths."
                ),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r"Reformatted markdown in doc\.md.*table pipes"],
                safety_notes=(
                    "Creates a temporary markdown file inside the gitignored acceptance "
                    "directory for formatting test"
                ),
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p untracked/acceptance/{_FIXTURE_DIR}"],
                cleanup_commands=[f"rm -rf untracked/acceptance/{_FIXTURE_DIR}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
