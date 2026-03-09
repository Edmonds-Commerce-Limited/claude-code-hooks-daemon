"""Tests for pseudo-event integration in DaemonController.

TDD RED phase: Tests define how pseudo-events are wired into the
DaemonController lifecycle (initialise + process_event).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from claude_code_hooks_daemon.config.models import Config
from claude_code_hooks_daemon.core.event import EventType, HookEvent, HookInput
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.daemon.controller import DaemonController


def _make_config_with_pseudo_events(
    pseudo_events: dict[str, Any] | None = None,
) -> Config:
    """Create a Config with pseudo_events section."""
    data: dict[str, Any] = {
        "version": "2.0",
        "daemon": {"self_install_mode": True},
        "handlers": {},
    }
    if pseudo_events is not None:
        data["pseudo_events"] = pseudo_events
    return Config.model_validate(data)


class TestConfigPseudoEventsField:
    """Test pseudo_events field on Config model."""

    def test_config_has_pseudo_events_field(self) -> None:
        """Config model accepts pseudo_events field."""
        config = _make_config_with_pseudo_events(
            {
                "nitpick": {
                    "enabled": True,
                    "triggers": ["pre_tool_use:1/5"],
                    "handlers": {
                        "dismissive_language": {"enabled": True},
                    },
                }
            }
        )
        assert config.pseudo_events is not None
        assert "nitpick" in config.pseudo_events

    def test_config_default_empty_pseudo_events(self) -> None:
        """Config defaults to empty pseudo_events dict."""
        config = Config.model_validate({"version": "2.0"})
        assert config.pseudo_events == {}

    def test_config_preserves_pseudo_event_structure(self) -> None:
        """Config preserves nested pseudo_events structure."""
        pe_config = {
            "nitpick": {
                "enabled": True,
                "triggers": ["pre_tool_use:1/5", "stop:1/1"],
                "handlers": {
                    "dismissive_language": {"enabled": True},
                    "hedging_language": {"enabled": False},
                },
            }
        }
        config = _make_config_with_pseudo_events(pe_config)
        assert len(config.pseudo_events["nitpick"]["triggers"]) == 2
        assert config.pseudo_events["nitpick"]["handlers"]["hedging_language"]["enabled"] is False


class TestControllerPseudoEventInitialise:
    """Test PseudoEventDispatcher creation during initialise()."""

    def test_initialise_accepts_pseudo_events_config(self) -> None:
        """DaemonController.initialise() accepts pseudo_events_config parameter."""
        controller = DaemonController()
        pe_config = {
            "nitpick": {
                "enabled": True,
                "triggers": ["pre_tool_use:1/5"],
                "handlers": {},
            }
        }
        with (
            patch("claude_code_hooks_daemon.handlers.registry.HandlerRegistry.discover"),
            patch(
                "claude_code_hooks_daemon.handlers.registry.HandlerRegistry.register_all",
                return_value=0,
            ),
            patch("claude_code_hooks_daemon.daemon.controller.ConfigValidator"),
            patch("claude_code_hooks_daemon.daemon.controller.ProjectContext") as mock_pc,
        ):
            mock_pc._initialized = True
            controller.initialise(
                handler_config={},
                workspace_root=MagicMock(),
                pseudo_events_config=pe_config,
            )
        assert controller._pseudo_dispatcher is not None

    def test_initialise_without_pseudo_events(self) -> None:
        """DaemonController works without pseudo_events_config."""
        controller = DaemonController()
        with (
            patch("claude_code_hooks_daemon.handlers.registry.HandlerRegistry.discover"),
            patch(
                "claude_code_hooks_daemon.handlers.registry.HandlerRegistry.register_all",
                return_value=0,
            ),
            patch("claude_code_hooks_daemon.daemon.controller.ConfigValidator"),
            patch("claude_code_hooks_daemon.daemon.controller.ProjectContext") as mock_pc,
        ):
            mock_pc._initialized = True
            controller.initialise(
                handler_config={},
                workspace_root=MagicMock(),
            )
        assert controller._pseudo_dispatcher is None


class TestControllerPseudoEventDispatch:
    """Test pseudo-event dispatch during process_event()."""

    def test_pseudo_event_context_merged_into_result(self) -> None:
        """Pseudo-event context is appended to real chain result."""
        controller = DaemonController()

        # Set up a mock dispatcher that returns advisory context
        mock_dispatcher = MagicMock()
        mock_pseudo_result = MagicMock()
        mock_pseudo_result.decision = Decision.ALLOW
        mock_pseudo_result.context = ["Hedging language detected"]
        mock_pseudo_result.handlers_matched = ["nitpick-hedging-language"]
        mock_pseudo_result.reason = None
        mock_dispatcher.check_and_fire.return_value = [mock_pseudo_result]

        controller._pseudo_dispatcher = mock_dispatcher
        controller._initialised = True
        controller._degraded = False

        event = HookEvent(
            event_type=EventType.PRE_TOOL_USE,
            hook_input=HookInput(
                tool_name="Bash",
                tool_input={"command": "echo hello"},
                session_id="test-session",
            ),
        )

        with patch("claude_code_hooks_daemon.core.router.EventRouter.route") as mock_route:
            mock_chain_result = MagicMock()
            mock_chain_result.result.decision = Decision.ALLOW
            mock_chain_result.result.context = ["Real context"]
            mock_chain_result.result.handlers_matched = []
            mock_chain_result.result.reason = None
            mock_chain_result.handlers_matched = []
            mock_route.return_value = mock_chain_result

            result = controller.process_event(event)

        # Verify dispatcher was called with correct args
        mock_dispatcher.check_and_fire.assert_called_once_with(
            EventType.PRE_TOOL_USE,
            event.hook_input.model_dump(by_alias=False),
            "test-session",
        )

        # Verify context was merged
        assert "Hedging language detected" in result.result.context

    def test_no_dispatch_when_no_pseudo_events(self) -> None:
        """No pseudo-event dispatch when dispatcher is None."""
        controller = DaemonController()
        controller._pseudo_dispatcher = None
        controller._initialised = True
        controller._degraded = False

        event = HookEvent(
            event_type=EventType.PRE_TOOL_USE,
            hook_input=HookInput(
                tool_name="Bash",
                tool_input={"command": "echo hello"},
            ),
        )

        with patch("claude_code_hooks_daemon.core.router.EventRouter.route") as mock_route:
            mock_chain_result = MagicMock()
            mock_chain_result.result.decision = Decision.ALLOW
            mock_chain_result.result.context = []
            mock_chain_result.result.handlers_matched = []
            mock_chain_result.handlers_matched = []
            mock_route.return_value = mock_chain_result

            result = controller.process_event(event)

        # Result should be unchanged
        assert result == mock_chain_result

    def test_session_id_defaults_when_missing(self) -> None:
        """Uses fallback session_id when not in hook_input."""
        controller = DaemonController()

        mock_dispatcher = MagicMock()
        mock_dispatcher.check_and_fire.return_value = []
        controller._pseudo_dispatcher = mock_dispatcher
        controller._initialised = True
        controller._degraded = False

        event = HookEvent(
            event_type=EventType.PRE_TOOL_USE,
            hook_input=HookInput(
                tool_name="Bash",
                tool_input={"command": "echo hello"},
                # No session_id
            ),
        )

        with patch("claude_code_hooks_daemon.core.router.EventRouter.route") as mock_route:
            mock_chain_result = MagicMock()
            mock_chain_result.result.decision = Decision.ALLOW
            mock_chain_result.result.context = []
            mock_chain_result.result.handlers_matched = []
            mock_chain_result.handlers_matched = []
            mock_route.return_value = mock_chain_result

            controller.process_event(event)

        # Should use fallback session_id
        call_args = mock_dispatcher.check_and_fire.call_args
        session_id = call_args[0][2]
        assert session_id == "default"
