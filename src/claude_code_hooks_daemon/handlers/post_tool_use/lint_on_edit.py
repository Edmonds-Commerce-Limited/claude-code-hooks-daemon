"""LintOnEditHandler - runs language-aware lint validation after Write/Edit.

Uses Strategy Pattern: all language-specific logic is delegated to LintStrategy
implementations. The handler itself has ZERO language awareness.
"""

import shutil
import subprocess  # nosec B404 - subprocess used for lint validation only (trusted tools)
import sys
from pathlib import Path
from typing import Any, ClassVar, Final

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

# Directory holding the console scripts of the environment running the daemon.
# ``sys.executable`` is the project venv's interpreter, and a venv's ``ruff`` /
# ``black`` / ``mypy`` entry points sit beside it. Resolved once at import.
_INTERPRETER_BIN_DIR: Final[Path] = Path(sys.executable).parent


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

    @staticmethod
    def _find_module_root(file_path: str, marker_file: str) -> str | None:
        """Find the nearest parent directory containing a marker file (e.g., go.mod).

        Walks up from the file's directory to find the module/project root.
        Returns the directory path if found, None otherwise.
        """
        current = Path(file_path).parent
        while current != current.parent:
            if (current / marker_file).exists():
                return str(current)
            current = current.parent
        return None

    # Map of language names to their module root marker files
    _MODULE_ROOT_MARKERS: ClassVar[dict[str, str]] = {
        "Go": "go.mod",
    }

    def _resolve_executable(self, executable: str) -> str | None:
        """Resolve a lint tool name to a runnable path, or None if absent.

        ``subprocess.run`` without a shell resolves a bare name against ``PATH``
        only. A Python project keeps its tooling in a virtualenv, so ``ruff``
        lives in ``<venv>/bin/ruff`` and is NOT on ``PATH`` — the daemon's own
        repo included. Every ``.py`` edit therefore raised ``FileNotFoundError``
        and degraded to "lint tool not found (ruff) - install to enable lint
        checking": the guard silently inert, and the advice wrong, because ruff
        was already installed.

        Looks in the interpreter's own ``bin`` directory first (that IS the
        project venv), then falls back to ``PATH`` for tools installed system
        wide (``golangci-lint``, ``shellcheck``, ``phpstan``).

        Returning None rather than guessing is deliberate: the caller turns it
        into an advisory ALLOW. Invoking a missing tool some other way — e.g.
        rewriting the command to ``python -m ruff`` — would exit NON-ZERO
        instead of raising, and a non-zero lint result DENIES the user's edit.
        A tool that is not installed must never block anyone.
        """
        # An absolute path (e.g. sys.executable in the default Python command)
        # is already resolved; do not second-guess it.
        if Path(executable).is_absolute():
            return executable

        candidate = _INTERPRETER_BIN_DIR / executable
        if candidate.is_file():
            return str(candidate)

        return shutil.which(executable)

    def _run_lint_command(
        self, command_template: str, file_path: str, language_name: str
    ) -> HookResult | None:
        """Run a lint command and return HookResult if it fails, None if it passes.

        Returns:
            HookResult with DENY if lint fails, None if lint passes.
            HookResult with ALLOW if linter not found or times out (graceful degradation).
        """
        # Find module/project root for languages that require it (e.g., Go needs go.mod)
        working_dir: str | None = None
        marker = self._MODULE_ROOT_MARKERS.get(language_name)
        if marker:
            working_dir = self._find_module_root(file_path, marker)

        # For Go, vet the package directory (not single file) since Go packages span
        # multiple files and single-file vetting can't resolve cross-file references
        effective_path = file_path
        if language_name == "Go" and working_dir:
            pkg_dir = str(Path(file_path).parent)
            # Convert absolute path to module-relative package path for go vet
            if pkg_dir.startswith(working_dir):
                effective_path = "./" + pkg_dir[len(working_dir) :].lstrip("/") + "/"

        command = command_template.replace(_FILE_PLACEHOLDER, effective_path)
        # Split command into list for subprocess
        # SECURITY: These are trusted lint tools defined in strategy constants
        command_parts = command.split()

        # Resolve the executable BEFORE running it. Strategies name their tools
        # bare (``ruff check {file}``) so they stay environment-independent; it
        # is this handler's job to find that name in the project venv or on
        # PATH. Without this the guard is inert wherever tooling lives in a
        # venv, which is the normal case for a Python project.
        resolved = self._resolve_executable(command_parts[0])
        if resolved is None:
            return HookResult(
                decision=Decision.ALLOW,
                context=[
                    f"⚠️ {language_name} lint tool not found ({command_parts[0]}) "
                    f"- looked in {_INTERPRETER_BIN_DIR} and on PATH. "
                    f"Install it to enable lint checking."
                ],
            )
        command_parts[0] = resolved

        try:
            result = subprocess.run(  # nosec B603 - lint tools are trusted, file path from hook
                command_parts,
                capture_output=True,
                text=True,
                timeout=Timeout.LINT_CHECK,
                cwd=working_dir,
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
            # Linter not installed - advisory allow (visible in system-reminders)
            return HookResult(
                decision=Decision.ALLOW,
                context=[
                    f"⚠️ {language_name} lint tool not found ({command_parts[0]}) "
                    f"- install to enable lint checking"
                ],
            )
        except subprocess.TimeoutExpired:
            return HookResult(
                decision=Decision.ALLOW,
                context=[
                    f"Lint check timed out after {Timeout.LINT_CHECK}s for {Path(file_path).name}"
                ],
            )

        return None

    def get_claude_md(self) -> str | None:
        return """## lint_on_edit — source writes are linted, and a failure DENIES

Every `Write`/`Edit` to a Python, Shell, Go, PHP, Ruby, Rust, Swift, Kotlin or
Dart file is linted immediately. A lint failure DENIES the tool call.

**The write has ALREADY landed on disk.** A PostToolUse denial is a failure
report, not a rollback — the file exists, with your content in it. Fix the
reported problems with `Edit`. Do NOT re-`Write` the file from scratch: that
rewrites content already on disk from memory, and loses anything you no longer
have in hand.

A denial also cancels every sibling tool call batched in the same turn, so
re-issue those separately.

Each language runs a cheap syntax check first (`python -m py_compile`, `bash
-n`, `go vet`, `php -l`, …) and then an optional deeper linter (`ruff`,
`shellcheck`, `golangci-lint`, `rubocop`, …). Tools are resolved from the
daemon's venv before `PATH`.

**A linter that is not installed never blocks.** You get an advisory saying it
was not found and the write stands — so that message means the check was
SKIPPED, not that it passed.

Narrow it under `handlers.post_tool_use.lint_on_edit.options`: `languages`
restricts which languages are checked, and `command_overrides` replaces a
language's `default`/`extended` command (set `extended: null` to run only the
syntax check)."""

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
