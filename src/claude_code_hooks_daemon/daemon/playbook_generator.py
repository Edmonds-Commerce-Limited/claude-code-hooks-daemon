"""Playbook generator for acceptance testing.

This module generates acceptance test playbooks from handler definitions.
Handlers implement get_acceptance_tests() which returns AcceptanceTest objects.
This generator collects all tests and formats them as a markdown playbook
or structured JSON for automated test execution.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from typing import TYPE_CHECKING, Any

from claude_code_hooks_daemon.constants import ConfigKey
from claude_code_hooks_daemon.core import AcceptanceTest
from claude_code_hooks_daemon.handlers.registry import EVENT_TYPE_MAPPING

if TYPE_CHECKING:
    from claude_code_hooks_daemon.handlers.registry import HandlerRegistry

logger = logging.getLogger(__name__)


# Type alias for collected test data tuple:
# (handler_name, event_type_str, priority, tests, source)
CollectedTests = list[tuple[str, str, int, list[AcceptanceTest], str]]


class PlaybookGenerator:
    """Generate acceptance test playbooks from handler definitions."""

    __slots__ = ("_config", "_plugins", "_project_handlers", "_registry")

    def __init__(
        self,
        config: dict[str, Any],
        registry: HandlerRegistry,
        plugins: list[Any] | None = None,
        project_handlers: list[Any] | None = None,
    ) -> None:
        """Initialize playbook generator.

        Args:
            config: Configuration dictionary (handlers section from hooks-daemon.yaml)
            registry: Handler registry with discovered handlers
            plugins: Optional list of plugin handler instances to include in playbook
            project_handlers: Optional list of project handler instances to include in playbook
        """
        self._config = config
        self._registry = registry
        self._plugins = plugins or []
        self._project_handlers = project_handlers or []

    def _collect_tests(
        self, include_disabled: bool = False
    ) -> tuple[CollectedTests, CollectedTests]:
        """Collect acceptance tests from all handler sources.

        Shared logic used by both generate_markdown() and generate_json().

        Args:
            include_disabled: Include tests from disabled handlers

        Returns:
            Tuple of (library_and_plugin_tests, project_handler_tests).
            Each is a list of (handler_name, event_type, priority, tests, source) tuples
            sorted by priority (lower = higher precedence).
        """
        tests_by_handler: CollectedTests = []

        # Iterate through all event types for registry handlers
        for event_dir_name, event_type in EVENT_TYPE_MAPPING.items():
            event_config = self._config.get(event_dir_name, {})

            for handler_class_name in self._registry.list_handlers():
                handler_class = self._registry.get_handler_class(handler_class_name)
                if not handler_class:
                    continue

                if event_dir_name not in handler_class.__module__:
                    continue

                from claude_code_hooks_daemon.handlers.registry import _to_snake_case

                config_key = _to_snake_case(handler_class_name)
                handler_config = event_config.get(config_key, {})

                is_enabled = handler_config.get(ConfigKey.ENABLED, True)

                if not is_enabled and not include_disabled:
                    logger.debug("Skipping disabled handler: %s", handler_class_name)
                    continue

                try:
                    instance = handler_class()

                    if hasattr(instance, "get_acceptance_tests"):
                        tests = instance.get_acceptance_tests()
                        if tests:
                            priority = handler_config.get(ConfigKey.PRIORITY, instance.priority)
                            tests_by_handler.append(
                                (handler_class_name, event_type.value, priority, tests, "library")
                            )
                            logger.debug(
                                "Collected %d tests from %s", len(tests), handler_class_name
                            )
                except Exception as e:
                    logger.warning("Failed to get tests from %s: %s", handler_class_name, e)

        # Collect from plugin handlers
        for plugin_handler in self._plugins:
            try:
                if hasattr(plugin_handler, "get_acceptance_tests"):
                    tests = plugin_handler.get_acceptance_tests()
                    if tests:
                        handler_name = plugin_handler.__class__.__name__
                        event_type_str = getattr(plugin_handler, "event_type", "Plugin")
                        if hasattr(event_type_str, "value"):
                            event_type_str = event_type_str.value

                        tests_by_handler.append(
                            (handler_name, event_type_str, plugin_handler.priority, tests, "plugin")
                        )
                        logger.debug("Collected %d tests from plugin %s", len(tests), handler_name)
            except Exception as e:
                logger.warning(
                    "Failed to get tests from plugin %s: %s", plugin_handler.__class__.__name__, e
                )

        # Collect from project handlers
        project_tests_by_handler: CollectedTests = []
        for project_handler in self._project_handlers:
            try:
                if hasattr(project_handler, "get_acceptance_tests"):
                    tests = project_handler.get_acceptance_tests()
                    if tests:
                        handler_name = project_handler.__class__.__name__
                        event_type_str = getattr(project_handler, "event_type", "Project")
                        if hasattr(event_type_str, "value"):
                            event_type_str = event_type_str.value

                        project_tests_by_handler.append(
                            (
                                handler_name,
                                event_type_str,
                                project_handler.priority,
                                tests,
                                "project",
                            )
                        )
                        logger.debug(
                            "Collected %d tests from project handler %s",
                            len(tests),
                            handler_name,
                        )
            except Exception as e:
                logger.warning(
                    "Failed to get tests from project handler %s: %s",
                    project_handler.__class__.__name__,
                    e,
                )

        # Sort by priority (lower = higher precedence)
        tests_by_handler.sort(key=lambda x: x[2])
        project_tests_by_handler.sort(key=lambda x: x[2])

        return tests_by_handler, project_tests_by_handler

    def generate_markdown(self, include_disabled: bool = False) -> str:
        """Generate acceptance test playbook in markdown format.

        Args:
            include_disabled: Include tests from disabled handlers

        Returns:
            Complete playbook as markdown string
        """
        tests_by_handler, project_tests_by_handler = self._collect_tests(include_disabled)

        # Convert to old format (without source field) for _format_playbook compatibility
        old_format: list[tuple[str, str, int, list[AcceptanceTest]]] = [
            (name, evt, pri, tests) for name, evt, pri, tests, _src in tests_by_handler
        ]
        old_project: list[tuple[str, str, int, list[AcceptanceTest]]] = [
            (name, evt, pri, tests) for name, evt, pri, tests, _src in project_tests_by_handler
        ]

        return self._format_playbook(old_format, old_project)

    def generate_json(
        self,
        include_disabled: bool = False,
        filter_type: str | None = None,
        filter_handler: str | None = None,
    ) -> list[dict[str, Any]]:
        """Generate acceptance tests as structured JSON list.

        Each test is a dictionary with all fields needed for automated execution.

        Args:
            include_disabled: Include tests from disabled handlers
            filter_type: Filter by test type ("blocking", "advisory", "context")
            filter_handler: Filter by handler name substring (case-insensitive)

        Returns:
            List of test dictionaries with fields:
            - test_number: Sequential test number
            - handler_name: Handler class name
            - event_type: Event type string (e.g. "PreToolUse")
            - priority: Handler priority
            - source: Where handler came from ("library", "plugin", "project")
            - title: Test title
            - command: Command to execute
            - description: Test description
            - expected_decision: Expected decision string
            - expected_message_patterns: List of regex patterns
            - test_type: Test type ("blocking", "advisory", "context")
            - setup_commands: Optional list of setup commands
            - cleanup_commands: Optional list of cleanup commands
            - safety_notes: Optional safety notes
            - requires_event: Optional event type required
        """
        tests_by_handler, project_tests_by_handler = self._collect_tests(include_disabled)

        # Combine all tests
        all_handler_tests = tests_by_handler + project_tests_by_handler

        result: list[dict[str, Any]] = []
        test_number = 1

        for handler_name, event_type, priority, tests, source in all_handler_tests:
            for test in tests:
                # Apply filter_type
                if filter_type and test.test_type.value != filter_type:
                    continue

                # Apply filter_handler (case-insensitive substring match)
                if filter_handler and filter_handler.lower() not in handler_name.lower():
                    continue

                test_dict: dict[str, Any] = {
                    "test_number": test_number,
                    "handler_name": handler_name,
                    "event_type": event_type,
                    "priority": priority,
                    "source": source,
                    "title": test.title,
                    "command": test.command,
                    "description": test.description,
                    "expected_decision": test.expected_decision.value,
                    "expected_message_patterns": test.expected_message_patterns,
                    "test_type": test.test_type.value,
                    "setup_commands": test.setup_commands,
                    "cleanup_commands": test.cleanup_commands,
                    "safety_notes": test.safety_notes,
                    "requires_event": test.requires_event,
                    "required_tools": test.required_tools,
                    "tools_available": all(shutil.which(t) for t in (test.required_tools or [])),
                }
                result.append(test_dict)
                test_number += 1

        return result

    def _format_playbook(
        self,
        tests_by_handler: list[tuple[str, str, int, list[AcceptanceTest]]],
        project_tests_by_handler: list[tuple[str, str, int, list[AcceptanceTest]]] | None = None,
    ) -> str:
        """Format tests as markdown playbook.

        Args:
            tests_by_handler: List of (handler_name, event_type, priority, tests)
            project_tests_by_handler: Optional list of project handler tests

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
        lines.append("## Test Categories")
        lines.append("")
        lines.append("Tests are organized into three categories based on how they're verified:")
        lines.append("")
        lines.append("### 1. EXECUTABLE Tests (Blocking + Advisory)")
        lines.append("- **Must be tested** by running commands in main thread")
        lines.append("- PreToolUse handlers that block or provide advisory context")
        lines.append("- Run command, verify expected behaviour (block or advisory message)")
        lines.append("- **Time**: 20-30 minutes for ~89 tests")
        lines.append("")
        lines.append("### 2. OBSERVABLE Tests (Context - Visible)")
        lines.append("- **Quick check** in system-reminders during normal session")
        lines.append("- SessionStart, UserPromptSubmit, PostToolUse lifecycle handlers")
        lines.append("- Just verify messages visible in your current context")
        lines.append("- **Time**: 30 seconds (no commands needed)")
        lines.append("")
        lines.append("### 3. VERIFIED_BY_LOAD Tests (Context - Untriggerable)")
        lines.append("- **Skip these tests** - cannot be triggered on demand")
        lines.append(
            "- SessionEnd, PreCompact, Stop, SubagentStop, Status, Notification, PermissionRequest"
        )
        lines.append("- Verified by daemon loading successfully + unit tests passing")
        lines.append("- **Time**: 0 minutes (already verified by Prerequisites step)")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## Instructions")
        lines.append("")
        lines.append("**For EXECUTABLE tests (Blocking/Advisory):**")
        lines.append("1. Execute the command in a Claude Code session")
        lines.append("2. Verify the expected behaviour occurs")
        lines.append("3. Mark the test as PASS or FAIL")
        lines.append("4. If any test fails, stop and fix the issue before continuing")
        lines.append("")
        lines.append(
            "**For OBSERVABLE tests (Context - SessionStart/UserPromptSubmit/PostToolUse):**"
        )
        lines.append("1. Look at system-reminders in your current session")
        lines.append(
            "2. Verify you see the expected messages (e.g., 'SessionStart hook system active')"
        )
        lines.append("3. No commands needed - just verify messages visible")
        lines.append("")
        lines.append("**For VERIFIED_BY_LOAD tests (Context - Untriggerable):**")
        lines.append("1. Skip these tests entirely")
        lines.append("2. Already verified by daemon loading successfully in Prerequisites")
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

                # Skip if required tools are not installed
                if test.required_tools:
                    missing = [t for t in test.required_tools if not shutil.which(t)]
                    if missing:
                        missing_str = ", ".join(f"`{t}`" for t in missing)
                        lines.append(f"**⚠️ SKIP**: Required tool(s) not installed: {missing_str}")
                        lines.append(f"*Install {', '.join(missing)} to enable this test.*")
                        lines.append("")
                        lines.append("**Result**: SKIP (tool not available)")
                        lines.append("")
                        lines.append("---")
                        lines.append("")
                        test_number += 1
                        continue

                # Test details with category annotation for Context tests
                test_type_str = test.test_type.value.title()
                if test.test_type.value == "context":
                    # Determine if OBSERVABLE or VERIFIED_BY_LOAD
                    observable_events = {"SessionStart", "UserPromptSubmit", "PostToolUse"}
                    if event_type in observable_events:
                        test_type_str = f"{test_type_str} (OBSERVABLE - check system-reminders)"
                    else:
                        test_type_str = f"{test_type_str} (VERIFIED_BY_LOAD - skip test)"

                lines.append(f"**Type**: {test_type_str}")
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

        # Project Handlers section (if any)
        if project_tests_by_handler:
            lines.append("## Project Handlers")
            lines.append("")

            for handler_name, event_type, priority, tests in project_tests_by_handler:
                if not tests:
                    continue

                lines.append(f"### Handler: {handler_name}")
                lines.append("")
                lines.append(f"**Event Type**: {event_type}")
                lines.append(f"**Priority**: {priority}")
                lines.append("**Source**: Project handler")
                lines.append("")

                for test in tests:
                    lines.append(f"#### Test {test_number}: {test.title}")
                    lines.append("")

                    # Skip if required tools are not installed
                    if test.required_tools:
                        missing = [t for t in test.required_tools if not shutil.which(t)]
                        if missing:
                            missing_str = ", ".join(f"`{t}`" for t in missing)
                            lines.append(
                                f"**⚠️ SKIP**: Required tool(s) not installed: {missing_str}"
                            )
                            lines.append(f"*Install {', '.join(missing)} to enable this test.*")
                            lines.append("")
                            lines.append("**Result**: SKIP (tool not available)")
                            lines.append("")
                            lines.append("---")
                            lines.append("")
                            test_number += 1
                            continue

                    # Test details with category annotation for Context tests
                    test_type_str = test.test_type.value.title()
                    if test.test_type.value == "context":
                        # Determine if OBSERVABLE or VERIFIED_BY_LOAD
                        observable_events = {"SessionStart", "UserPromptSubmit", "PostToolUse"}
                        if event_type in observable_events:
                            test_type_str = f"{test_type_str} (OBSERVABLE - check system-reminders)"
                        else:
                            test_type_str = f"{test_type_str} (VERIFIED_BY_LOAD - skip test)"

                    lines.append(f"**Type**: {test_type_str}")
                    lines.append(f"**Expected Decision**: {test.expected_decision.value}")
                    lines.append("")
                    lines.append(f"**Description**: {test.description}")
                    lines.append("")

                    if test.setup_commands:
                        lines.append("**Setup**:")
                        lines.append("```bash")
                        for cmd in test.setup_commands:
                            lines.append(cmd)
                        lines.append("```")
                        lines.append("")

                    lines.append("**Command**:")
                    lines.append("```bash")
                    lines.append(test.command)
                    lines.append("```")
                    lines.append("")

                    if test.expected_message_patterns:
                        lines.append("**Expected Message Patterns**:")
                        for pattern in test.expected_message_patterns:
                            lines.append(f"- `{pattern}`")
                        lines.append("")

                    if test.safety_notes:
                        lines.append(f"**Safety**: {test.safety_notes}")
                        lines.append("")

                    if test.cleanup_commands:
                        lines.append("**Cleanup**:")
                        lines.append("```bash")
                        for cmd in test.cleanup_commands:
                            lines.append(cmd)
                        lines.append("```")
                        lines.append("")

                    lines.append("**Result**: [ ] PASS [ ] FAIL")
                    lines.append("")
                    lines.append("---")
                    lines.append("")

                    test_number += 1

        # Total handler count including project handlers
        total_handler_count = len(tests_by_handler)
        if project_tests_by_handler:
            total_handler_count += len(project_tests_by_handler)

        # Summary section
        lines.append("## Summary")
        lines.append("")
        lines.append(f"**Total Tests**: {test_number - 1}")
        lines.append(f"**Total Handlers**: {total_handler_count}")
        lines.append("")
        lines.append("**Completion Criteria**:")
        lines.append("- [ ] All tests marked PASS")
        lines.append("- [ ] No test failures")
        lines.append("- [ ] Daemon remains running throughout testing")
        lines.append("")

        return "\n".join(lines)
