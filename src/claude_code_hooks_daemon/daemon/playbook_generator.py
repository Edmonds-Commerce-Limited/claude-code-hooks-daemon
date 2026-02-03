"""Playbook generator for acceptance testing.

This module generates acceptance test playbooks from handler definitions.
Handlers implement get_acceptance_tests() which returns AcceptanceTest objects.
This generator collects all tests and formats them as a markdown playbook.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from claude_code_hooks_daemon.constants import ConfigKey
from claude_code_hooks_daemon.core import AcceptanceTest
from claude_code_hooks_daemon.handlers.registry import EVENT_TYPE_MAPPING

if TYPE_CHECKING:
    from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

logger = logging.getLogger(__name__)


class PlaybookGenerator:
    """Generate acceptance test playbooks from handler definitions."""

    __slots__ = ("_config", "_registry")

    def __init__(self, config: dict[str, Any], registry: HandlerRegistry) -> None:
        """Initialize playbook generator.

        Args:
            config: Configuration dictionary (handlers section from hooks-daemon.yaml)
            registry: Handler registry with discovered handlers
        """
        self._config = config
        self._registry = registry

    def generate_markdown(self, include_disabled: bool = False) -> str:
        """Generate acceptance test playbook in markdown format.

        Args:
            include_disabled: Include tests from disabled handlers

        Returns:
            Complete playbook as markdown string
        """
        # Collect all acceptance tests from handlers
        tests_by_handler: list[tuple[str, str, int, list[AcceptanceTest]]] = []

        # Iterate through all event types
        for event_dir_name, event_type in EVENT_TYPE_MAPPING.items():
            event_config = self._config.get(event_dir_name, {})

            # Get all handler classes for this event type
            for handler_class_name in self._registry.list_handlers():
                # Get handler class
                handler_class = self._registry.get_handler_class(handler_class_name)
                if not handler_class:
                    continue

                # Check if handler belongs to this event type (by checking module path)
                if event_dir_name not in handler_class.__module__:
                    continue

                # Convert class name to config key (snake_case)
                from claude_code_hooks_daemon.handlers.registry import _to_snake_case

                config_key = _to_snake_case(handler_class_name)
                handler_config = event_config.get(config_key, {})

                # Check if handler is enabled
                is_enabled = handler_config.get(ConfigKey.ENABLED, True)

                if not is_enabled and not include_disabled:
                    logger.debug("Skipping disabled handler: %s", handler_class_name)
                    continue

                # Instantiate handler to call get_acceptance_tests()
                try:
                    instance = handler_class()

                    # Get acceptance tests
                    if hasattr(instance, "get_acceptance_tests"):
                        tests = instance.get_acceptance_tests()
                        if tests:
                            # Get handler priority (may be overridden in config)
                            priority = handler_config.get(ConfigKey.PRIORITY, instance.priority)

                            tests_by_handler.append(
                                (handler_class_name, event_type.value, priority, tests)
                            )
                            logger.debug(
                                "Collected %d tests from %s", len(tests), handler_class_name
                            )
                except Exception as e:
                    logger.warning("Failed to get tests from %s: %s", handler_class_name, e)

        # Sort handlers by priority (lower priority = higher precedence)
        tests_by_handler.sort(key=lambda x: x[2])

        # Generate markdown
        return self._format_playbook(tests_by_handler)

    def _format_playbook(
        self, tests_by_handler: list[tuple[str, str, int, list[AcceptanceTest]]]
    ) -> str:
        """Format tests as markdown playbook.

        Args:
            tests_by_handler: List of (handler_name, event_type, priority, tests)

        Returns:
            Formatted markdown playbook
        """
        lines: list[str] = []

        # Header
        lines.append("# Acceptance Testing Playbook")
        lines.append("")
        lines.append(f"**Version**: Generated {datetime.now().strftime('%Y-%m-%d')}")
        lines.append(
            "**Purpose**: Validate that all hooks daemon handlers work correctly in real Claude Code usage"
        )
        lines.append("")
        lines.append("---")
        lines.append("")

        # Prerequisites section
        lines.append("## Prerequisites")
        lines.append("")
        lines.append("Before starting:")
        lines.append("")
        lines.append("1. **Restart daemon to ensure latest code is loaded**:")
        lines.append("   ```bash")
        lines.append("   $PYTHON -m claude_code_hooks_daemon.daemon.cli restart")
        lines.append("   ```")
        lines.append("   Should show: `Daemon started successfully`")
        lines.append("")
        lines.append("2. **Verify daemon is running**:")
        lines.append("   ```bash")
        lines.append("   $PYTHON -m claude_code_hooks_daemon.daemon.cli status")
        lines.append("   ```")
        lines.append("   Should show: `Status: RUNNING`")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Instructions section
        lines.append("## Instructions")
        lines.append("")
        lines.append("For each test below:")
        lines.append("")
        lines.append("1. Execute the command in a Claude Code session")
        lines.append("2. Verify the expected behavior occurs")
        lines.append("3. Mark the test as PASS or FAIL")
        lines.append("4. If any test fails, stop and fix the issue before continuing")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Tests section
        lines.append("## Tests")
        lines.append("")

        test_number = 1
        for handler_name, event_type, priority, tests in tests_by_handler:
            if not tests:
                continue

            # Handler header
            lines.append(f"### Handler: {handler_name}")
            lines.append("")
            lines.append(f"**Event Type**: {event_type}")
            lines.append(f"**Priority**: {priority}")
            lines.append("")

            for test in tests:
                # Test header
                lines.append(f"#### Test {test_number}: {test.title}")
                lines.append("")

                # Test details
                lines.append(f"**Type**: {test.test_type.value.title()}")
                lines.append(f"**Expected Decision**: {test.expected_decision.value}")
                lines.append("")

                # Description
                lines.append(f"**Description**: {test.description}")
                lines.append("")

                # Setup commands (if any)
                if test.setup_commands:
                    lines.append("**Setup**:")
                    lines.append("```bash")
                    for cmd in test.setup_commands:
                        lines.append(cmd)
                    lines.append("```")
                    lines.append("")

                # Command
                lines.append("**Command**:")
                lines.append("```bash")
                lines.append(test.command)
                lines.append("```")
                lines.append("")

                # Expected message patterns
                if test.expected_message_patterns:
                    lines.append("**Expected Message Patterns**:")
                    for pattern in test.expected_message_patterns:
                        lines.append(f"- `{pattern}`")
                    lines.append("")

                # Safety notes (if any)
                if test.safety_notes:
                    lines.append(f"**Safety**: {test.safety_notes}")
                    lines.append("")

                # Cleanup commands (if any)
                if test.cleanup_commands:
                    lines.append("**Cleanup**:")
                    lines.append("```bash")
                    for cmd in test.cleanup_commands:
                        lines.append(cmd)
                    lines.append("```")
                    lines.append("")

                # Test result checkbox
                lines.append("**Result**: [ ] PASS [ ] FAIL")
                lines.append("")
                lines.append("---")
                lines.append("")

                test_number += 1

        # Summary section
        lines.append("## Summary")
        lines.append("")
        lines.append(f"**Total Tests**: {test_number - 1}")
        lines.append(f"**Total Handlers**: {len(tests_by_handler)}")
        lines.append("")
        lines.append("**Completion Criteria**:")
        lines.append("- [ ] All tests marked PASS")
        lines.append("- [ ] No test failures")
        lines.append("- [ ] Daemon remains running throughout testing")
        lines.append("")

        return "\n".join(lines)
