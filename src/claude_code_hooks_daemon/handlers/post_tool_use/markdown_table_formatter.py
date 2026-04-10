"""MarkdownTableFormatterHandler - auto-format markdown tables via mdformat + mdformat-gfm.

Runs after Write/Edit of .md files, reformats the content with mdformat so tables
have aligned pipes and consistent column widths, then writes back only if changed.

Applies two mitigations to constrain mdformat's default behaviour:

1. `options={"number": True}` preserves consecutive ordered-list numbering
   (1. 2. 3.) instead of renumbering everything to 1.
2. Post-processes mdformat's output to restore `---` thematic breaks
   (mdformat hardcodes 70 underscores for thematic breaks with no config option).
"""

from pathlib import Path
from typing import Any

import mdformat

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_file_path

# Extensions treated as markdown (lowercase match).
_MARKDOWN_EXTENSIONS: tuple[str, ...] = (".md", ".markdown")

# mdformat options: preserve consecutive ordered-list numbering so 1. 2. 3.
# doesn't get renumbered to 1. 1. 1. Without this the default renumbers
# every item to 1.
_MDFORMAT_OPTIONS: dict[str, Any] = {"number": True}

# mdformat extensions: enable GFM tables, strikethrough, task lists, autolinks.
_MDFORMAT_EXTENSIONS: set[str] = {"gfm"}

# mdformat hardcodes thematic breaks as 70 underscores. Post-process to
# convert them back to the more common `---` form.
_THEMATIC_BREAK_UNDERSCORES = "_" * 70
_THEMATIC_BREAK_DASHES = "---"


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
            formatted = mdformat.text(
                before,
                extensions=_MDFORMAT_EXTENSIONS,
                options=_MDFORMAT_OPTIONS,
            )
            formatted = self._restore_thematic_breaks(formatted)
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

    @staticmethod
    def _restore_thematic_breaks(content: str) -> str:
        """Replace mdformat's 70-underscore thematic break with `---`."""
        return "\n".join(
            _THEMATIC_BREAK_DASHES if line == _THEMATIC_BREAK_UNDERSCORES else line
            for line in content.split("\n")
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
            "**Ad-hoc formatting of existing files:**\n"
            "\n"
            "```\n"
            "$PYTHON -m claude_code_hooks_daemon.daemon.cli format-markdown <path>\n"
            "```\n"
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Acceptance tests for the handler — Write/Edit of .md files."""
        return []
