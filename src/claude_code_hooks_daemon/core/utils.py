"""Utility functions for hook handlers."""

from pathlib import Path
from typing import Any, cast

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.utils.command_evasion import normalise_line_continuations


def get_bash_command(hook_input: dict[str, Any]) -> str | None:
    """Extract bash command from hook input, or None if not Bash tool.

    Args:
        hook_input: Hook input dictionary

    Returns:
        Bash command string, or None if not a Bash tool call
    """
    if hook_input.get("tool_name") != "Bash":
        return None
    tool_input: dict[str, Any] = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")
    # A Bash call can carry command=None (or an empty string). Both must pass
    # straight through: callers test falsiness, and normalising None would
    # raise inside the regex. Only real text is normalised.
    if not command or not isinstance(command, str):
        return cast("str | None", command)
    # Line continuations are normalised HERE, at the single point where commands
    # enter the daemon, so no handler pattern has to know about them. A command
    # split across lines with `\<newline>` reached guards in a form none of their
    # patterns matched — `\s+` does not match a backslash — so `git \<newline>
    # reset --hard` was allowed while the one-line form was denied.
    return normalise_line_continuations(command)


def get_file_path(hook_input: dict[str, Any]) -> str | None:
    """Extract file path from hook input, or None if not Write/Edit.

    Args:
        hook_input: Hook input dictionary

    Returns:
        File path string, or None if not a Write/Edit tool call
    """
    if hook_input.get("tool_name") not in ["Write", "Edit"]:
        return None
    tool_input: dict[str, Any] = hook_input.get("tool_input", {})
    return cast("str", tool_input.get("file_path", ""))


def get_file_content(hook_input: dict[str, Any]) -> str | None:
    """Extract file content from hook input, or None if not Write/Edit.

    Args:
        hook_input: Hook input dictionary

    Returns:
        File content string, or None if not a Write/Edit tool call
    """
    if hook_input.get("tool_name") not in ["Write", "Edit"]:
        return None
    tool_input: dict[str, Any] = hook_input.get("tool_input", {})
    return cast("str", tool_input.get("content", ""))


def get_workspace_root() -> Path:
    """Find project root by searching upward for directory with BOTH .git AND CLAUDE.

    This allows handlers to work in any directory structure, not just hardcoded paths.
    Prevents bugs from hardcoded absolute paths that only work in specific environments.

    Requires BOTH markers to ensure we find the actual project root, not a subdirectory
    that happens to have one marker.

    Returns:
        Path to project root directory
    """
    # Start from this file's location
    current = Path(__file__).resolve()

    # Search upward through parent directories
    for parent in [current, *current.parents]:
        # Require BOTH .git AND CLAUDE to exist
        if (parent / ".git").exists() and (parent / "CLAUDE").exists():
            return parent

    # Fallback: use ProjectContext (single source of truth)
    return ProjectContext.project_root()
