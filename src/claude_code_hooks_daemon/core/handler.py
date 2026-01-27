"""Handler base class for hook handlers.

This module provides the abstract base class that all hook handlers
must inherit from, defining the interface for matching and processing
hook events.
"""

from abc import ABC, abstractmethod
from typing import Any

from claude_code_hooks_daemon.core.hook_result import HookResult


class Handler(ABC):
    """Abstract base class for all hook handlers.

    Handlers implement pattern matching and execution logic for specific
    hook scenarios. They can be terminal (stop dispatch) or non-terminal
    (allow fall-through).

    Attributes:
        name: Unique handler identifier
        priority: Execution order (lower = earlier, default 50)
        terminal: If True, stops dispatch after execution (default True).
                  If False, allows subsequent handlers to run (fall-through).
        tags: List of tags for categorizing and filtering handlers (default []).
              Tags enable language-specific, function-specific, or project-specific
              handler groups. Example tags: python, safety, tdd, qa-enforcement.

    Priority Ranges (Convention):
        0-19:  Critical safety (destructive git, dangerous commands)
        20-39: Code quality (ESLint, TDD enforcement)
        40-59: Workflow (planning, npm conventions)
        60-79: Advisory (British English, hints)
        80-99: Logging/metrics (analytics, audit trails)
    """

    __slots__ = ("name", "priority", "tags", "terminal")

    def __init__(
        self,
        name: str,
        *,
        priority: int = 50,
        terminal: bool = True,
        tags: list[str] | None = None,
    ) -> None:
        """Initialise handler.

        Args:
            name: Unique handler identifier
            priority: Execution order (lower = earlier)
            terminal: Whether to stop dispatch after execution
            tags: List of tags for categorizing/filtering (default [])
        """
        self.name = name
        self.priority = priority
        self.terminal = terminal
        self.tags = tags if tags is not None else []

    def __repr__(self) -> str:
        """Return string representation."""
        return (
            f"{self.__class__.__name__}("
            f"name={self.name!r}, "
            f"priority={self.priority}, "
            f"terminal={self.terminal}, "
            f"tags={self.tags})"
        )

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
