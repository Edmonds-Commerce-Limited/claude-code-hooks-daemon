"""Handler base class for hook handlers.

This module provides the abstract base class that all hook handlers
must inherit from, defining the interface for matching and processing
hook events.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from claude_code_hooks_daemon.constants.handlers import HandlerIDMeta
    from claude_code_hooks_daemon.core.hook_result import HookResult


class Handler(ABC):
    """Abstract base class for all hook handlers.

    Handlers implement pattern matching and execution logic for specific
    hook scenarios. They can be terminal (stop dispatch) or non-terminal
    (allow fall-through).

    Attributes:
        handler_id: Unique handler identifier (use HandlerID constants)
        name: Display name (set from handler_id)
        priority: Execution order (lower = earlier, default 50)
        terminal: If True, stops dispatch after execution (default True).
                  If False, allows subsequent handlers to run (fall-through).
        tags: List of tags for categorizing and filtering handlers (default []).
              Tags enable language-specific, function-specific, or project-specific
              handler groups. Example tags: python, safety, tdd, qa-enforcement.
        shares_options_with: Name of parent handler to inherit config options from.
                            When set, this handler will automatically receive the same
                            options as the parent handler (optional, default None).
        depends_on: List of handler names that must be enabled for this handler to work.
                   Used for validation at config load time (optional, default None).

    Priority Ranges (Convention):
        0-19:  Critical safety (destructive git, dangerous commands)
        20-39: Code quality (ESLint, TDD enforcement)
        40-59: Workflow (planning, npm conventions)
        60-79: Advisory (British English, hints)
        80-99: Logging/metrics (analytics, audit trails)
    """

    __slots__ = (
        "config_key",
        "depends_on",
        "handler_id",
        "name",
        "priority",
        "shares_options_with",
        "tags",
        "terminal",
    )

    def __init__(
        self,
        handler_id: str | HandlerIDMeta | None = None,
        *,
        name: str | None = None,
        priority: int = 50,
        terminal: bool = True,
        tags: list[str] | None = None,
        shares_options_with: str | None = None,
        depends_on: list[str] | None = None,
    ) -> None:
        """Initialise handler.

        Args:
            handler_id: Handler identifier, either a HandlerIDMeta constant or string.
                Use HandlerID constants for production handlers.
            name: Deprecated alias for handler_id (backward compatibility for tests).
            priority: Execution order (lower = earlier)
            terminal: Whether to stop dispatch after execution
            tags: List of tags for categorizing/filtering (default [])
            shares_options_with: Parent handler name to inherit options from (default None)
            depends_on: List of required handler names (default None)

        Raises:
            ValueError: If neither handler_id nor name is provided.
        """
        from claude_code_hooks_daemon.constants.handlers import HandlerIDMeta

        # Accept either handler_id or name (backward compat)
        resolved_id: str | HandlerIDMeta
        if handler_id is not None:
            resolved_id = handler_id
        elif name is not None:
            resolved_id = name
        else:
            raise ValueError("Either handler_id or name must be provided")

        if isinstance(resolved_id, HandlerIDMeta):
            self.handler_id: str | HandlerIDMeta = resolved_id
            self.name = resolved_id.display_name
            self.config_key = resolved_id.config_key
        else:
            self.handler_id = resolved_id
            self.name = resolved_id
            self.config_key = resolved_id.replace("-", "_")
        self.priority = priority
        self.terminal = terminal
        self.tags = tags if tags is not None else []
        self.shares_options_with = shares_options_with
        self.depends_on = depends_on if depends_on is not None else []

    def __repr__(self) -> str:
        """Return string representation."""
        parts = [
            f"name={self.name!r}",
            f"priority={self.priority}",
            f"terminal={self.terminal}",
            f"tags={self.tags}",
        ]
        if self.shares_options_with:
            parts.append(f"shares_options_with={self.shares_options_with!r}")
        if self.depends_on:
            parts.append(f"depends_on={self.depends_on}")
        return f"{self.__class__.__name__}({', '.join(parts)})"

    @abstractmethod
    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if this handler should process the given event.

        Override this method to implement custom matching logic.
        Can use complex conditions, multiple checks, etc.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            True if this handler should execute
        """
        ...

    @abstractmethod
    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Execute the handler logic.

        Override this method to implement the actual hook behaviour.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            HookResult with decision and optional reason/context
        """
        ...

    @abstractmethod
    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for this handler.

        MANDATORY: Every handler MUST define at least one acceptance test.
        Returning an empty list is NOT ALLOWED and will be rejected during
        validation.

        Acceptance tests define real-world scenarios that verify the handler
        works correctly. They're used to generate manual test playbooks and
        will enable automated testing in the future.

        Returns:
            List of AcceptanceTest objects (must contain at least 1 test)

        Raises:
            ValueError: If validation detects empty list return (enforced elsewhere)

        Example:
            def get_acceptance_tests(self) -> list[AcceptanceTest]:
                return [
                    AcceptanceTest(
                        title="Block git reset --hard",
                        command='echo "git reset --hard"',
                        description="Prevents destructive git reset",
                        expected_decision=Decision.DENY,
                        expected_message_patterns=[r"destroys.*uncommitted"],
                        safety_notes="Uses echo - safe to execute",
                        test_type=TestType.BLOCKING,
                    )
                ]
        """
        ...
