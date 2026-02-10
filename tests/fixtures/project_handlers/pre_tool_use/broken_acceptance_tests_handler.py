"""Handler whose get_acceptance_tests raises for testing error path."""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision


class BrokenAcceptanceTestsHandler(Handler):
    """Handler that raises when get_acceptance_tests is called."""

    def __init__(self) -> None:
        super().__init__(
            handler_id="broken-acceptance-tests",
            priority=51,
            terminal=False,
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        raise RuntimeError("Deliberate acceptance test failure for testing")
