"""Unit tests for ProjectHandlerLoader."""

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.handler import Handler
from claude_code_hooks_daemon.handlers.project_loader import (
    ProjectHandlerDiscovery,
    ProjectHandlerLoader,
    ProjectHandlerLoadFailure,
)


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

    def test_discover_handlers_skips_broken_handlers_and_logs_warnings(
        self,
        error_cases_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that broken handlers are skipped and a warning is logged.

        Project handlers are user code — an upstream upgrade should not kill
        the daemon. Broken handlers are skipped gracefully so the daemon starts
        with all remaining working handlers still active.
        """
        with caplog.at_level(logging.WARNING):
            results = ProjectHandlerLoader.discover_handlers(error_cases_dir)

        # Broken handlers skipped → returns only successfully loaded handlers
        # (may be empty if all broken, but must not raise)
        assert isinstance(results, list)
        # At least one warning logged for each skipped handler
        assert any("Skipping project handler" in record.message for record in caplog.records)

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
    def get_claude_md(self) -> str | None:
        return None
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

    def test_discover_handlers_skips_broken_handler_and_loads_working_one(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that a broken handler is skipped while a working one still loads.

        This is the core resilience guarantee: one broken project handler must
        not prevent other working project handlers from loading.
        """
        pre_tool_dir = tmp_path / "pre_tool_use"
        pre_tool_dir.mkdir()

        # Broken handler — syntax error
        (pre_tool_dir / "aaa_broken_handler.py").write_text("this is not valid python !!!")

        # Working handler
        working_code = '''"""Working handler."""
from typing import Any
from claude_code_hooks_daemon.core import Handler, HookResult, AcceptanceTest, TestType
from claude_code_hooks_daemon.core.hook_result import Decision

class WorkingHandler(Handler):
    def __init__(self) -> None:
        super().__init__(handler_id="working-handler", priority=50)
    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False
    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)
    def get_claude_md(self) -> str | None:
        return None
    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [AcceptanceTest(
            title="test", command="echo test", description="test",
            expected_decision=Decision.ALLOW, expected_message_patterns=[],
            test_type=TestType.BLOCKING,
        )]
'''
        (pre_tool_dir / "zzz_working_handler.py").write_text(working_code)

        with caplog.at_level(logging.WARNING):
            results = ProjectHandlerLoader.discover_handlers(tmp_path)

        # Working handler loaded despite broken one
        assert len(results) == 1
        assert results[0][1].name == "working-handler"
        # Warning logged for the skipped handler
        assert any("Skipping project handler" in record.message for record in caplog.records)


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
    def get_claude_md(self) -> str | None:
        return None
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
    def get_claude_md(self) -> str | None:
        return None
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

    def test_load_handler_gives_version_specific_error_for_missing_get_claude_md(
        self,
        error_cases_dir: Path,
    ) -> None:
        """Test that a handler missing get_claude_md() gets a version-specific error.

        Regression test for v2.30.0 breaking change: get_claude_md() became abstract.
        The error must name the method and the version it was introduced, so users
        know exactly what to add and why, rather than seeing "No Handler subclass found".
        """
        handler_file = error_cases_dir / "pre_tool_use" / "missing_get_claude_md_handler.py"
        with pytest.raises(RuntimeError) as exc_info:
            ProjectHandlerLoader.load_handler_from_file(handler_file)

        error_message = str(exc_info.value)
        assert (
            "get_claude_md" in error_message
        ), f"Error should name the missing method, got: {error_message}"
        assert (
            "2.30.0" in error_message
        ), f"Error should include the version that introduced the method, got: {error_message}"

    def test_an_imported_base_is_not_blamed_for_the_missing_method(
        self,
        tmp_path: Path,
    ) -> None:
        """The incomplete-handler error must name the USER's class, not ours.

        Once a project handler subclasses its event's base, that base is an
        abstract ``Handler`` subclass sitting in the module namespace. The
        diagnostic that lists abstract classes would otherwise pick it up and
        tell the client their handler is missing ``handle``, ``matches`` and
        everything else — pointing at a daemon-internal class they cannot fix.
        """
        handler_code = '''"""Handler that forgot get_claude_md."""
from typing import Any
from claude_code_hooks_daemon.core import AcceptanceTest, GatingResult, TestType
from claude_code_hooks_daemon.core.handler_bases import PreToolUseHandlerBase

class IncompleteHandler(PreToolUseHandlerBase):
    def __init__(self) -> None:
        super().__init__(handler_id="incomplete", priority=50)

    def matches(self, hook_input: dict[str, Any]) -> bool:
        return False

    def handle(self, hook_input: dict[str, Any]) -> GatingResult:
        return GatingResult.allow()

    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return []
'''
        handler_file = tmp_path / "incomplete_handler.py"
        handler_file.write_text(handler_code)

        with pytest.raises(RuntimeError) as exc_info:
            ProjectHandlerLoader.load_handler_from_file(handler_file)

        error_message = str(exc_info.value)
        assert "IncompleteHandler" in error_message
        assert "PreToolUseHandlerBase" not in error_message
        assert "GatingHandler" not in error_message

    def test_load_handler_applies_default_priority_when_none(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that handler with None priority gets default (50) applied.

        Regression test for Plan 00070: project handlers that somehow end
        up with priority=None should get the default applied and a warning logged.
        """
        handler_code = '''"""Handler that sets priority to None."""
from typing import Any
from claude_code_hooks_daemon.core import Handler, HookResult, AcceptanceTest, TestType
from claude_code_hooks_daemon.core.hook_result import Decision

class NullPriorityHandler(Handler):
    def __init__(self) -> None:
        super().__init__(handler_id="null-priority", priority=50)
        # Simulate priority being set to None after init
        setattr(self, "priority", None)
    def matches(self, hook_input: dict[str, Any]) -> bool:
        return True
    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        return HookResult(decision=Decision.ALLOW)
    def get_claude_md(self) -> str | None:
        return None
    def get_acceptance_tests(self) -> list[AcceptanceTest]:
        return [AcceptanceTest(
            title="test", command="echo test", description="test",
            expected_decision=Decision.ALLOW, expected_message_patterns=[],
            test_type=TestType.BLOCKING,
        )]
'''
        handler_file = tmp_path / "null_priority_handler.py"
        handler_file.write_text(handler_code)

        with caplog.at_level(logging.WARNING):
            handler = ProjectHandlerLoader.load_handler_from_file(handler_file)

        assert handler is not None
        assert handler.priority == 50  # Default applied
        assert isinstance(handler.priority, int)
        assert any(
            "None priority" in record.message or "default" in record.message.lower()
            for record in caplog.records
        )


class TestDiscoverHandlersWithFailures:
    """Test the failure-aware discovery API (Plan 00143).

    ``discover_handlers_with_failures`` returns BOTH the successfully loaded
    handlers AND structured records of every handler that failed to load, so
    the running daemon can persist and loudly surface protection regressions
    instead of dropping them into a log line nobody reads.
    """

    @pytest.fixture
    def project_handlers_dir(self) -> Path:
        """Return path to test project handler fixtures (all valid)."""
        return Path(__file__).parent.parent.parent / "fixtures" / "project_handlers"

    @pytest.fixture
    def error_cases_dir(self) -> Path:
        """Return path to error case fixtures (intentionally broken handlers)."""
        return Path(__file__).parent.parent.parent / "fixtures" / "project_handlers_error_cases"

    def test_returns_discovery_dataclass(self, project_handlers_dir: Path) -> None:
        """A ProjectHandlerDiscovery with handlers + failures is returned."""
        discovery = ProjectHandlerLoader.discover_handlers_with_failures(project_handlers_dir)

        assert isinstance(discovery, ProjectHandlerDiscovery)
        assert isinstance(discovery.handlers, list)
        assert isinstance(discovery.failures, list)

    def test_valid_handlers_have_no_failures(self, project_handlers_dir: Path) -> None:
        """A directory of valid handlers loads cleanly with zero failures."""
        discovery = ProjectHandlerLoader.discover_handlers_with_failures(project_handlers_dir)

        assert len(discovery.handlers) >= 2
        assert discovery.failures == []

    def test_broken_handlers_recorded_as_structured_failures(self, error_cases_dir: Path) -> None:
        """Each broken handler becomes a ProjectHandlerLoadFailure with details."""
        discovery = ProjectHandlerLoader.discover_handlers_with_failures(error_cases_dir)

        assert len(discovery.failures) >= 1
        for failure in discovery.failures:
            assert isinstance(failure, ProjectHandlerLoadFailure)
            assert failure.filename.endswith(".py")
            assert failure.event_dir  # non-empty event directory name
            assert failure.reason  # non-empty human-readable reason

    def test_failure_reason_names_missing_method_and_version(self, error_cases_dir: Path) -> None:
        """The missing-get_claude_md handler's failure reason is actionable.

        Regression coverage for the v2.30.0 silent-skip class: the reason must
        name the method and the version that introduced it so the alert tells
        the user exactly what to fix.
        """
        discovery = ProjectHandlerLoader.discover_handlers_with_failures(error_cases_dir)

        reasons = "\n".join(f.reason for f in discovery.failures)
        filenames = {f.filename for f in discovery.failures}
        assert "missing_get_claude_md_handler.py" in filenames
        assert "get_claude_md" in reasons
        assert "2.30.0" in reasons

    def test_failure_records_correct_event_dir(self, error_cases_dir: Path) -> None:
        """The session_start syntax-error handler is recorded under session_start."""
        discovery = ProjectHandlerLoader.discover_handlers_with_failures(error_cases_dir)

        by_name = {f.filename: f for f in discovery.failures}
        assert "syntax_error_handler.py" in by_name
        assert by_name["syntax_error_handler.py"].event_dir == "session_start"

    def test_nonexistent_path_yields_empty_discovery(self) -> None:
        """A non-existent path returns empty handlers and empty failures."""
        discovery = ProjectHandlerLoader.discover_handlers_with_failures(Path("/nonexistent/path"))

        assert discovery.handlers == []
        assert discovery.failures == []

    def test_discover_handlers_delegates_to_failure_aware_api(
        self, project_handlers_dir: Path
    ) -> None:
        """The backward-compatible discover_handlers returns the same handlers."""
        legacy = ProjectHandlerLoader.discover_handlers(project_handlers_dir)
        discovery = ProjectHandlerLoader.discover_handlers_with_failures(project_handlers_dir)

        legacy_names = sorted(h.name for _, h in legacy)
        discovery_names = sorted(h.name for _, h in discovery.handlers)
        assert legacy_names == discovery_names
