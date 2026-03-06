"""SecurityAntipatternHandler - blocks security antipatterns in written code.

Inspects content written via Write or Edit tools and denies if the new content
contains security antipatterns defined by registered strategies.

Uses Strategy Pattern: all language-specific pattern logic is delegated to
SecurityStrategy implementations.  The handler has ZERO language awareness.

OWASP coverage: A02 (Cryptographic Failures), A03 (Injection).
"""

import re
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
from claude_code_hooks_daemon.strategies.security.common import should_skip
from claude_code_hooks_daemon.strategies.security.protocol import SecurityPattern
from claude_code_hooks_daemon.strategies.security.registry import (
    SecurityStrategyRegistry,
)

# Config key hint shown in the denial message
_CONFIG_HINT_HANDLER = "handlers.pre_tool_use.security_antipattern"


class SecurityAntipatternHandler(Handler):
    """Block Write/Edit of files containing security antipatterns.

    Scans content being written for security antipatterns defined by
    registered SecurityStrategy implementations.  The handler orchestrates
    without any knowledge of specific languages or pattern types.

    Excludes vendor code, test fixtures, documentation, and rule definition
    files via the shared should_skip() utility.

    Configuration options (set via YAML config):
        languages: list[str] | None — Restrict enforcement to specific languages.
            If unset or empty, ALL registered strategies are enforced (default).
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.SECURITY_ANTIPATTERN,
            priority=Priority.SECURITY_ANTIPATTERN,
            tags=[
                HandlerTag.SAFETY,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
                HandlerTag.FILE_OPS,
            ],
        )
        self._registry = SecurityStrategyRegistry.create_default()
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
        """Return True if the content being written contains a security antipattern.

        Only matches Write and Edit tool calls for files not in skip directories.
        Returns False for all other tools or empty content.
        """
        self._apply_language_filter()

        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in (ToolName.WRITE, ToolName.EDIT):
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        if should_skip(file_path):
            return False

        content = self._get_new_content(hook_input, tool_name)
        if not content:
            return False

        strategies = self._registry.get_strategies(file_path)
        for strategy in strategies:
            for pattern in strategy.patterns:
                if re.search(pattern.regex, content):
                    return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Deny write if content contains security antipatterns, allow otherwise."""
        file_path = get_file_path(hook_input)
        tool_name = hook_input.get(HookInputField.TOOL_NAME, "")

        if not file_path:
            return HookResult(decision=Decision.ALLOW)

        content = self._get_new_content(hook_input, tool_name)
        if not content:
            return HookResult(decision=Decision.ALLOW)

        issues = self._find_all_violations(content, file_path)
        if not issues:
            return HookResult(decision=Decision.ALLOW)

        return HookResult(
            decision=Decision.DENY,
            reason=self._format_reason(issues, file_path),
        )

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests aggregated from all registered strategies."""
        tests: list[Any] = []
        seen_languages: set[str] = set()
        for strategy in self._registry.all_strategies:
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

    def _find_all_violations(self, content: str, file_path: str) -> list[SecurityPattern]:
        """Return all matching security patterns across all applicable strategies."""
        violations: list[SecurityPattern] = []
        strategies = self._registry.get_strategies(file_path)
        for strategy in strategies:
            for pattern in strategy.patterns:
                if re.search(pattern.regex, content):
                    violations.append(pattern)
        return violations

    def _format_reason(self, issues: list[SecurityPattern], file_path: str) -> str:
        """Build a human-readable denial message for matched patterns."""
        issues_text = "\n".join(f"  - [{issue.owasp}] {issue.name}" for issue in issues)

        # Collect unique suggestions
        suggestions = []
        seen_suggestions: set[str] = set()
        for issue in issues:
            if issue.suggestion not in seen_suggestions:
                seen_suggestions.add(issue.suggestion)
                suggestions.append(f"  - {issue.suggestion}")
        suggestions_text = "\n".join(suggestions)

        return (
            f"SECURITY ANTIPATTERN BLOCKED\n\n"
            f"File: {file_path}\n\n"
            f"Issues detected ({len(issues)}):\n"
            f"{issues_text}\n\n"
            "These patterns indicate security vulnerabilities (OWASP A02/A03).\n\n"
            f"CORRECT APPROACH:\n"
            f"{suggestions_text}\n\n"
            "If this is test fixture code, place it in tests/fixtures/ or tests/assets/.\n"
            "If this is rule documentation, place it in docs/ or eslint-rules/.\n\n"
            f"To disable: {_CONFIG_HINT_HANDLER}  (set enabled: false)"
        )
