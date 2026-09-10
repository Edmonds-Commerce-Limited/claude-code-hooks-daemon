"""The content a file WOULD have after a Write/Edit tool call.

Shared by every PreToolUse gate that judges a document's post-edit state
(``plan_qa_edit``, ``plan_close_approval``): for Write that is the payload
itself; for Edit the old/new replacement is applied to the current text. One
helper, so two gates can never disagree about what an Edit produces.
"""

from __future__ import annotations

from typing import Any, Final

from claude_code_hooks_daemon.constants import HookInputField, ToolName

_FIELD_CONTENT: Final[str] = "content"
_FIELD_OLD_STRING: Final[str] = "old_string"
_FIELD_NEW_STRING: Final[str] = "new_string"
_FIELD_REPLACE_ALL: Final[str] = "replace_all"

_SINGLE_REPLACEMENT: Final[int] = 1


def would_be_content(hook_input: dict[str, Any], *, current: str | None) -> str | None:
    """Return the post-call content, or ``None`` when there is nothing to judge.

    ``None`` means the tool call cannot produce a file: an Edit with no
    current text to apply to, an empty ``old_string``, or an ``old_string``
    the file does not contain. Claude Code fails such a call with its own
    error, so a gate has nothing to decide.

    Args:
        hook_input: The PreToolUse payload.
        current: The file's present content, or ``None`` if it does not exist
            (or could not be read).
    """
    tool_input = hook_input.get(HookInputField.TOOL_INPUT, {})
    if hook_input.get(HookInputField.TOOL_NAME) == ToolName.WRITE:
        raw: Any = tool_input.get(_FIELD_CONTENT, "")
        return str(raw)

    if current is None:
        return None
    old_string = str(tool_input.get(_FIELD_OLD_STRING, ""))
    new_string = str(tool_input.get(_FIELD_NEW_STRING, ""))
    if not old_string or old_string not in current:
        return None
    if bool(tool_input.get(_FIELD_REPLACE_ALL, False)):
        return current.replace(old_string, new_string)
    return current.replace(old_string, new_string, _SINGLE_REPLACEMENT)
