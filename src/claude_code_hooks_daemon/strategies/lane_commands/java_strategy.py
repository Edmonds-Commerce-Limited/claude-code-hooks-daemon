"""Java lane-command strategy - JVM build tools, judged by their goal."""

from typing import Any

from claude_code_hooks_daemon.strategies.lane_commands.common import lane_acceptance_test

_LANGUAGE_NAME = "Java"
#: `mvn deploy` and `gradle publish` ship an artefact and are deployment.
_SHIPPING_GOAL = r"(?!(?:.*\s)?(?:deploy|publish)(?:\s|$))"
_LANE_PATTERNS: tuple[str, ...] = (
    r"^ant\b",
    rf"^(?:gradle|gradlew|mvn){_SHIPPING_GOAL}\b",
)
_ACCEPTANCE_COMMAND = "mvn test"


class JavaLaneCommandStrategy:
    """Lane commands for JVM projects."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def lane_patterns(self) -> tuple[str, ...]:
        return _LANE_PATTERNS

    def get_acceptance_tests(self) -> list[Any]:
        """A host seat's mvn test run is refused."""
        return [lane_acceptance_test(_LANGUAGE_NAME, _ACCEPTANCE_COMMAND)]
