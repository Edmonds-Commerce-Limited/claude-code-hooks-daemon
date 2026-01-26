"""Invalid handler - not a Handler subclass."""


class InvalidHandler:
    """Not a Handler subclass - for testing error handling."""

    def __init__(self):
        """Initialise the invalid class."""
        self.name = "not-a-handler"

    def matches(self, hook_input: dict) -> bool:
        """Pretend to match.

        Args:
            hook_input: Hook input dictionary

        Returns:
            True
        """
        return True

    def handle(self, hook_input: dict) -> dict:
        """Pretend to handle.

        Args:
            hook_input: Hook input dictionary

        Returns:
            Dict (wrong return type)
        """
        return {"decision": "allow"}
