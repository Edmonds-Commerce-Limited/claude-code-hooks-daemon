"""Handler missing required methods."""

from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.core import Handler


class MissingMethodsHandler(Handler):
    """Handler that doesn't implement required methods."""

    def __init__(self, config=None):
        """Initialise the handler.

        Args:
            config: Optional configuration dictionary
        """
        super().__init__(name="missing-methods", priority=Priority.HELLO_WORLD)
        self.config = config

    # Missing matches() and handle() methods
