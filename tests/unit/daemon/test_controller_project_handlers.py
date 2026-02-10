"""Unit tests for DaemonController project handler integration."""

import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.config.models import ProjectHandlersConfig
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.daemon.controller import DaemonController


class _StubHandler(Handler):
    """Minimal test handler for integration tests."""

    def __init__(self, handler_id: str = "stub-handler", priority: int = 50) -> None:
        super().__init__(handler_id=handler_id, priority=priority, terminal=False)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW, context=["stub"])

    def get_acceptance_tests(self) -> list[Any]:
        return []


class TestLoadProjectHandlers:
    """Test DaemonController._load_project_handlers method."""

    def test_load_project_handlers_returns_count(self, tmp_path: Path) -> None:
        """Test that _load_project_handlers returns number of loaded handlers."""
        controller = DaemonController()

        project_config = ProjectHandlersConfig(enabled=True, path=str(tmp_path))

        # Empty directory should load 0 handlers
        count = controller._load_project_handlers(
            project_handlers_config=project_config,
            workspace_root=tmp_path,
        )
        assert count == 0

    def test_load_project_handlers_disabled_returns_zero(self, tmp_path: Path) -> None:
        """Test that disabled project handlers config returns 0."""
        controller = DaemonController()

        project_config = ProjectHandlersConfig(enabled=False, path=str(tmp_path))

        count = controller._load_project_handlers(
            project_handlers_config=project_config,
            workspace_root=tmp_path,
        )
        assert count == 0

    def test_load_project_handlers_registers_with_router(self, tmp_path: Path) -> None:
        """Test that discovered handlers are registered with the router."""
        controller = DaemonController()

        stub_handler = _StubHandler(handler_id="project-stub")

        project_config = ProjectHandlersConfig(enabled=True, path=str(tmp_path))

        with patch(
            "claude_code_hooks_daemon.handlers.project_loader.ProjectHandlerLoader.discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = [
                (EventType.PRE_TOOL_USE, stub_handler),
            ]

            count = controller._load_project_handlers(
                project_handlers_config=project_config,
                workspace_root=tmp_path,
            )

        assert count == 1
        # Verify handler was registered with the router
        chain = controller._router.get_chain(EventType.PRE_TOOL_USE)
        handler_names = [h.name for h in chain.handlers]
        assert "project-stub" in handler_names

    def test_load_project_handlers_resolves_relative_path(self, tmp_path: Path) -> None:
        """Test that relative paths are resolved against workspace_root."""
        controller = DaemonController()

        project_config = ProjectHandlersConfig(enabled=True, path=".claude/project-handlers")

        with patch(
            "claude_code_hooks_daemon.handlers.project_loader.ProjectHandlerLoader.discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = []

            controller._load_project_handlers(
                project_handlers_config=project_config,
                workspace_root=tmp_path,
            )

            # Verify discover_handlers was called with resolved path
            expected_path = tmp_path / ".claude" / "project-handlers"
            mock_discover.assert_called_once_with(expected_path)

    def test_load_project_handlers_uses_absolute_path_as_is(self, tmp_path: Path) -> None:
        """Test that absolute paths are used directly."""
        controller = DaemonController()

        abs_path = str(tmp_path / "absolute" / "handlers")
        project_config = ProjectHandlersConfig(enabled=True, path=abs_path)

        with patch(
            "claude_code_hooks_daemon.handlers.project_loader.ProjectHandlerLoader.discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = []

            controller._load_project_handlers(
                project_handlers_config=project_config,
                workspace_root=tmp_path,
            )

            mock_discover.assert_called_once_with(Path(abs_path))

    def test_load_project_handlers_logs_count(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that loading is logged."""
        controller = DaemonController()

        project_config = ProjectHandlersConfig(enabled=True, path=str(tmp_path))

        with caplog.at_level(logging.INFO):
            controller._load_project_handlers(
                project_handlers_config=project_config,
                workspace_root=tmp_path,
            )

        assert any("project" in record.message.lower() for record in caplog.records)


class TestConflictDetection:
    """Test handler_id and priority conflict detection in _load_project_handlers."""

    def test_skips_project_handler_with_conflicting_id(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that project handler with same name as existing is skipped."""
        controller = DaemonController()

        # Register a built-in handler first
        builtin_handler = _StubHandler(handler_id="conflicting-handler", priority=10)
        controller._router.register(EventType.PRE_TOOL_USE, builtin_handler)

        # Project handler has the same handler_id
        project_handler = _StubHandler(handler_id="conflicting-handler", priority=50)

        project_config = ProjectHandlersConfig(enabled=True, path=str(tmp_path))

        with patch(
            "claude_code_hooks_daemon.handlers.project_loader.ProjectHandlerLoader.discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = [
                (EventType.PRE_TOOL_USE, project_handler),
            ]

            with caplog.at_level(logging.WARNING):
                count = controller._load_project_handlers(
                    project_handlers_config=project_config,
                    workspace_root=tmp_path,
                )

        # Project handler should be skipped
        assert count == 0

        # Should log a warning about the conflict
        assert any(
            "conflict" in record.message.lower() and "conflicting-handler" in record.message
            for record in caplog.records
        )

    def test_allows_project_handler_with_unique_id(self, tmp_path: Path) -> None:
        """Test that project handler with unique name is registered."""
        controller = DaemonController()

        # Register a built-in handler first
        builtin_handler = _StubHandler(handler_id="builtin-handler", priority=10)
        controller._router.register(EventType.PRE_TOOL_USE, builtin_handler)

        # Project handler has a different handler_id
        project_handler = _StubHandler(handler_id="project-unique", priority=50)

        project_config = ProjectHandlersConfig(enabled=True, path=str(tmp_path))

        with patch(
            "claude_code_hooks_daemon.handlers.project_loader.ProjectHandlerLoader.discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = [
                (EventType.PRE_TOOL_USE, project_handler),
            ]

            count = controller._load_project_handlers(
                project_handlers_config=project_config,
                workspace_root=tmp_path,
            )

        assert count == 1

    def test_logs_warning_for_priority_collision(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that priority collision with existing handler logs a warning."""
        controller = DaemonController()

        # Register a built-in handler with priority 50
        builtin_handler = _StubHandler(handler_id="builtin-handler", priority=50)
        controller._router.register(EventType.PRE_TOOL_USE, builtin_handler)

        # Project handler has different name but same priority for same event
        project_handler = _StubHandler(handler_id="project-handler", priority=50)

        project_config = ProjectHandlersConfig(enabled=True, path=str(tmp_path))

        with patch(
            "claude_code_hooks_daemon.handlers.project_loader.ProjectHandlerLoader.discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = [
                (EventType.PRE_TOOL_USE, project_handler),
            ]

            with caplog.at_level(logging.WARNING):
                count = controller._load_project_handlers(
                    project_handlers_config=project_config,
                    workspace_root=tmp_path,
                )

        # Handler should still be registered (priority collision is a warning, not a skip)
        assert count == 1

        # Should log a warning about the priority collision
        assert any(
            "priority" in record.message.lower() and "50" in record.message
            for record in caplog.records
        )

    def test_no_warning_for_different_priority(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that different priorities don't produce warnings."""
        controller = DaemonController()

        # Register a built-in handler with priority 10
        builtin_handler = _StubHandler(handler_id="builtin-handler", priority=10)
        controller._router.register(EventType.PRE_TOOL_USE, builtin_handler)

        # Project handler has different priority
        project_handler = _StubHandler(handler_id="project-handler", priority=50)

        project_config = ProjectHandlersConfig(enabled=True, path=str(tmp_path))

        with patch(
            "claude_code_hooks_daemon.handlers.project_loader.ProjectHandlerLoader.discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = [
                (EventType.PRE_TOOL_USE, project_handler),
            ]

            with caplog.at_level(logging.WARNING):
                count = controller._load_project_handlers(
                    project_handlers_config=project_config,
                    workspace_root=tmp_path,
                )

        assert count == 1

        # No priority collision warning should be logged
        assert not any(
            "priority" in record.message.lower() and "collision" in record.message.lower()
            for record in caplog.records
        )

    def test_conflict_check_spans_only_same_event_type(self, tmp_path: Path) -> None:
        """Test that conflict checks only apply within the same event type."""
        controller = DaemonController()

        # Register a built-in handler for POST_TOOL_USE
        builtin_handler = _StubHandler(handler_id="shared-name", priority=50)
        controller._router.register(EventType.POST_TOOL_USE, builtin_handler)

        # Project handler has same name but is for PRE_TOOL_USE (different event)
        project_handler = _StubHandler(handler_id="shared-name", priority=50)

        project_config = ProjectHandlersConfig(enabled=True, path=str(tmp_path))

        with patch(
            "claude_code_hooks_daemon.handlers.project_loader.ProjectHandlerLoader.discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = [
                (EventType.PRE_TOOL_USE, project_handler),
            ]

            count = controller._load_project_handlers(
                project_handlers_config=project_config,
                workspace_root=tmp_path,
            )

        # Should be registered since it's a different event type
        assert count == 1

    def test_multiple_conflicts_skip_all_conflicting(self, tmp_path: Path) -> None:
        """Test that multiple conflicting handlers are all skipped."""
        controller = DaemonController()

        # Register built-in handlers
        builtin_a = _StubHandler(handler_id="handler-a", priority=10)
        builtin_b = _StubHandler(handler_id="handler-b", priority=20)
        controller._router.register(EventType.PRE_TOOL_USE, builtin_a)
        controller._router.register(EventType.PRE_TOOL_USE, builtin_b)

        # Project handlers: one conflicts, one is unique
        conflict_handler = _StubHandler(handler_id="handler-a", priority=50)
        unique_handler = _StubHandler(handler_id="handler-c", priority=50)

        project_config = ProjectHandlersConfig(enabled=True, path=str(tmp_path))

        with patch(
            "claude_code_hooks_daemon.handlers.project_loader.ProjectHandlerLoader.discover_handlers"
        ) as mock_discover:
            mock_discover.return_value = [
                (EventType.PRE_TOOL_USE, conflict_handler),
                (EventType.PRE_TOOL_USE, unique_handler),
            ]

            count = controller._load_project_handlers(
                project_handlers_config=project_config,
                workspace_root=tmp_path,
            )

        # Only the unique handler should be registered
        assert count == 1
        chain = controller._router.get_chain(EventType.PRE_TOOL_USE)
        handler_names = [h.name for h in chain.handlers]
        assert "handler-c" in handler_names
        assert handler_names.count("handler-a") == 1  # Only the built-in


class TestInitialiseWithProjectHandlers:
    """Test that initialise() calls _load_project_handlers."""

    def test_initialise_calls_load_project_handlers(self, tmp_path: Path) -> None:
        """Test that initialise loads project handlers when config provided."""
        project_config = ProjectHandlersConfig(enabled=True, path=str(tmp_path))

        with (
            patch(
                "claude_code_hooks_daemon.daemon.controller.HandlerRegistry"
            ) as mock_registry_cls,
            patch(
                "claude_code_hooks_daemon.daemon.controller.DaemonController._load_project_handlers",
                return_value=0,
            ) as mock_load,
            patch(
                "claude_code_hooks_daemon.daemon.controller.DaemonController._validate_config",
            ),
            patch(
                "claude_code_hooks_daemon.daemon.controller.ProjectContext._initialized",
                True,
            ),
        ):
            mock_registry_cls.return_value.register_all.return_value = 0
            controller = DaemonController()
            controller.initialise(
                workspace_root=tmp_path,
                project_handlers_config=project_config,
            )

        mock_load.assert_called_once_with(
            project_handlers_config=project_config,
            workspace_root=tmp_path,
        )

    def test_initialise_skips_project_handlers_when_not_provided(self, tmp_path: Path) -> None:
        """Test that initialise skips project handlers when config is None."""
        with (
            patch(
                "claude_code_hooks_daemon.daemon.controller.HandlerRegistry"
            ) as mock_registry_cls,
            patch(
                "claude_code_hooks_daemon.daemon.controller.DaemonController._load_project_handlers",
                return_value=0,
            ) as mock_load,
            patch(
                "claude_code_hooks_daemon.daemon.controller.DaemonController._validate_config",
            ),
            patch(
                "claude_code_hooks_daemon.daemon.controller.ProjectContext._initialized",
                True,
            ),
        ):
            mock_registry_cls.return_value.register_all.return_value = 0
            controller = DaemonController()
            controller.initialise(
                workspace_root=tmp_path,
            )

        mock_load.assert_not_called()
