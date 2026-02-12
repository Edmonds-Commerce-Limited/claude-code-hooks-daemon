"""LintOnEditHandler - runs language-aware lint validation after Write/Edit.

Uses Strategy Pattern: all language-specific logic is delegated to LintStrategy
implementations. The handler itself has ZERO language awareness.
"""

import subprocess  # nosec B404 - subprocess used for lint validation only (trusted tools)
from pathlib import Path
from typing import Any

from claude_code_hooks_daemon.constants import (
    HandlerID,
    HandlerTag,
    HookInputField,
    Priority,
    Timeout,
    ToolName,
)
from claude_code_hooks_daemon.core import Decision, Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_file_path
from claude_code_hooks_daemon.strategies.lint.common import matches_skip_path
from claude_code_hooks_daemon.strategies.lint.protocol import LintStrategy
from claude_code_hooks_daemon.strategies.lint.registry import LintStrategyRegistry

# Placeholder for file path in lint commands
_FILE_PLACEHOLDER = "{file}"


class LintOnEditHandler(Handler):
    """Run language-aware lint validation on files after Write/Edit.

    Uses Strategy Pattern: delegates ALL language-specific decisions to LintStrategy
    implementations registered in the LintStrategyRegistry. The handler orchestrates
    the workflow without any knowledge of specific languages.

    Each language defines a default lint command (e.g., bash -n, python -m py_compile)
    and an optional extended lint command (e.g., shellcheck, ruff). Commands are
    overridable at project level via config.

    Configuration options (set via config YAML):
        languages: list[str] | None - Restrict to specific languages.
            If not set or empty, ALL registered languages are enforced (default).
        command_overrides: dict[str, dict] | None - Override lint commands per language.
            Example: {"Python": {"default": "ruff check {file}", "extended": null}}
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.LINT_ON_EDIT,
            priority=Priority.LINT_ON_EDIT,
            terminal=False,
            tags=[
                HandlerTag.VALIDATION,
                HandlerTag.MULTI_LANGUAGE,
                HandlerTag.QA_ENFORCEMENT,
                HandlerTag.NON_TERMINAL,
            ],
        )
        self._registry = LintStrategyRegistry.create_default()
        # Config options: set via setattr AFTER __init__
        self._languages: list[str] | None = None
        self._command_overrides: dict[str, dict[str, str | None]] | None = None
        self._languages_applied: bool = False

    def _apply_language_filter(self) -> None:
        """Apply language filter to registry on first use (lazy)."""
        if self._languages_applied:
            return
        self._languages_applied = True
        effective_languages = self._languages or getattr(self, "_project_languages", None)
        if effective_languages:
            self._registry.filter_by_languages(effective_languages)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this is a Write/Edit operation to a lintable file."""
        self._apply_language_filter()

        # Only match Write/Edit tools
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

        # Check skip paths
        if matches_skip_path(file_path, strategy.skip_paths):
            return False

        # File must exist (PostToolUse runs after write)
        return Path(file_path).exists()

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Run lint commands and deny if errors found."""
        file_path = get_file_path(hook_input)
        if not file_path:
            return HookResult(decision=Decision.ALLOW, reason="No file path found")

        strategy = self._registry.get_strategy(file_path)
        if strategy is None:
            return HookResult(decision=Decision.ALLOW)

        # Get lint commands (config overrides take priority)
        default_cmd, extended_cmd = self._get_lint_commands(strategy)

        # Run default lint command
        default_result = self._run_lint_command(default_cmd, file_path, strategy.language_name)
        if default_result is not None:
            return default_result

        # Run extended lint command if configured and default passed
        if extended_cmd:
            extended_result = self._run_lint_command(
                extended_cmd, file_path, strategy.language_name
            )
            if extended_result is not None:
                return extended_result

        return HookResult(decision=Decision.ALLOW)

    def _get_lint_commands(self, strategy: LintStrategy) -> tuple[str, str | None]:
        """Get lint commands, checking config overrides first."""
        default_cmd = strategy.default_lint_command
        extended_cmd = strategy.extended_lint_command

        if self._command_overrides and strategy.language_name in self._command_overrides:
            overrides = self._command_overrides[strategy.language_name]
            if "default" in overrides:
                override_default = overrides["default"]
                if override_default is not None:
                    default_cmd = override_default
            if "extended" in overrides:
                extended_cmd = overrides.get("extended")

        return default_cmd, extended_cmd

    def _run_lint_command(
        self, command_template: str, file_path: str, language_name: str
    ) -> HookResult | None:
        """Run a lint command and return HookResult if it fails, None if it passes.

        Returns:
            HookResult with DENY if lint fails, None if lint passes.
            HookResult with ALLOW if linter not found or times out (graceful degradation).
        """
        command = command_template.replace(_FILE_PLACEHOLDER, file_path)
        # Split command into list for subprocess
        # SECURITY: These are trusted lint tools defined in strategy constants
        command_parts = command.split()

        try:
            result = subprocess.run(  # nosec B603 - lint tools are trusted, file path from hook
                command_parts,
                capture_output=True,
                text=True,
                timeout=Timeout.LINT_CHECK,
            )

            if result.returncode != 0:
                error_output = result.stdout
                if result.stderr:
                    error_output = (
                        error_output + "\n" + result.stderr if error_output else result.stderr
                    )

                return HookResult(
                    decision=Decision.DENY,
                    reason=(
                        f"{language_name} lint FAILED for {Path(file_path).name}\n\n"
                        f"{error_output}\n\n"
                        f"Fix the lint errors before continuing.\n"
                        f"Command: {command}"
                    ),
                )

        except FileNotFoundError:
            # Linter not installed - graceful degradation
            return HookResult(
                decision=Decision.ALLOW,
                reason=f"Lint tool not found: {command_parts[0]} (skipping)",
            )
        except subprocess.TimeoutExpired:
            return HookResult(
                decision=Decision.ALLOW,
                reason=f"Lint check timed out after {Timeout.LINT_CHECK}s for {Path(file_path).name}",
            )

        return None

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
