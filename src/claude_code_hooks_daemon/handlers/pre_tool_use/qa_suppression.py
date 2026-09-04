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
from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core import Decision, GatingResult, get_data_layer
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase
from claude_code_hooks_daemon.core.rule import Rule, RuleFormatter
from claude_code_hooks_daemon.core.utils import get_file_content, get_file_path
from claude_code_hooks_daemon.strategies.qa_suppression import (
    QaSuppressionStrategyRegistry,
)
from claude_code_hooks_daemon.strategies.qa_suppression.protocol import (
    QaSuppressionStrategy,
)
from claude_code_hooks_daemon.utils.path_exclusion import (
    handler_excludes_path,
)

# Maximum number of issues to show in error message
_MAX_ISSUES_SHOWN = 5

# Single rule (Plan 00116): every language's suppression directive is the
# same concept, "QA suppression" -- the language dimension lives in the
# strategy registry, not in a per-language RuleID.
_QA_SUPPRESSION_RULE = Rule(
    rule_id=RuleID.QA_SUPPRESSION,
    blocked="a QA suppression directive (noqa, type: ignore, eslint-disable, ...)",
    why="Suppression comments hide real problems and create technical debt",
    fix="Fix the underlying issue; do not suppress the warning",
    verbose=(
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
        "Quality tools exist to prevent bugs. Fix the code, don't silence the tool."
    ),
)


class QaSuppressionHandler(PreToolUseHandlerBase):
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
        # Client-configured exclude globs (Plan 00150), layered on top of the
        # per-language skip_directories; project default injected by registry.
        self._exclude_paths: list[str] | None = None
        self._formatter = RuleFormatter()

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
        effective_languages = self._languages or self._project_languages
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

        # Skip client-configured / project-level exclude globs (Plan 00150).
        if self._is_excluded(file_path):
            return False

        content = self._get_content(hook_input)
        if not content:
            return False

        # Check for forbidden patterns
        for pattern in strategy.forbidden_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True

        return False

    def _is_excluded(self, file_path: str) -> bool:
        """Return True if file_path matches a client-configured exclude glob."""
        return handler_excludes_path(
            file_path,
            handler_patterns=self._exclude_paths,
            project_patterns=self._project_exclude_paths,
            layout=self.layout_for(file_path),
        )

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Check content for QA suppression patterns, deny if found."""
        file_path = get_file_path(hook_input)
        if not file_path:
            return GatingResult(decision=Decision.ALLOW)

        strategy = self._registry.get_strategy(file_path)
        if strategy is None:
            return GatingResult(decision=Decision.ALLOW)

        content = self._get_content(hook_input)
        if not content:
            return GatingResult(decision=Decision.ALLOW)

        # Find all matching forbidden patterns
        issues: list[str] = []
        for pattern in strategy.forbidden_patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                issues.append(match.group(0))

        if not issues:
            return GatingResult(decision=Decision.ALLOW)

        return self._build_deny_result(hook_input, file_path, strategy, issues)

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's blocking behaviour."""
        return [_QA_SUPPRESSION_RULE]

    def _build_deny_result(
        self,
        hook_input: dict[str, Any],
        file_path: str,
        strategy: QaSuppressionStrategy,
        issues: list[str],
    ) -> GatingResult:
        """Build a DENY result with language-appropriate error message.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G). The per-invocation
        diagnostic (file, matched suppression comments, tool resources) is
        dynamic and always fully present -- only the surrounding "why this
        is blocked" teaching prose goes terse on repeat fires.
        """
        # Build resources section from strategy
        resources_text = "\n".join(
            f"  - {tool}: {url}"
            for tool, url in zip(strategy.tool_names, strategy.tool_docs_urls, strict=False)
        )

        issues_text = "\n".join(f"  - {issue}" for issue in issues[:_MAX_ISSUES_SHOWN])

        dynamic_detail = (
            f"{strategy.language_name} QA suppression comments are not allowed\n\n"
            f"File: {file_path}\n\n"
            f"Found {len(issues)} suppression comment(s):\n"
            f"{issues_text}\n\n"
            f"Resources:\n{resources_text}"
        )

        rule = _QA_SUPPRESSION_RULE
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, rule.rule_id):
            message = self._formatter.terse(rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, rule.rule_id)
            message = self._formatter.verbose(rule)

        return GatingResult(decision=Decision.DENY, reason=f"{message}\n\n{dynamic_detail}")

    def get_claude_md(self) -> str | None:
        return (
            "## qa_suppression — QA suppression annotations are blocked\n\n"
            "A `Write`/`Edit` that puts QA suppression directives into a source file "
            "is blocked, across all "
            "supported languages. Fix the underlying code issue instead.\n\n"
            "**Blocked annotation types (by language)**:\n"
            "- Python: `noqa` directives, `type: ignore` annotations\n"
            "- JavaScript/TypeScript: `eslint-disable` inline directives\n"
            "- Go: `nolint` directives (golangci-lint)\n"
            "- PHP: `phpstan-ignore`, `psalm-suppress` annotations\n"
            "- Java/Kotlin: `@SuppressWarnings`, `@Suppress` annotations\n"
            "- C#: `pragma warning disable` directives\n"
            "- Rust: `allow(...)` attributes anywhere in the file "
            "(item-level `#[allow(...)]` and crate-level `#![allow(...)]`)\n\n"
            "**Required action**: Fix the code so QA passes without suppression. "
            "If a suppression is genuinely necessary, ask the user to add it manually — "
            "this signals a conscious decision rather than a shortcut.\n\n"
            "**Excluded paths**: per-language vendor/build/node_modules dirs are "
            "skipped by default. Exempt more paths with glob patterns via "
            "`handlers.pre_tool_use.qa_suppression.options.exclude_paths` or the "
            "project-wide `daemon.exclude_paths` — use these for fixtures that must "
            "contain suppression annotations."
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
