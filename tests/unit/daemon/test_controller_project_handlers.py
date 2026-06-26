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
from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.daemon import project_handler_health as health
from claude_code_hooks_daemon.daemon.controller import DaemonController
from claude_code_hooks_daemon.handlers.project_loader import (
    ProjectHandlerDiscovery,
    ProjectHandlerLoadFailure,
)

# Target of the failure-aware discovery call the controller makes (Plan 00143).
_DISCOVER = (
    "claude_code_hooks_daemon.handlers.project_loader."
    "ProjectHandlerLoader.discover_handlers_with_failures"
)


@pytest.fixture(autouse=True)
def _isolate_health_state(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point project-handler health persistence at an isolated temp dir.

    The controller now persists load failures on every project-handler load;
    these direct ``_load_project_handlers`` calls would otherwise hit an
    uninitialised ProjectContext. Isolating the untracked dir keeps the
    persistence side-effect clean and inspectable per test.
    """
    health_dir = tmp_path_factory.mktemp("project_handler_health")
    monkeypatch.setattr(
        ProjectContext,
        "daemon_untracked_dir",
        classmethod(lambda cls: health_dir),
    )


class _StubHandler(Handler):
    """Minimal test handler for integration tests."""

    def __init__(self, handler_id: str = "stub-handler", priority: int = 50) -> None:
        super().__init__(handler_id=handler_id, priority=priority, terminal=False)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW, context=["stub"])

    def get_claude_md(self) -> str | None:
        return None

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

        with patch(_DISCOVER) as mock_discover:
            mock_discover.return_value = ProjectHandlerDiscovery(
                handlers=[(EventType.PRE_TOOL_USE, stub_handler)]
            )

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

        with patch(_DISCOVER) as mock_discover:
            mock_discover.return_value = ProjectHandlerDiscovery(handlers=[])

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

        with patch(_DISCOVER) as mock_discover:
            mock_discover.return_value = ProjectHandlerDiscovery(handlers=[])

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

        with patch(_DISCOVER) as mock_discover:
            mock_discover.return_value = ProjectHandlerDiscovery(
                handlers=[(EventType.PRE_TOOL_USE, project_handler)]
            )

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

        with patch(_DISCOVER) as mock_discover:
            mock_discover.return_value = ProjectHandlerDiscovery(
                handlers=[(EventType.PRE_TOOL_USE, project_handler)]
            )

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

        with patch(_DISCOVER) as mock_discover:
            mock_discover.return_value = ProjectHandlerDiscovery(
                handlers=[(EventType.PRE_TOOL_USE, project_handler)]
            )

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

        with patch(_DISCOVER) as mock_discover:
            mock_discover.return_value = ProjectHandlerDiscovery(
                handlers=[(EventType.PRE_TOOL_USE, project_handler)]
            )

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

        with patch(_DISCOVER) as mock_discover:
            mock_discover.return_value = ProjectHandlerDiscovery(
                handlers=[(EventType.PRE_TOOL_USE, project_handler)]
            )

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

        with patch(_DISCOVER) as mock_discover:
            mock_discover.return_value = ProjectHandlerDiscovery(
                handlers=[
                    (EventType.PRE_TOOL_USE, conflict_handler),
                    (EventType.PRE_TOOL_USE, unique_handler),
                ]
            )

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


class TestPersistsLoadFailures:
    """The running daemon persists project-handler load failures (Plan 00143).

    The persisted state is what the SessionStart alert and the
    status/health/check CLI read to surface a loud degraded signal.
    """

    @pytest.fixture
    def error_cases_dir(self) -> Path:
        """Fixtures with intentionally broken project handlers."""
        return (
            Path(__file__).parent.parent.parent
            / "fixtures"
            / "project_handlers_error_cases"
        )

    @pytest.fixture
    def valid_handlers_dir(self) -> Path:
        """Fixtures with valid project handlers."""
        return Path(__file__).parent.parent.parent / "fixtures" / "project_handlers"

    def test_failures_are_persisted(self, error_cases_dir: Path) -> None:
        """Broken handlers are recorded to the health state file."""
        controller = DaemonController()
        project_config = ProjectHandlersConfig(enabled=True, path=str(error_cases_dir))

        controller._load_project_handlers(
            project_handlers_config=project_config,
            workspace_root=error_cases_dir,
        )

        state = health.read_load_failures()
        assert state.is_degraded is True
        assert state.failed_count >= 1
        filenames = {f.filename for f in state.failures}
        assert "missing_get_claude_md_handler.py" in filenames

    def test_persisted_even_when_all_handlers_fail(self, tmp_path: Path) -> None:
        """Failures persist despite the early-return when zero handlers load.

        With every handler broken, ``discovery.handlers`` is empty and the
        method returns 0 — but the failures must still be recorded before that
        early return, or the degraded signal would be lost exactly when the
        whole event directory is down.
        """
        pre_tool_dir = tmp_path / "pre_tool_use"
        pre_tool_dir.mkdir()
        (pre_tool_dir / "all_broken_handler.py").write_text("this is not valid python !!!")

        controller = DaemonController()
        project_config = ProjectHandlersConfig(enabled=True, path=str(tmp_path))

        count = controller._load_project_handlers(
            project_handlers_config=project_config,
            workspace_root=tmp_path,
        )

        assert count == 0
        state = health.read_load_failures()
        assert state.is_degraded is True
        assert "all_broken_handler.py" in {f.filename for f in state.failures}

    def test_clean_load_clears_stale_state(self, valid_handlers_dir: Path) -> None:
        """A clean load erases prior degraded state (always-rewrite)."""
        # Pre-seed a stale failure as if a previous daemon was degraded.
        health.write_load_failures(
            [
                ProjectHandlerLoadFailure(
                    filename="old_handler.py",
                    event_dir="pre_tool_use",
                    reason="stale",
                )
            ],
            loaded_count=0,
        )
        assert health.read_load_failures().is_degraded is True

        controller = DaemonController()
        project_config = ProjectHandlersConfig(enabled=True, path=str(valid_handlers_dir))
        controller._load_project_handlers(
            project_handlers_config=project_config,
            workspace_root=valid_handlers_dir,
        )

        assert health.read_load_failures().is_degraded is False

    def test_disabled_clears_stale_state(self, tmp_path: Path) -> None:
        """Disabling project handlers clears any stale degraded state."""
        health.write_load_failures(
            [
                ProjectHandlerLoadFailure(
                    filename="old_handler.py",
                    event_dir="pre_tool_use",
                    reason="stale",
                )
            ],
            loaded_count=0,
        )
        assert health.read_load_failures().is_degraded is True

        controller = DaemonController()
        project_config = ProjectHandlersConfig(enabled=False, path=str(tmp_path))
        controller._load_project_handlers(
            project_handlers_config=project_config,
            workspace_root=tmp_path,
        )

        assert health.read_load_failures().is_degraded is False
