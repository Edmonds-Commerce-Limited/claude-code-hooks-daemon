"""Tests for config key injection in DENY/ASK handler responses.

Plan 050: Every handler DENY/ASK response should include the fully-qualified
config path so users can immediately know how to disable it.

Format: handlers.{event_type}.{config_key}  (set enabled: false)
"""

from typing import Any

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.core.hook_result import Decision, HookResult
from claude_code_hooks_daemon.core.router import EventRouter

# Footer format constant (must match implementation)
_DISABLE_FOOTER_PREFIX = "\n\nTo disable: handlers."


class StubHandler(Handler):
    """Stub handler for testing config key injection."""

    def __init__(
        self,
        name: str = "test_handler",
        priority: int = 50,
        terminal: bool = True,
        result: HookResult | None = None,
    ) -> None:
        """Initialize stub handler."""
        super().__init__(name=name, priority=priority, terminal=terminal)
        self._result = result or HookResult.allow()

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Always match."""
        return True

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Return configured result."""
        return self._result

    def get_acceptance_tests(self) -> list[Any]:
        """Stub - no acceptance tests needed for test helpers."""
        from claude_code_hooks_daemon.core import AcceptanceTest, TestType

        return [
            AcceptanceTest(
                title="stub",
                command="echo test",
                description="Stub for config key injection tests",
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[r".*"],
                test_type=TestType.BLOCKING,
            )
        ]


class TestConfigKeyInjectionInRouter:
    """Config key injection at the EventRouter level."""

    def test_deny_result_includes_config_path(self) -> None:
        """DENY result should include config path footer in reason."""
        router = EventRouter()
        handler = StubHandler(
            name="destructive_git",
            terminal=True,
            result=HookResult.deny(reason="Blocked: dangerous command"),
        )
        router.register(EventType.PRE_TOOL_USE, handler)

        result = router.route(EventType.PRE_TOOL_USE, {"tool_name": "Bash"})

        assert result.result.decision == Decision.DENY
        assert "To disable: handlers.pre_tool_use.destructive_git" in result.result.reason
        assert "(set enabled: false)" in result.result.reason

    def test_ask_result_includes_config_path(self) -> None:
        """ASK result should include config path footer in reason."""
        router = EventRouter()
        handler = StubHandler(
            name="risky_command",
            terminal=True,
            result=HookResult.ask(reason="Are you sure?"),
        )
        router.register(EventType.PRE_TOOL_USE, handler)

        result = router.route(EventType.PRE_TOOL_USE, {"tool_name": "Bash"})

        assert result.result.decision == Decision.ASK
        assert "To disable: handlers.pre_tool_use.risky_command" in result.result.reason
        assert "(set enabled: false)" in result.result.reason

    def test_allow_result_does_not_include_config_path(self) -> None:
        """ALLOW result should NOT include config path footer."""
        router = EventRouter()
        handler = StubHandler(
            name="some_handler",
            terminal=True,
            result=HookResult.allow(context=["Some context"]),
        )
        router.register(EventType.PRE_TOOL_USE, handler)

        result = router.route(EventType.PRE_TOOL_USE, {"tool_name": "Bash"})

        assert result.result.decision == Decision.ALLOW
        assert result.result.reason is None

    def test_config_path_format_pre_tool_use(self) -> None:
        """Config path should use handlers.pre_tool_use.{config_key} format."""
        router = EventRouter()
        handler = StubHandler(
            name="sed_blocker",
            terminal=True,
            result=HookResult.deny(reason="Blocked"),
        )
        router.register(EventType.PRE_TOOL_USE, handler)

        result = router.route(EventType.PRE_TOOL_USE, {"tool_name": "Bash"})

        assert "handlers.pre_tool_use.sed_blocker" in result.result.reason

    def test_config_path_format_post_tool_use(self) -> None:
        """Config path should use handlers.post_tool_use.{config_key} format."""
        router = EventRouter()
        handler = StubHandler(
            name="validate_eslint",
            terminal=True,
            result=HookResult.deny(reason="ESLint failed"),
        )
        router.register(EventType.POST_TOOL_USE, handler)

        result = router.route(EventType.POST_TOOL_USE, {"tool_name": "Bash"})

        assert "handlers.post_tool_use.validate_eslint" in result.result.reason

    def test_config_path_format_session_start(self) -> None:
        """Config path should use handlers.session_start.{config_key} format."""
        router = EventRouter()
        handler = StubHandler(
            name="yolo_detection",
            terminal=True,
            result=HookResult.deny(reason="Not in container"),
        )
        router.register(EventType.SESSION_START, handler)

        result = router.route(EventType.SESSION_START, {})

        assert "handlers.session_start.yolo_detection" in result.result.reason

    def test_config_path_format_stop(self) -> None:
        """Config path should use handlers.stop.{config_key} format."""
        router = EventRouter()
        handler = StubHandler(
            name="stop_guard",
            terminal=True,
            result=HookResult.deny(reason="Cannot stop"),
        )
        router.register(EventType.STOP, handler)

        result = router.route(EventType.STOP, {})

        assert "handlers.stop.stop_guard" in result.result.reason

    def test_deny_with_none_reason_gets_config_path(self) -> None:
        """DENY with None reason should still get config path footer."""
        router = EventRouter()
        handler = StubHandler(
            name="strict_handler",
            terminal=True,
            result=HookResult(decision=Decision.DENY, reason=None),
        )
        router.register(EventType.PRE_TOOL_USE, handler)

        result = router.route(EventType.PRE_TOOL_USE, {"tool_name": "Bash"})

        assert result.result.decision == Decision.DENY
        assert "To disable: handlers.pre_tool_use.strict_handler" in result.result.reason
        assert "(set enabled: false)" in result.result.reason

    def test_footer_separated_by_blank_line(self) -> None:
        """Footer should be separated from original reason by a blank line."""
        router = EventRouter()
        handler = StubHandler(
            name="test_handler",
            terminal=True,
            result=HookResult.deny(reason="Original reason"),
        )
        router.register(EventType.PRE_TOOL_USE, handler)

        result = router.route(EventType.PRE_TOOL_USE, {"tool_name": "Bash"})

        # Should have blank line between original reason and footer
        assert "Original reason\n\nTo disable:" in result.result.reason

    def test_non_terminal_deny_gets_config_path(self) -> None:
        """Non-terminal handler DENY result should also get config path."""
        router = EventRouter()
        handler = StubHandler(
            name="advisory_handler",
            terminal=False,
            result=HookResult.deny(reason="Advisory block"),
        )
        router.register(EventType.PRE_TOOL_USE, handler)

        result = router.route(EventType.PRE_TOOL_USE, {"tool_name": "Bash"})

        assert result.result.decision == Decision.DENY
        assert "To disable: handlers.pre_tool_use.advisory_handler" in result.result.reason

    def test_config_key_uses_handler_config_key_attribute(self) -> None:
        """Should use handler's config_key attribute, not handler name."""
        router = EventRouter()
        # Handler with hyphenated name gets underscore config_key
        handler = StubHandler(
            name="my-handler",
            terminal=True,
            result=HookResult.deny(reason="Blocked"),
        )
        router.register(EventType.PRE_TOOL_USE, handler)

        result = router.route(EventType.PRE_TOOL_USE, {"tool_name": "Bash"})

        # config_key converts hyphens to underscores
        assert "handlers.pre_tool_use.my_handler" in result.result.reason

    def test_route_by_string_also_injects_config_path(self) -> None:
        """route_by_string should also inject config path."""
        router = EventRouter()
        handler = StubHandler(
            name="test_handler",
            terminal=True,
            result=HookResult.deny(reason="Blocked"),
        )
        router.register(EventType.PRE_TOOL_USE, handler)

        result = router.route_by_string("PreToolUse", {"tool_name": "Bash"})

        assert result.decision == Decision.DENY
        assert "To disable: handlers.pre_tool_use.test_handler" in result.reason

    def test_allow_with_reason_not_modified(self) -> None:
        """ALLOW result with a reason should NOT get config path footer."""
        router = EventRouter()
        handler = StubHandler(
            name="some_handler",
            terminal=True,
            result=HookResult(
                decision=Decision.ALLOW,
                reason="Allowed with reason",
            ),
        )
        router.register(EventType.PRE_TOOL_USE, handler)

        result = router.route(EventType.PRE_TOOL_USE, {"tool_name": "Bash"})

        assert result.result.decision == Decision.ALLOW
        assert result.result.reason == "Allowed with reason"
        assert "To disable:" not in (result.result.reason or "")

    def test_no_handlers_matched_no_injection(self) -> None:
        """When no handlers match, no config path should be injected."""
        router = EventRouter()

        result = router.route(EventType.PRE_TOOL_USE, {"tool_name": "Bash"})

        assert result.result.decision == Decision.ALLOW
        assert result.result.reason is None


class TestConfigKeyInjectionInFrontController:
    """Config key injection at the FrontController level (legacy path)."""

    def test_deny_result_includes_config_path(self) -> None:
        """FrontController DENY result should include config path footer."""
        from claude_code_hooks_daemon.core.front_controller import FrontController

        fc = FrontController("PreToolUse")
        handler = StubHandler(
            name="destructive_git",
            terminal=True,
            result=HookResult.deny(reason="Blocked"),
        )
        fc.register(handler)

        result = fc.dispatch({"tool_name": "Bash"})

        assert result.decision == Decision.DENY
        assert "To disable: handlers.pre_tool_use.destructive_git" in result.reason
        assert "(set enabled: false)" in result.reason

    def test_allow_result_not_modified(self) -> None:
        """FrontController ALLOW result should NOT be modified."""
        from claude_code_hooks_daemon.core.front_controller import FrontController

        fc = FrontController("PreToolUse")
        handler = StubHandler(
            name="some_handler",
            terminal=True,
            result=HookResult.allow(),
        )
        fc.register(handler)

        result = fc.dispatch({"tool_name": "Bash"})

        assert result.decision == Decision.ALLOW
        assert result.reason is None

    def test_ask_result_includes_config_path(self) -> None:
        """FrontController ASK result should include config path footer."""
        from claude_code_hooks_daemon.core.front_controller import FrontController

        fc = FrontController("PostToolUse")
        handler = StubHandler(
            name="confirm_handler",
            terminal=True,
            result=HookResult.ask(reason="Please confirm"),
        )
        fc.register(handler)

        result = fc.dispatch({"tool_name": "Bash"})

        assert result.decision == Decision.ASK
        assert "To disable: handlers.post_tool_use.confirm_handler" in result.reason

    def test_deny_with_none_reason(self) -> None:
        """FrontController DENY with None reason should get config path."""
        from claude_code_hooks_daemon.core.front_controller import FrontController

        fc = FrontController("PreToolUse")
        handler = StubHandler(
            name="strict_handler",
            terminal=True,
            result=HookResult(decision=Decision.DENY, reason=None),
        )
        fc.register(handler)

        result = fc.dispatch({"tool_name": "Bash"})

        assert result.decision == Decision.DENY
        assert "To disable: handlers.pre_tool_use.strict_handler" in result.reason
