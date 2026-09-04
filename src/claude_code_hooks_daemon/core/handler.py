"""Handler base class for hook handlers.

This module provides the abstract base class that all hook handlers
must inherit from, defining the interface for matching and processing
hook events.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from pathlib import Path

    from claude_code_hooks_daemon.constants.handlers import HandlerIDMeta
    from claude_code_hooks_daemon.core.acceptance_test import AcceptanceTest
    from claude_code_hooks_daemon.core.hook_result import HookResult
    from claude_code_hooks_daemon.core.project_layout import ProjectLayout
    from claude_code_hooks_daemon.core.rule import Rule
    from claude_code_hooks_daemon.core.workspace import ProjectRegistry


class WorkspaceScope(StrEnum):
    """Which axis a handler's concern is resolved against (Plan 00301 follow-up).

    See CLAUDE/Code/WorkspaceResolution.md's "REPO-level vs PROJECT-level
    handlers" section for the full taxonomy this pins.

    REPO: the concern is repository-singular (the plan tree, the agent/human
    docs corpus taken as a whole, git metadata, session/cron state). Must NOT
    consume per-project layout/workspace resolution -- there is exactly one
    of these per repository, declared `projects:` sub-trees notwithstanding.

    PROJECT: the concern belongs to a file's OWNING project (toolchains,
    manifests, source/test/config directory roles). Must resolve via the
    injected `_project_registry` (`resolve_workspace`/`resolve_layout`/
    `layout_for`/`iter_layouts`/`all_source_dirs`), never
    `ProjectContext.project_root()` for a project-shaped question.
    """

    REPO = "repo"
    PROJECT = "project"


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

    Priority Ranges: defined by ``PriorityRange`` in
    ``constants/priority.py`` (the source of truth); documented in
    CLAUDE/HANDLER_DEVELOPMENT.md#priority-guide.
    """

    #: Which axis this handler's concern is resolved against -- see
    #: :class:`WorkspaceScope`. Defaults to REPO, the neutral value: a
    #: handler that never touches project layout/workspace resolution is
    #: correctly REPO-scoped without declaring anything. A handler that
    #: DOES resolve per-project state must override this to PROJECT.
    workspace_scope: ClassVar[WorkspaceScope] = WorkspaceScope.REPO

    __slots__ = (
        "_project_exclude_paths",
        "_project_languages",
        "_project_layout",
        "_project_registry",
        "config_key",
        "depends_on",
        "handler_id",
        "name",
        "priority",
        "shares_options_with",
        "tags",
        "terminal",
    )

    _project_languages: list[str] | None
    _project_exclude_paths: list[str] | None
    _project_layout: ProjectLayout | None
    _project_registry: ProjectRegistry | None

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
        # Project-level values injected AFTER construction by handlers/registry.py.
        # They are initialised here so the annotations above are true: `__slots__`
        # creates the slot but leaves it UNSET until assigned, so plain attribute
        # access raised AttributeError on any handler built outside the registry —
        # which is every handler in a unit test. Fourteen call sites across nine
        # modules worked around that with `getattr(self, "_project_...", None)`.
        # Defaulting them makes the declared type honest and the workaround
        # unnecessary; the registry still overwrites both (Plan 00251).
        self._project_languages = None
        self._project_exclude_paths = None
        self._project_layout = None
        self._project_registry = None

    def layout_for(self, file_path: str) -> ProjectLayout:
        """The `ProjectLayout` owning ``file_path`` (Plan 00300/00331).

        :attr:`_project_layout` is the ROOT project's layout. Reading it
        directly answers a project-shaped question with the repository's
        answer, which :class:`WorkspaceScope`'s ``PROJECT`` contract forbids:
        a monorepo sub-project declaring its own ``layout.vendor_dirs`` would
        be ignored exactly the way the whole config was before Plan 00331.

        Never returns None. A caller asking a layout question needs an
        answer, and returning None would make every call site re-implement
        the same fallback -- which is how the parallel copies this plan
        deleted came about.

        Args:
            file_path: The file being acted on.

        Returns:
            The owning project's layout; the injected root layout when no
            registry is available (a unit test exercising a handler
            directly); the built-in defaults when there is neither.
        """
        from pathlib import Path

        from claude_code_hooks_daemon.core.workspace import resolve_layout
        from claude_code_hooks_daemon.utils.path_exclusion import resolve_project_root

        root = resolve_project_root()
        return resolve_layout(
            self._project_registry,
            Path(file_path),
            Path(root) if root else Path(),
            fallback_root_layout=self._project_layout,
        )

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
    def get_claude_md(self) -> str | None:
        """Return markdown content to inject into project CLAUDE.md.

        Override this method to provide handler-specific guidance that helps
        agents understand what this handler does and how to avoid fighting it.

        On daemon startup, the daemon collects get_claude_md() from all active
        handlers that return non-None, and injects the combined content into the
        project CLAUDE.md inside a <hooksdaemon>...</hooksdaemon> section.
        This keeps agents informed about active handler behaviour without
        requiring manual CLAUDE.md maintenance.

        Returns:
            Markdown string with handler guidance, or None to exclude from injection.
        """

    @abstractmethod
    def get_acceptance_tests(self) -> list[AcceptanceTest]:
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

    def get_rules(self) -> list[Rule]:
        """Return the Rule objects that define this handler's blocking behaviour.

        Plan 00116, Phase 2 (Task 2.2).  Used to generate:
          - The always-on CLAUDE.md rule-ID table (one row per rule).
          - Terse reminders for repeat block fires.
          - Verbose first-fire block messages.

        Override this in blocking handlers to declare their rules using
        ``RuleID`` constants (from ``constants.rule_ids``).  The base
        implementation returns an empty list so legacy handlers that have not
        yet been migrated continue to work without modification (graceful
        degradation — Decision B of the design).

        Returns:
            List of ``Rule`` objects; empty list if the handler has not yet
            declared rules (legacy / non-blocking handlers).
        """
        return []

    def get_enforcement_status(self, project_root: Path) -> list[str]:
        """Return advisory strings for any downgraded enforcement at ``project_root``.

        Plan 00296 Task 4.1. Some handlers decide their strictness from what
        they find on disk (an ``llm:`` script in ``package.json``, a resolvable
        linter binary) rather than from config — and when that probe comes up
        empty, enforcement quietly drops to advisory-only with nothing saying
        so outside the handler's own source. This hook lets a handler declare
        its CURRENT posture at a given root so `hooks-daemon check` can surface
        it, instead of the fact staying invisible until someone reads the code.

        Concrete (not abstract): most handlers have no such probe, so the
        default is "nothing to report" (nominal enforcement). Override only in
        a handler whose enforcement mode depends on what it finds on disk.

        Must stay CHEAP: `check` calls this synchronously and it must not add
        filesystem cost beyond what the handler already does per invocation
        (existence checks, one small file read) — no subprocess execution, no
        directory walks.

        Args:
            project_root: The root to evaluate the handler's posture at (the
                repository root, or a declared project's root).

        Returns:
            Human-readable advisory strings, one per degraded condition found.
            Empty list means nominal enforcement at this root.
        """
        return []

    def get_default_enabled(self) -> bool:
        """Whether this handler is enabled by default in a fresh config.

        Plan 00133. Single source of truth for a handler's *semantic* default
        enabled state. The config template still carries a curated
        ``{enabled: true/false}`` literal per handler (Decision 5); a drift-guard
        test (``test_default_enabled_template_consistency``) asserts the
        template's disabled set equals the set of handlers declaring
        ``get_default_enabled() -> False``, so the two can never diverge. The
        config-changes upgrade advisory consumes this method directly.

        ``True``  = opt-out  (on unless the client explicitly disables it).
        ``False`` = opt-in   (off unless the client explicitly enables it).

        Concrete (NOT abstract) with a sensible universal default: the vast
        majority of handlers are opt-out. Opt-in handlers override this to
        return ``False``. Keeping it concrete means existing built-in handlers
        and project-level handlers are never forced to implement it.

        Returns:
            ``True`` if the handler should be enabled by default, else ``False``.
        """
        return True
