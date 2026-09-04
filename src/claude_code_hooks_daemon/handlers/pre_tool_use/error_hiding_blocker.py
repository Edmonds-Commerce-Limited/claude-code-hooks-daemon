"""ErrorHidingBlockerHandler - blocks error-hiding patterns in written code.

Inspects content written via Write or Edit tools and denies if the new content
contains language-specific patterns that suppress errors silently.

Uses Strategy Pattern: all language-specific pattern logic is delegated to
ErrorHidingStrategy implementations.  The handler has ZERO language awareness.
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

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
from claude_code_hooks_daemon.core.utils import get_file_path
from claude_code_hooks_daemon.strategies.error_hiding.protocol import (
    ErrorHidingPattern,
    ErrorHidingStrategy,
)
from claude_code_hooks_daemon.strategies.error_hiding.registry import (
    ErrorHidingStrategyRegistry,
)
from claude_code_hooks_daemon.utils.path_exclusion import (
    handler_excludes_path,
    vendored_exclude_globs,
)

if TYPE_CHECKING:
    from claude_code_hooks_daemon.core.project_layout import ProjectLayout

# Config key hint shown in the denial message
_CONFIG_HINT_HANDLER = "handlers.pre_tool_use.error_hiding_blocker"

# Single rule (Plan 00116): every language's error-hiding pattern is the same
# concept -- the language dimension lives in the strategy registry.
_ERROR_HIDING_RULE = Rule(
    rule_id=RuleID.ERROR_HIDING,
    blocked="an error-hiding pattern (bare except, || true, empty catch, _ = err, ...)",
    why="Silent failure makes bugs invisible, delays diagnosis, and corrupts state",
    fix="Handle the error explicitly: log it, return it, or propagate it",
    verbose=(
        "WHY BLOCKED:\n"
        "  Error hiding is a cardinal sin. Silent failure makes bugs invisible,\n"
        "  delays diagnosis, and corrupts system state without warning.\n\n"
        f"To disable: {_CONFIG_HINT_HANDLER}  (set enabled: false)"
    ),
)

# Built-in default excludes so this handler matches its siblings' behaviour:
# generated/vendored trees and test-fixture code (which legitimately contains
# error-hiding patterns) are never scanned. Clients extend this via the
# ``exclude_paths`` option and/or the project-level ``daemon.exclude_paths``.
#
# Plan 00288 Task 3.2: the vendored/build half derives from the canonical
# core (measurement doc §3, ACCEPT all deltas); the fixture-semantics half
# is a different category and stays local to this handler.
_FIXTURE_EXCLUDE_GLOBS: Final[tuple[str, ...]] = (
    "**/tests/fixtures/**",
    "**/tests/assets/**",
    "**/__fixtures__/**",
)


def _default_exclude_globs(layout: "ProjectLayout | None") -> tuple[str, ...]:
    """Built-in excludes for one dispatch: vendored dirs + fixture dirs.

    Computed per call, not at module import (Plan 00331): the vendored half
    is configurable via ``layout.vendor_dirs``, and freezing it at import
    time meant a project could declare a directory vendored and this handler
    would still judge every file inside it. The fixture half has no config
    axis and is a plain constant.
    """
    vendored = vendored_exclude_globs(None if layout is None else layout.vendor_dirs)
    return vendored + _FIXTURE_EXCLUDE_GLOBS


class ErrorHidingBlockerHandler(PreToolUseHandlerBase):
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
        # Client-configured exclude globs (Plan 00150); project-level default is
        # injected as _project_exclude_paths by the registry.
        self._exclude_paths: list[str] | None = None
        self._formatter = RuleFormatter()

    # ------------------------------------------------------------------
    # Language filter (applied lazily on first use)
    # ------------------------------------------------------------------

    def _apply_language_filter(self) -> None:
        """Apply language filter to registry on first use (lazy)."""
        if self._languages_applied:
            return
        self._languages_applied = True
        effective_languages = self._languages or self._project_languages
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

        if self._is_excluded(file_path):
            return False

        strategy = self._registry.get_strategy(file_path)
        if strategy is None:
            return False

        content = self._get_new_content(hook_input, tool_name)
        if not content:
            return False

        return self._find_violation(content, strategy) is not None

    def _is_excluded(self, file_path: str) -> bool:
        """Return True if file_path matches a default or client-configured exclude glob."""
        layout = self.layout_for(file_path)
        return handler_excludes_path(
            file_path,
            handler_patterns=self._exclude_paths,
            project_patterns=self._project_exclude_paths,
            defaults=_default_exclude_globs(layout),
            layout=layout,
        )

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        """Deny write if content contains an error-hiding pattern, allow otherwise."""
        file_path = get_file_path(hook_input)
        tool_name = hook_input.get(HookInputField.TOOL_NAME, "")

        if not file_path:
            return GatingResult(decision=Decision.ALLOW)

        strategy = self._registry.get_strategy(file_path)
        if strategy is None:
            return GatingResult(decision=Decision.ALLOW)

        content = self._get_new_content(hook_input, tool_name)
        violation = self._find_violation(content or "", strategy)
        if violation is None:
            return GatingResult(decision=Decision.ALLOW)

        return GatingResult(
            decision=Decision.DENY,
            reason=self._format_reason(hook_input, violation, strategy.language_name, file_path),
        )

    def get_rules(self) -> list[Rule]:
        """Return the single Rule backing this handler's blocking behaviour."""
        return [_ERROR_HIDING_RULE]

    def get_claude_md(self) -> str | None:
        return (
            "## error_hiding_blocker — error-suppression patterns are blocked\n\n"
            "A `Write`/`Edit` of code that silently swallows errors is blocked. "
            "All errors must be handled explicitly.\n\n"
            "**Blocked patterns (examples)**:\n"
            "- Python: bare `except` clauses with an empty body, "
            "catching and discarding all exceptions\n"
            "- Shell: redirecting stderr to `/dev/null` to silence failures, "
            "`|| true` to suppress non-zero exit codes\n"
            "- JavaScript/TypeScript: empty `catch` blocks that swallow exceptions\n"
            "- Go: `_ = err` (discarding error return values without handling)\n\n"
            "**Required action**: Handle errors explicitly — log them, return them "
            "to the caller, or propagate them. Silent error suppression masks bugs "
            "and makes debugging impossible.\n\n"
            "**Excluded paths**: vendor/, node_modules/, and test-fixture dirs "
            "(tests/fixtures/, tests/assets/, __fixtures__/) are skipped by default. "
            "Exempt more paths with glob patterns via "
            "`handlers.pre_tool_use.error_hiding_blocker.options.exclude_paths` or the "
            "project-wide `daemon.exclude_paths` — use these for fixtures of "
            "deliberately-broken code instead of disabling the handler."
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

    def _format_reason(
        self,
        hook_input: dict[str, Any],
        pattern: ErrorHidingPattern,
        language: str,
        file_path: str,
    ) -> str:
        """Build a human-readable denial message for the matched pattern.

        Verbosity is decided per (transcript_path, rule_id) via the shared
        DisclosureTracker (Plan 00116, Decision G). The per-invocation
        diagnostic (file, language, matched pattern, example, suggestion) is
        dynamic and always fully present -- only the surrounding "why this
        is blocked" teaching prose goes terse on repeat fires.
        """
        filename = Path(file_path).name if file_path else "file"
        dynamic_detail = (
            f"FILE: {filename}\n"
            f"LANGUAGE: {language}\n"
            f"PATTERN: {pattern.name}\n\n"
            f"EXAMPLE OF BLOCKED CODE:\n"
            f"  {pattern.example}\n\n"
            f"INSTEAD:\n"
            f"  {pattern.suggestion}"
        )

        rule = _ERROR_HIDING_RULE
        transcript_path = hook_input.get(HookInputField.TRANSCRIPT_PATH)
        tracker = get_data_layer().disclosure

        if transcript_path and tracker.was_disclosed(transcript_path, rule.rule_id):
            message = self._formatter.terse(rule)
        else:
            if transcript_path:
                tracker.mark_disclosed(transcript_path, rule.rule_id)
            message = self._formatter.verbose(rule)

        return f"{message}\n\n{dynamic_detail}"
