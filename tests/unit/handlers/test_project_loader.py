"""Unit tests for ProjectHandlerLoader."""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.handlers.project_loader import ProjectHandlerLoader


class TestDiscoverHandlers:
    """Test project handler discovery from convention-based directory structure."""

    @pytest.fixture
    def project_handlers_dir(self) -> Path:
        """Return path to test project handler fixtures."""
        return Path(__file__).parent.parent.parent / "fixtures" / "project_handlers"

    @pytest.fixture
    def error_cases_dir(self) -> Path:
        """Return path to error case fixtures (intentionally broken handlers)."""
        return Path(__file__).parent.parent.parent / "fixtures" / "project_handlers_error_cases"

    def test_discover_handlers_finds_valid_handlers(self, project_handlers_dir: Path) -> None:
        """Test that discover_handlers finds handlers in event-type subdirectories."""
        results = ProjectHandlerLoader.discover_handlers(project_handlers_dir)

        assert len(results) >= 2
        # Should find vendor_reminder in pre_tool_use/ and build_checker in post_tool_use/
        event_types = [et for et, _ in results]
        assert EventType.PRE_TOOL_USE in event_types
        assert EventType.POST_TOOL_USE in event_types

    def test_discover_handlers_returns_handler_instances(self, project_handlers_dir: Path) -> None:
        """Test that discovered handlers are proper Handler instances."""
        results = ProjectHandlerLoader.discover_handlers(project_handlers_dir)

        for event_type, handler in results:
            assert isinstance(handler, Handler)
            assert isinstance(event_type, EventType)

    def test_discover_handlers_skips_test_files(self, project_handlers_dir: Path) -> None:
        """Test that files starting with test_ are skipped."""
        results = ProjectHandlerLoader.discover_handlers(project_handlers_dir)

        handler_names = [h.name for _, h in results]
        # test_should_be_skipped.py should not produce a handler
        assert "test-should-be-skipped" not in handler_names

    def test_discover_handlers_skips_underscore_files(self, project_handlers_dir: Path) -> None:
        """Test that files starting with _ are skipped."""
        results = ProjectHandlerLoader.discover_handlers(project_handlers_dir)

        handler_names = [h.name for _, h in results]
        # _private_helper.py should not produce a handler
        assert "private-helper" not in handler_names

    def test_discover_handlers_skips_init_files(self, project_handlers_dir: Path) -> None:
        """Test that __init__.py files are skipped."""
        results = ProjectHandlerLoader.discover_handlers(project_handlers_dir)

        handler_names = [h.name for _, h in results]
        assert "__init__" not in handler_names

    def test_discover_handlers_maps_event_types_correctly(self, project_handlers_dir: Path) -> None:
        """Test that handlers are mapped to correct event types from directory names."""
        results = ProjectHandlerLoader.discover_handlers(project_handlers_dir)

        event_handler_map: dict[EventType, list[str]] = {}
        for event_type, handler in results:
            event_handler_map.setdefault(event_type, []).append(handler.name)

        # vendor_reminder should be in PRE_TOOL_USE
        assert "vendor-reminder" in event_handler_map.get(EventType.PRE_TOOL_USE, [])
        # build_checker should be in POST_TOOL_USE
        assert "build-checker" in event_handler_map.get(EventType.POST_TOOL_USE, [])

    def test_discover_handlers_handles_nonexistent_path(self) -> None:
        """Test that non-existent path returns empty list."""
        results = ProjectHandlerLoader.discover_handlers(Path("/nonexistent/path"))
        assert results == []

    def test_discover_handlers_handles_empty_directory(self, tmp_path: Path) -> None:
        """Test that empty directory returns empty list."""
        results = ProjectHandlerLoader.discover_handlers(tmp_path)
        assert results == []

    def test_discover_handlers_crashes_on_syntax_errors(self, error_cases_dir: Path) -> None:
        """Test that any error in handler files crashes (TIER 1: project handlers).

        Project handlers are explicitly written by the user - any error must
        be immediately visible, not silently skipped. Discovery stops at the
        first error encountered.
        """
        # The error_cases directory contains multiple error types
        # Discovery should crash when it tries to load the first one
        with pytest.raises(RuntimeError, match="Failed to .* project handler"):
            ProjectHandlerLoader.discover_handlers(error_cases_dir)

    def test_discover_handlers_ignores_non_event_directories(self, tmp_path: Path) -> None:
        """Test that directories not matching event types are ignored."""
        # Create a directory that doesn't match any event type
        unknown_dir = tmp_path / "unknown_event_type"
        unknown_dir.mkdir()
        handler_file = unknown_dir / "some_handler.py"
        handler_file.write_text('"""Not a real handler."""\n')

        results = ProjectHandlerLoader.discover_handlers(tmp_path)
        assert results == []

    def test_discover_handlers_with_single_event_type_dir(self, tmp_path: Path) -> None:
        """Test discovery with only one event type directory."""
        pre_tool_dir = tmp_path / "pre_tool_use"
        pre_tool_dir.mkdir()

        handler_code = '''"""Simple handler."""
from typing import Any
from claude_code_hooks_daemon.core import Handler, HookResult, AcceptanceTest, TestType
from claude_code_hooks_daemon.core.hook_result import Decision

class SimpleHandler(Handler):
    def __init__(self) -> None:
        super().__init__(handler_id="simple-test", priority=50)
    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True
    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)
    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [AcceptanceTest(
            title="test", command="echo test", description="test",
            expected_decision=Decision.ALLOW, expected_message_patterns=[],
            test_type=TestType.BLOCKING,
        )]
'''
        (pre_tool_dir / "simple_handler.py").write_text(handler_code)

        results = ProjectHandlerLoader.discover_handlers(tmp_path)
        assert len(results) == 1
        assert results[0][0] == EventType.PRE_TOOL_USE
        assert results[0][1].name == "simple-test"


class TestLoadHandlerFromFile:
    """Test loading a single handler from a Python file."""

    @pytest.fixture
    def project_handlers_dir(self) -> Path:
        """Return path to test project handler fixtures."""
        return Path(__file__).parent.parent.parent / "fixtures" / "project_handlers"

    @pytest.fixture
    def error_cases_dir(self) -> Path:
        """Return path to error case fixtures (intentionally broken handlers)."""
        return Path(__file__).parent.parent.parent / "fixtures" / "project_handlers_error_cases"

    def test_load_valid_handler(self, project_handlers_dir: Path) -> None:
        """Test loading a valid handler from a file."""
        handler_file = project_handlers_dir / "pre_tool_use" / "vendor_reminder.py"
        handler = ProjectHandlerLoader.load_handler_from_file(handler_file)

        assert handler is not None
        assert isinstance(handler, Handler)
        assert handler.name == "vendor-reminder"
        assert handler.priority == 45

    def test_load_handler_crashes_for_nonexistent_file(self) -> None:
        """Test that loading from non-existent file crashes (TIER 1: project handlers)."""
        with pytest.raises(RuntimeError, match="Project handler file not found"):
            ProjectHandlerLoader.load_handler_from_file(Path("/nonexistent/handler.py"))

    def test_load_handler_crashes_for_syntax_error(self, error_cases_dir: Path) -> None:
        """Test that loading file with syntax errors crashes (TIER 1: project handlers)."""
        handler_file = error_cases_dir / "session_start" / "syntax_error_handler.py"
        with pytest.raises(RuntimeError, match="Failed to import project handler"):
            ProjectHandlerLoader.load_handler_from_file(handler_file)

    def test_load_handler_crashes_for_non_handler_class(self, tmp_path: Path) -> None:
        """Test that file without Handler subclass crashes (TIER 1: project handlers)."""
        handler_file = tmp_path / "not_a_handler.py"
        handler_file.write_text('"""Not a handler."""\n\nclass NotAHandler:\n    pass\n')
        with pytest.raises(RuntimeError, match="No Handler subclass found"):
            ProjectHandlerLoader.load_handler_from_file(handler_file)

    def test_load_handler_crashes_on_errors(
        self,
        error_cases_dir: Path,
    ) -> None:
        """Test that loading errors crash (TIER 1: project handlers)."""
        handler_file = error_cases_dir / "session_start" / "syntax_error_handler.py"
        with pytest.raises(RuntimeError, match="Failed to import project handler"):
            ProjectHandlerLoader.load_handler_from_file(handler_file)

    def test_load_handler_crashes_when_spec_is_none(
        self,
        project_handlers_dir: Path,
    ) -> None:
        """Test that None spec from spec_from_file_location crashes (TIER 1)."""
        handler_file = project_handlers_dir / "pre_tool_use" / "vendor_reminder.py"
        with patch(
            "claude_code_hooks_daemon.handlers.project_loader.importlib.util.spec_from_file_location",
            return_value=None,
        ):
            with pytest.raises(RuntimeError, match="Failed to create module spec"):
                ProjectHandlerLoader.load_handler_from_file(handler_file)

    def test_load_handler_crashes_when_instantiation_fails(
        self,
        error_cases_dir: Path,
    ) -> None:
        """Test that handler instantiation failure crashes (TIER 1: project handlers)."""
        handler_file = error_cases_dir / "pre_tool_use" / "instantiation_error_handler.py"
        with pytest.raises(RuntimeError, match="Failed to instantiate project handler"):
            ProjectHandlerLoader.load_handler_from_file(handler_file)

    def test_load_handler_warns_when_no_acceptance_tests(
        self,
        project_handlers_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that handler with empty acceptance tests logs a warning."""
        handler_file = project_handlers_dir / "pre_tool_use" / "no_acceptance_tests_handler.py"
        with caplog.at_level(logging.WARNING):
            result = ProjectHandlerLoader.load_handler_from_file(handler_file)

        assert result is not None
        assert result.name == "no-acceptance-tests"
        assert any(
            "does not define acceptance tests" in record.message for record in caplog.records
        )

    def test_load_handler_warns_when_acceptance_tests_raise(
        self,
        error_cases_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that handler with broken acceptance tests logs a warning.

        Note: Acceptance test failures are warnings, not crashes (TIER 3).
        The handler can still run even if acceptance tests are broken.
        """
        handler_file = error_cases_dir / "pre_tool_use" / "broken_acceptance_tests_handler.py"
        with caplog.at_level(logging.WARNING):
            result = ProjectHandlerLoader.load_handler_from_file(handler_file)

        assert result is not None
        assert result.name == "broken-acceptance-tests"
        assert any(
            "failed to return acceptance tests" in record.message for record in caplog.records
        )

    def test_load_handler_crashes_on_multiple_handler_subclasses(
        self,
        tmp_path: Path,
    ) -> None:
        """Test that multiple Handler subclasses in one file crashes (TIER 1).

        Regression test for M2: When multiple Handler subclasses are found,
        it's ambiguous which to use - crash instead of guessing.
        """
        handler_code = '''"""Handler file with multiple Handler subclasses."""
from typing import Any
from claude_code_hooks_daemon.core import Handler, HookResult, AcceptanceTest, TestType
from claude_code_hooks_daemon.core.hook_result import Decision

class FirstHandler(Handler):
    def __init__(self) -> None:
        super().__init__(handler_id="first-handler", priority=50)
    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True
    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)
    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [AcceptanceTest(
            title="test", command="echo test", description="test",
            expected_decision=Decision.ALLOW, expected_message_patterns=[],
            test_type=TestType.BLOCKING,
        )]

class SecondHandler(Handler):
    def __init__(self) -> None:
        super().__init__(handler_id="second-handler", priority=60)
    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False
    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)
    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [AcceptanceTest(
            title="test", command="echo test", description="test",
            expected_decision=Decision.ALLOW, expected_message_patterns=[],
            test_type=TestType.BLOCKING,
        )]
'''
        handler_file = tmp_path / "multi_handler.py"
        handler_file.write_text(handler_code)

        with pytest.raises(RuntimeError, match="Multiple Handler subclasses found"):
            ProjectHandlerLoader.load_handler_from_file(handler_file)
