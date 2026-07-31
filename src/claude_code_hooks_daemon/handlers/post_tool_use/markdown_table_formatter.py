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

from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_file_path
from claude_code_hooks_daemon.plan_qa.paths import is_journal_file
from claude_code_hooks_daemon.utils.cli_command import daemon_cli_command
from claude_code_hooks_daemon.utils.markdown_format import format_markdown_text

# Extensions treated as markdown (lowercase match).
_MARKDOWN_EXTENSIONS: tuple[str, ...] = (".md", ".markdown")


class MarkdownTableFormatterHandler(Handler):
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

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Reformat the markdown file in place if its content changes."""
        file_path = get_file_path(hook_input)
        if not file_path:
            return HookResult(decision=Decision.ALLOW)

        path = Path(file_path)
        if not path.exists():
            return HookResult(decision=Decision.ALLOW)

        try:
            before = path.read_text(encoding="utf-8")
            formatted = format_markdown_text(before)
        except Exception as exc:
            # FAIL SAFE: mdformat can raise many parser/IO/unicode errors.
            # Never crash the PostToolUse dispatch chain — surface the error
            # as advisory context and allow the write through unchanged.
            return HookResult(
                decision=Decision.ALLOW,
                context=[
                    f"markdown_table_formatter failed on {path.name}: {exc}",
                ],
            )

        if formatted == before:
            return HookResult(decision=Decision.ALLOW)

        path.write_text(formatted, encoding="utf-8")
        return HookResult(
            decision=Decision.ALLOW,
            context=[f"Reformatted markdown tables in {path.name}"],
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
            "**Exempt:** anything under a plan's `JOURNAL/` directory is NEVER "
            "reformatted — day-files (`JOURNAL/NNNNN-Journal-YY-MM-DD.md`, Plan 00163) "
            "and any other file in there. A journal is an append-only, byte-stable log; "
            "rewriting it would trip the `journal-append-only` check. The exemption is "
            "by LOCATION as well as by filename, so a mis-named day-file is still safe.\n"
            "\n"
            "**Ad-hoc formatting of existing files:**\n"
            "\n"
            "```\n"
            f"{daemon_cli_command('format-markdown', '<path>')}\n"
            "```\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests for the handler — Write/Edit of .md files."""
        from claude_code_hooks_daemon.core import AcceptanceTest, RecommendedModel, TestType

        return [
            AcceptanceTest(
                title="Markdown table auto-alignment after Write",
                command=(
                    "Use the Write tool to create /tmp/acceptance-test-mdformat/doc.md "
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
                expected_message_patterns=[r"Reformatted markdown tables"],
                safety_notes="Creates temporary markdown file in /tmp for formatting test",
                test_type=TestType.ADVISORY,
                setup_commands=["mkdir -p /tmp/acceptance-test-mdformat"],
                cleanup_commands=["rm -rf /tmp/acceptance-test-mdformat"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=True,
            ),
        ]
