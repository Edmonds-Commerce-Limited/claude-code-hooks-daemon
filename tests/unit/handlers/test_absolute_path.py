"""Comprehensive tests for AbsolutePathHandler."""

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use.absolute_path import AbsolutePathHandler


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker():
    """Reset the shared DaemonDataLayer singleton around every test in this module."""
    reset_data_layer()
    yield
    reset_data_layer()


class TestAbsolutePathHandler:
    """Test suite for AbsolutePathHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return AbsolutePathHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'require-absolute-paths'."""
        assert handler.name == "require-absolute-paths"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be 12."""
        assert handler.priority == 12

    def test_init_sets_correct_terminal_flag(self, handler):
        """Handler should be terminal (default)."""
        assert handler.terminal is True

    # matches() - Positive Cases: Relative paths (should match)
    def test_matches_write_with_relative_path(self, handler):
        """Should match Write with relative path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.py",
                "content": "print('hello')",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_read_with_relative_path(self, handler):
        """Should match Read with relative path."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "README.md"},
        }
        assert handler.matches(hook_input) is True

    def test_matches_edit_with_relative_path(self, handler):
        """Should match Edit with relative path."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "config.py",
                "old_string": "old",
                "new_string": "new",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_nested_relative_path(self, handler):
        """Should match Write with nested relative path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/components/Header.tsx",
                "content": "export function Header() {}",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_write_with_parent_directory_path(self, handler):
        """Should match Write with parent directory path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "../config/settings.py",
                "content": "SETTINGS = {}",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Absolute paths (should not match)
    def test_matches_write_with_absolute_path_returns_false(self, handler):
        """Should not match Write with absolute path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/test.py",
                "content": "print('hello')",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_read_with_absolute_path_returns_false(self, handler):
        """Should not match Read with absolute path."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/workspace/README.md"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_edit_with_absolute_path_returns_false(self, handler):
        """Should not match Edit with absolute path."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/workspace/config.py",
                "old_string": "old",
                "new_string": "new",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_bash_tool_returns_false(self, handler):
        """Should not match Bash tool (only Read/Write/Edit)."""
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        assert handler.matches(hook_input) is False

    def test_matches_empty_file_path_returns_false(self, handler):
        """Should not match when file_path is empty."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "", "content": "test"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_none_file_path_returns_false(self, handler):
        """Should not match when file_path is None."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": None, "content": "test"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_missing_file_path_returns_false(self, handler):
        """Should not match when file_path is missing."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"content": "test"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_missing_tool_input_returns_false(self, handler):
        """Should not match when tool_input is missing."""
        hook_input = {"tool_name": "Write"}
        assert handler.matches(hook_input) is False

    # handle() Tests - Write Tool
    def test_handle_write_returns_deny_decision(self, handler):
        """handle() should return deny for Write tool with relative path."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "test.py",
                "content": "print('hello')",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_write_reason_contains_blocked_indicator(self, handler):
        """handle() reason should indicate operation is blocked."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "test"},
        }
        result = handler.handle(hook_input)
        assert "BLOCKED" in result.reason

    def test_handle_write_reason_shows_relative_path(self, handler):
        """handle() reason should show the relative path provided."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "config.py", "content": "test"},
        }
        result = handler.handle(hook_input)
        assert "config.py" in result.reason

    def test_handle_write_explains_why_absolute_required(self, handler):
        """handle() reason should explain why absolute paths are required."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "test"},
        }
        result = handler.handle(hook_input)
        assert "absolute" in result.reason.lower()
        assert "required" in result.reason.lower()

    def test_handle_provides_example_rooted_at_this_machines_project(self, handler, monkeypatch):
        """The worked example names the REAL project root, not a hardcoded one.

        This assertion used to pin ``/workspace/`` — this repository's own
        self-install root — so it passed while every client install was told to
        prepend a directory that does not exist there (Plan 00244).
        """
        from pathlib import Path

        from claude_code_hooks_daemon.core import project_context as pc

        client_root = Path("/home/testuser/Projects/example-app")
        monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
        monkeypatch.setattr(
            pc.ProjectContext, "project_root", classmethod(lambda cls: client_root), raising=False
        )

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "test"},
        }
        result = handler.handle(hook_input)
        assert f"{client_root}/test.py" in result.reason

    def test_handle_omits_the_example_rather_than_guessing_a_root(self, handler, monkeypatch):
        """An omitted example beats a wrong one, and a block reason must not raise."""
        from claude_code_hooks_daemon.core import project_context as pc

        monkeypatch.setattr(pc.ProjectContext, "_initialized", False, raising=False)
        monkeypatch.setattr(pc.ProjectContext, "_instance", None, raising=False)

        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "test"},
        }
        result = handler.handle(hook_input)
        assert "Example:" not in result.reason
        assert "absolute" in result.reason.lower()

    # handle() Tests - Read Tool
    def test_handle_read_returns_deny_decision(self, handler):
        """handle() should return deny for Read tool with relative path."""
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": "README.md"},
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    # handle() Tests - Edit Tool
    def test_handle_edit_returns_deny_decision(self, handler):
        """handle() should return deny for Edit tool with relative path."""
        hook_input = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "config.py",
                "old_string": "old",
                "new_string": "new",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"

    def test_handle_context_is_empty(self, handler):
        """handle() context should be empty (not used)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "test"},
        }
        result = handler.handle(hook_input)
        assert result.context == []

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None (not used)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {"file_path": "test.py", "content": "test"},
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    # Integration Tests
    def test_allows_absolute_paths(self, handler):
        """Should allow absolute paths (not match)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/src/components/Header.tsx",
                "content": "export function Header() { return <div>Header</div>; }",
            },
        }
        assert handler.matches(hook_input) is False

    def test_blocks_relative_paths(self, handler):
        """Should block relative paths (match and deny)."""
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "src/components/Header.tsx",
                "content": "export function Header() { return <div>Header</div>; }",
            },
        }
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == "deny"


class TestAbsolutePathGetRules:
    """get_rules() declares the single Rule backing this handler (Plan 00116)."""

    @pytest.fixture
    def handler(self):
        return AbsolutePathHandler()

    def test_returns_one_rule(self, handler):
        rules = handler.get_rules()
        assert len(rules) == 1
        assert isinstance(rules[0], Rule)

    def test_rule_id_matches_constant(self, handler):
        assert handler.get_rules()[0].rule_id == RuleID.ABSOLUTE_PATH_REQUIRED

    def test_rule_has_non_empty_verbose(self, handler):
        assert handler.get_rules()[0].verbose


class TestAbsolutePathDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder (Decision G)."""

    @pytest.fixture
    def handler(self):
        return AbsolutePathHandler()

    def _hook_input(self, file_path: str, transcript_path):
        return {
            "tool_name": "Write",
            "tool_input": {"file_path": file_path, "content": "x"},
            "transcript_path": transcript_path,
        }

    def test_first_fire_for_agent_is_verbose(self, handler):
        hook_input = self._hook_input("test.py", "/tmp/agent-a/transcript.jsonl")
        result = handler.handle(hook_input)

        assert result.decision == "deny"
        assert "REQUIRED ACTION" in result.reason
        assert "Eliminates ambiguity" in result.reason

    def test_second_fire_for_same_agent_is_terse(self, handler):
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input("test.py", transcript_path))
        result = handler.handle(self._hook_input("other.py", transcript_path))

        assert result.decision == "deny"
        assert "REQUIRED ACTION" not in result.reason
        assert "Eliminates ambiguity" not in result.reason
        assert "other.py" in result.reason

    def test_terse_message_leads_with_rule_id(self, handler):
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        handler.handle(self._hook_input("test.py", transcript_path))
        result = handler.handle(self._hook_input("other.py", transcript_path))

        assert result.reason.startswith(f"BLOCKED [{RuleID.ABSOLUTE_PATH_REQUIRED}]")

    def test_different_agent_is_independently_verbose(self, handler):
        handler.handle(self._hook_input("test.py", "/tmp/agent-a/transcript.jsonl"))
        result = handler.handle(self._hook_input("test.py", "/tmp/agent-b/transcript.jsonl"))

        assert "REQUIRED ACTION" in result.reason

    def test_missing_transcript_path_is_always_verbose(self, handler):
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "test.py", "content": "x"}}
        handler.handle(hook_input)
        result = handler.handle(hook_input)

        assert "REQUIRED ACTION" in result.reason
