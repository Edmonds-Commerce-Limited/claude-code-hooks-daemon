"""Handler that raises during instantiation for testing error handling."""

from typing import Any

from claude_code_hooks_daemon.core import AcceptanceTest, Handler, HookResult
from claude_code_hooks_daemon.core.hook_result import Decision


class InstantiationErrorHandler(Handler):
    """Handler that always fails to instantiate."""

    def __init__(self) -> None:
        raise RuntimeError("Deliberate instantiation failure for testing")

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return []
