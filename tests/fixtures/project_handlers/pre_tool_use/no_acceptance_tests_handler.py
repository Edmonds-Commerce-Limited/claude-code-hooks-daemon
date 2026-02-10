"""Handler that returns empty acceptance tests for testing warning path."""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision


class NoAcceptanceTestsHandler(Handler):
    """Handler that returns no acceptance tests."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="no-acceptance-tests",
            priority=50,
            terminal=False,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return []
