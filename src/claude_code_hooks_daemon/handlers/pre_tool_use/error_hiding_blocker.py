"""ErrorHidingBlockerHandler - blocks error-hiding patterns in written code.

Inspects content written via Write or Edit tools and denies if the new content
contains language-specific patterns that suppress errors silently.

Uses Strategy Pattern: all language-specific pattern logic is delegated to
ErrorHidingStrategy implementations.  The handler has ZERO language awareness.
"""

import re
from pathlib import Path
from typing import Any, cast

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_file_path
from claude_code_hooks_daemon.strategies.error_hiding.protocol import (
    ErrorHidingPattern,
    ErrorHidingStrategy,
)
from claude_code_hooks_daemon.strategies.error_hiding.registry import (
    ErrorHidingStrategyRegistry,
)

# Config key hint shown in the denial message
_CONFIG_HINT_HANDLER = "handlers.pre_tool_use.error_hiding_blocker"


class ErrorHidingBlockerHandler(Handler):
    """Block error-hiding patterns in code written via Write or Edit tools.

    Inspects the content of any Write or Edit tool call. If the new content
    matches a language-specific error-hiding pattern (e.g. ``|| true`` in shell,
    ``except: pass`` in Python), the write is denied with an explanatory message.

    Language-specific patterns are managed by ErrorHidingStrategy implementations
    in the error_hiding strategy domain.  The handler orchestrates without any
    knowledge of specific languages.

    Configuration options (set via YAML config):
        languages: list[str] | None — Restrict enforcement to specific languages.
            If unset or empty, ALL registered languages are enforced (default).
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.ERROR_HIDING_BLOCKER,
            priority=Priority.ERROR_HIDING_BLOCKER,
            tags=[
                HandlerTag.SAFETY,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
                HandlerTag.MULTI_LANGUAGE,
            ],
        )
        self._registry = ErrorHidingStrategyRegistry.create_default()
        # Set by HandlerRegistry via setattr from config options
        self._languages: list[str] | None = None
        self._languages_applied: bool = False

    # ------------------------------------------------------------------
    # Language filter (applied lazily on first use)
    # ------------------------------------------------------------------

    def _apply_language_filter(self) -> None:
        """Apply language filter to registry on first use (lazy)."""
        if self._languages_applied:
            return
        self._languages_applied = True
        effective_languages = self._languages or getattr(self, "_project_languages", None)
        if effective_languages:
            self._registry.filter_by_languages(effective_languages)

    # ------------------------------------------------------------------
    # Handler interface
    # ------------------------------------------------------------------

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Return True if the content being written contains an error-hiding pattern.

        Only matches Write and Edit tool calls for files with a registered strategy.
        Returns False for all other tools, unknown extensions, or empty content.
        """
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

        content = self._get_new_content(hook_input, tool_name)
        if not content:
            return False

        return self._find_violation(content, strategy) is not None

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Deny write if content contains an error-hiding pattern, allow otherwise."""
        file_path = get_file_path(hook_input)
        tool_name = hook_input.get(HookInputField.TOOL_NAME, "")

        if not file_path:
            return HookResult(decision=Decision.ALLOW)

        strategy = self._registry.get_strategy(file_path)
        if strategy is None:
            return HookResult(decision=Decision.ALLOW)

        content = self._get_new_content(hook_input, tool_name)
        violation = self._find_violation(content or "", strategy)
        if violation is None:
            return HookResult(decision=Decision.ALLOW)

        return HookResult(
            decision=Decision.DENY,
            reason=self._format_reason(violation, strategy.language_name, file_path),
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests aggregated from all registered strategies."""
        tests: list[Any] = []
        seen_languages: set[str] = set()
        for strategy in self._registry._strategies.values():
            if strategy.language_name in seen_languages:
                continue
            seen_languages.add(strategy.language_name)
            if hasattr(strategy, "get_acceptance_tests"):
                tests.extend(strategy.get_acceptance_tests())
        return tests

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_new_content(self, hook_input: dict[str, Any], tool_name: str) -> str | None:
        """Extract the new content being written from the hook input.

        For Write: returns the 'content' field.
        For Edit: returns the 'new_string' field.
        """
        tool_input: dict[str, Any] = hook_input.get(HookInputField.TOOL_INPUT, {})
        if tool_name == ToolName.WRITE:
            return cast("str", tool_input.get("content", ""))
        if tool_name == ToolName.EDIT:
            return cast("str", tool_input.get("new_string", ""))
        return None

    def _find_violation(
        self, content: str, strategy: ErrorHidingStrategy
    ) -> ErrorHidingPattern | None:
        """Return the first matching error-hiding pattern, or None if content is clean."""
        for pattern in strategy.patterns:
            if re.search(pattern.regex, content, re.MULTILINE):
                return pattern
        return None

    def _format_reason(self, pattern: ErrorHidingPattern, language: str, file_path: str) -> str:
        """Build a human-readable denial message for the matched pattern."""
        filename = Path(file_path).name if file_path else "file"
        return (
            f"BLOCKED: Error-hiding pattern detected\n\n"
            f"FILE: {filename}\n"
            f"LANGUAGE: {language}\n"
            f"PATTERN: {pattern.name}\n\n"
            f"EXAMPLE OF BLOCKED CODE:\n"
            f"  {pattern.example}\n\n"
            f"WHY BLOCKED:\n"
            f"  Error hiding is a cardinal sin. Silent failure makes bugs invisible,\n"
            f"  delays diagnosis, and corrupts system state without warning.\n\n"
            f"INSTEAD:\n"
            f"  {pattern.suggestion}\n\n"
            f"To disable: {_CONFIG_HINT_HANDLER}  (set enabled: false)"
        )
