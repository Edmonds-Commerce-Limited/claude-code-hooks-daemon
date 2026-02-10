"""Unit tests for ProjectHandlerLoader."""

import logging
from pathlib import Path

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

    def test_discover_handlers_handles_syntax_errors_gracefully(
        self, project_handlers_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that syntax errors in handler files are logged and skipped."""
        with caplog.at_level(logging.WARNING):
            results = ProjectHandlerLoader.discover_handlers(project_handlers_dir)

        # Should still load the valid handlers
        handler_names = [h.name for _, h in results]
        assert "vendor-reminder" in handler_names
        assert "build-checker" in handler_names

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

    def test_load_valid_handler(self, project_handlers_dir: Path) -> None:
        """Test loading a valid handler from a file."""
        handler_file = project_handlers_dir / "pre_tool_use" / "vendor_reminder.py"
        handler = ProjectHandlerLoader.load_handler_from_file(handler_file)

        assert handler is not None
        assert isinstance(handler, Handler)
        assert handler.name == "vendor-reminder"
        assert handler.priority == 45

    def test_load_handler_returns_none_for_nonexistent_file(self) -> None:
        """Test that loading from non-existent file returns None."""
        handler = ProjectHandlerLoader.load_handler_from_file(Path("/nonexistent/handler.py"))
        assert handler is None

    def test_load_handler_returns_none_for_syntax_error(self, project_handlers_dir: Path) -> None:
        """Test that loading file with syntax errors returns None."""
        handler_file = project_handlers_dir / "session_start" / "syntax_error_handler.py"
        handler = ProjectHandlerLoader.load_handler_from_file(handler_file)
        assert handler is None

    def test_load_handler_returns_none_for_non_handler_class(self, tmp_path: Path) -> None:
        """Test that file without Handler subclass returns None."""
        handler_file = tmp_path / "not_a_handler.py"
        handler_file.write_text('"""Not a handler."""\n\nclass NotAHandler:\n    pass\n')
        handler = ProjectHandlerLoader.load_handler_from_file(handler_file)
        assert handler is None

    def test_load_handler_logs_errors(
        self,
        project_handlers_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that loading errors are logged."""
        handler_file = project_handlers_dir / "session_start" / "syntax_error_handler.py"
        with caplog.at_level(logging.WARNING):
            ProjectHandlerLoader.load_handler_from_file(handler_file)

        assert any(
            "Failed to load" in record.message or "Failed to import" in record.message
            for record in caplog.records
        )
