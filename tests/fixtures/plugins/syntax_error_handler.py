"""Handler with intentional syntax error for testing."""

from claude_code_hooks_daemon.core import Handler, HookResult


class BrokenHandler(Handler):
    """Handler with syntax error."""

    def __init__(self, config=None
        # Intentional syntax error - missing closing parenthesis
