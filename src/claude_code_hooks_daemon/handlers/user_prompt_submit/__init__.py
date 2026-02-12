"""UserPromptSubmit handlers for claude-code-hooks-daemon."""

from .critical_thinking_advisory import CriticalThinkingAdvisoryHandler
from .git_context_injector import GitContextInjectorHandler

__all__ = [
    "CriticalThinkingAdvisoryHandler",
    "GitContextInjectorHandler",
]
