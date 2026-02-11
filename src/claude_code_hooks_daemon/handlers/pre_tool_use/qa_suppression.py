"""QaSuppressionHandler - unified multi-language QA suppression blocker.

Uses Strategy Pattern: all language-specific logic is delegated to QaSuppressionStrategy
implementations. The handler itself has ZERO language awareness.

Replaces the individual per-language handlers (PythonQaSuppressionBlocker,
GoQaSuppressionBlocker, PhpQaSuppressionBlocker, EslintDisableHandler).
"""

import re
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_file_content, get_file_path
from claude_code_hooks_daemon.strategies.qa_suppression import (
    QaSuppressionStrategyRegistry,
)
from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)

# Maximum number of issues to show in error message
_MAX_ISSUES_SHOWN = 5


class QaSuppressionHandler(Handler):
    """Block QA suppression comments across all supported languages.

    Uses Strategy Pattern: delegates ALL language-specific decisions to
    QaSuppressionStrategy implementations registered in the
    QaSuppressionStrategyRegistry. The handler orchestrates the workflow
    without any knowledge of specific languages.

    Supported languages are determined by registered strategies (currently 11:
    Python, Go, JavaScript/TypeScript, PHP, Rust, Java, C#, Kotlin, Ruby, Swift, Dart).
    Unknown file extensions are allowed through without blocking.

    Configuration options (set via config YAML):
        languages: list[str] | None - Restrict enforcement to specific languages.
            If not set or empty, ALL registered languages are enforced (default).
            Example: ["python", "go", "javascript/typescript"]
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.QA_SUPPRESSION,
            priority=Priority.QA_SUPPRESSION,
            tags=[
                HandlerTag.MULTI_LANGUAGE,
                HandlerTag.QA_ENFORCEMENT,
                HandlerTag.BLOCKING,
                HandlerTag.TERMINAL,
            ],
        )
        self._registry = QaSuppressionStrategyRegistry.create_default()
        # Config option: restrict to specific languages (None = ALL languages)
        # Set by registry via setattr after __init__
        self._languages: list[str] | None = None
        self._languages_applied: bool = False

    def _apply_language_filter(self) -> None:
        """Apply language filter to registry on first use (lazy).

        Config options are set via setattr AFTER __init__, so we must defer
        filtering until first matches()/handle() call. This is idempotent -
        only applies once via the _languages_applied guard.

        Priority: handler-level _languages > project-level _project_languages > ALL
        """
        if self._languages_applied:
            return
        self._languages_applied = True
        # Handler-level override takes priority over project-level default
        effective_languages = self._languages or getattr(self, "_project_languages", None)
        if effective_languages:
            self._registry.filter_by_languages(effective_languages)

    def _get_content(self, hook_input: dict[str, Any]) -> str:
        """Extract content to check from hook input, handling Write vs Edit."""
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name == ToolName.EDIT:
            tool_input: dict[str, str] = hook_input.get(HookInputField.TOOL_INPUT, {})
            result: str = tool_input.get("new_string", "")
            return result
        content = get_file_content(hook_input)
        return content or ""

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if writing QA suppression comments to a known language file.

        Delegates all language-specific checks to the matched strategy:
        - extension matching via registry
        - skip_directories for vendor/build/node_modules
        - forbidden_patterns for language-specific suppressions
        """
        self._apply_language_filter()

        # Only match Write and Edit tools
        tool_name = hook_input.get(HookInputField.TOOL_NAME)
        if tool_name not in (ToolName.WRITE, ToolName.EDIT):
            return False

        file_path = get_file_path(hook_input)
        if not file_path:
            return False

        # Find strategy for this file's language
        strategy = self._registry.get_strategy(file_path)
        if strategy is None:
            return False  # Unknown language - allow through

        # Skip configured directories (vendor, build, node_modules, etc.)
        if any(skip_dir in file_path for skip_dir in strategy.skip_directories):
            return False

        content = self._get_content(hook_input)
        if not content:
            return False

        # Check for forbidden patterns
        for pattern in strategy.forbidden_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True

        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Check content for QA suppression patterns, deny if found."""
        file_path = get_file_path(hook_input)
        if not file_path:
            return HookResult(decision=Decision.ALLOW)

        strategy = self._registry.get_strategy(file_path)
        if strategy is None:
            return HookResult(decision=Decision.ALLOW)

        content = self._get_content(hook_input)
        if not content:
            return HookResult(decision=Decision.ALLOW)

        # Find all matching forbidden patterns
        issues: list[str] = []
        for pattern in strategy.forbidden_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                issues.append(match.group(0))

        if not issues:
            return HookResult(decision=Decision.ALLOW)

        return self._build_deny_result(file_path, strategy, issues)

    @staticmethod
    def _build_deny_result(
        file_path: str,
        strategy: QaSuppressionStrategy,
        issues: list[str],
    ) -> HookResult:
        """Build a DENY result with language-appropriate error message."""
        # Build resources section from strategy
        resources_text = "\n".join(
            f"  - {tool}: {url}" for tool, url in zip(strategy.tool_names, strategy.tool_docs_urls)
        )

        issues_text = "\n".join(f"  - {issue}" for issue in issues[:_MAX_ISSUES_SHOWN])

        return HookResult(
            decision=Decision.DENY,
            reason=(
                f"QA SUPPRESSION BLOCKED: {strategy.language_name} QA suppression "
                f"comments are not allowed\n\n"
                f"File: {file_path}\n\n"
                f"Found {len(issues)} suppression comment(s):\n"
                f"{issues_text}\n\n"
                "WHY: Suppression comments hide real problems and create technical debt.\n"
                "Type errors, style violations, and complexity warnings exist for good reason.\n\n"
                "CORRECT APPROACH:\n"
                "  1. Fix the underlying issue (don't suppress)\n"
                "  2. Add proper type annotations instead of suppressing type errors\n"
                "  3. Refactor code to meet quality standards\n"
                "  4. If rule is genuinely wrong, update project config\n"
                "  5. For test-specific code, ensure file is in tests/ directory\n"
                "  6. For legacy code requiring suppression:\n"
                "     - Add detailed comment explaining WHY suppression is needed\n"
                "     - Create ticket to fix properly\n"
                "     - Link ticket in comment\n\n"
                "Quality tools exist to prevent bugs. Fix the code, don't silence the tool.\n\n"
                f"Resources:\n{resources_text}"
            ),
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
