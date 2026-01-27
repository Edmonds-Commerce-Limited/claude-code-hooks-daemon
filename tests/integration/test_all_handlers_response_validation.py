"""Integration tests validating ALL built-in handlers return valid responses.

This test suite uses pytest parametrization (PHP-style data providers) to test
every built-in handler with multiple scenarios, asserting:
1. Handler correctly matches/doesn't match input
2. Handler returns valid HookResult
3. HookResult converts to valid JSON for the event type
4. Response passes schema validation

Test case format: (hook_input_dict, expected_decision, description)
"""

import pytest

from claude_code_hooks_daemon.core.hook_result import Decision

# =============================================================================
# PreToolUse Handlers (17 handlers)
# =============================================================================


class TestDestructiveGitHandler:
    """Test DestructiveGitHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
            DestructiveGitHandler,
        )

        return DestructiveGitHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Blocked commands
            (
                {"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}},
                Decision.DENY,
                "Block git reset --hard",
            ),
            (
                {"tool_name": "Bash", "tool_input": {"command": "git clean -f -d"}},
                Decision.DENY,
                "Block git clean -f",
            ),
            (
                {"tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}},
                Decision.DENY,
                "Block force push",
            ),
            (
                {"tool_name": "Bash", "tool_input": {"command": "git checkout ."}},
                Decision.DENY,
                "Block git checkout .",
            ),
            # Allowed commands
            (
                {"tool_name": "Bash", "tool_input": {"command": "git status"}},
                Decision.ALLOW,
                "Allow git status",
            ),
            (
                {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'test'"}},
                Decision.ALLOW,
                "Allow git commit",
            ),
            (
                {"tool_name": "Read", "tool_input": {"file_path": "/workspace/test.py"}},
                Decision.ALLOW,
                "Allow non-Bash tools",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid PreToolUse response."""
        # Check if handler matches
        if handler.matches(hook_input):
            result = handler.handle(hook_input)
            assert result.decision == expected_decision, f"Failed: {description}"

            # Validate response format
            response = result.to_json("PreToolUse")
            response_validator.assert_valid("PreToolUse", response)
        else:
            # Handler doesn't match - that's also valid behavior
            assert expected_decision == Decision.ALLOW, f"Handler should match: {description}"


class TestSedBlockerHandler:
    """Test SedBlockerHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker import (
            SedBlockerHandler,
        )

        return SedBlockerHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Blocked sed commands
            (
                {"tool_name": "Bash", "tool_input": {"command": "sed -i 's/foo/bar/g' file.txt"}},
                Decision.DENY,
                "Block sed inline edit",
            ),
            (
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": "sed 's/old/new/' < input.txt > output.txt"},
                },
                Decision.DENY,
                "Block sed stream edit",
            ),
            # Allowed commands
            (
                {"tool_name": "Bash", "tool_input": {"command": "grep 'pattern' file.txt"}},
                Decision.ALLOW,
                "Allow grep",
            ),
            (
                {"tool_name": "Edit", "tool_input": {"file_path": "/workspace/test.py"}},
                Decision.ALLOW,
                "Allow Edit tool",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid PreToolUse response."""
        if handler.matches(hook_input):
            result = handler.handle(hook_input)
            assert result.decision == expected_decision, f"Failed: {description}"
            response = result.to_json("PreToolUse")
            response_validator.assert_valid("PreToolUse", response)
        else:
            assert expected_decision == Decision.ALLOW


class TestAbsolutePathHandler:
    """Test AbsolutePathHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.pre_tool_use.absolute_path import (
            AbsolutePathHandler,
        )

        return AbsolutePathHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Blocked relative paths
            (
                {"tool_name": "Read", "tool_input": {"file_path": "relative/path.py"}},
                Decision.DENY,
                "Block relative path in Read",
            ),
            (
                {"tool_name": "Write", "tool_input": {"file_path": "./config.yaml"}},
                Decision.DENY,
                "Block ./ relative path",
            ),
            (
                {"tool_name": "Edit", "tool_input": {"file_path": "../parent/file.py"}},
                Decision.DENY,
                "Block ../ relative path",
            ),
            # Allowed absolute paths
            (
                {"tool_name": "Read", "tool_input": {"file_path": "/workspace/test.py"}},
                Decision.ALLOW,
                "Allow absolute path",
            ),
            (
                {"tool_name": "Bash", "tool_input": {"command": "cat relative.txt"}},
                Decision.ALLOW,
                "Allow Bash with relative paths",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid PreToolUse response."""
        if handler.matches(hook_input):
            result = handler.handle(hook_input)
            assert result.decision == expected_decision, f"Failed: {description}"
            response = result.to_json("PreToolUse")
            response_validator.assert_valid("PreToolUse", response)
        else:
            assert expected_decision == Decision.ALLOW


class TestWebSearchYearHandler:
    """Test WebSearchYearHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.pre_tool_use.web_search_year import (
            WebSearchYearHandler,
        )

        return WebSearchYearHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Modified queries (returns ALLOW with context)
            (
                {
                    "tool_name": "WebSearch",
                    "tool_input": {"query": "React hooks documentation 2023"},
                },
                Decision.ALLOW,
                "Update year in query",
            ),
            (
                {"tool_name": "WebSearch", "tool_input": {"query": "Python tutorial 2024"}},
                Decision.ALLOW,
                "Update year to 2026",
            ),
            # Unmodified queries
            (
                {"tool_name": "WebSearch", "tool_input": {"query": "React hooks documentation"}},
                Decision.ALLOW,
                "Allow query without year",
            ),
            (
                {"tool_name": "Read", "tool_input": {"file_path": "/workspace/test.py"}},
                Decision.ALLOW,
                "Allow non-WebSearch tools",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid PreToolUse response."""
        if handler.matches(hook_input):
            result = handler.handle(hook_input)
            assert result.decision == expected_decision, f"Failed: {description}"
            response = result.to_json("PreToolUse")
            response_validator.assert_valid("PreToolUse", response)
        else:
            assert expected_decision == Decision.ALLOW


class TestBritishEnglishHandler:
    """Test BritishEnglishHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.pre_tool_use.british_english import (
            BritishEnglishHandler,
        )

        return BritishEnglishHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # American spellings (warning only)
            (
                {
                    "tool_name": "Write",
                    "tool_input": {"content": "color = 'red'\nfavorite = 'blue'"},
                },
                Decision.ALLOW,
                "Warn about American spellings",
            ),
            # British spellings
            (
                {
                    "tool_name": "Write",
                    "tool_input": {"content": "colour = 'red'\nfavourite = 'blue'"},
                },
                Decision.ALLOW,
                "Allow British spellings",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid PreToolUse response."""
        if handler.matches(hook_input):
            result = handler.handle(hook_input)
            assert result.decision == expected_decision, f"Failed: {description}"
            response = result.to_json("PreToolUse")
            response_validator.assert_valid("PreToolUse", response)


class TestEslintDisableHandler:
    """Test EslintDisableHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.pre_tool_use.eslint_disable import (
            EslintDisableHandler,
        )

        return EslintDisableHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Blocked ESLint suppressions
            (
                {
                    "tool_name": "Write",
                    "tool_input": {"content": "// eslint-disable-next-line\nconst x = 1;"},
                },
                Decision.DENY,
                "Block eslint-disable-next-line",
            ),
            (
                {
                    "tool_name": "Edit",
                    "tool_input": {"new_string": "/* eslint-disable */\ncode();"},
                },
                Decision.DENY,
                "Block eslint-disable comment",
            ),
            # Allowed code
            (
                {"tool_name": "Write", "tool_input": {"content": "const x = 1;\nconsole.log(x);"}},
                Decision.ALLOW,
                "Allow normal JavaScript",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid PreToolUse response."""
        if handler.matches(hook_input):
            result = handler.handle(hook_input)
            assert result.decision == expected_decision, f"Failed: {description}"
            response = result.to_json("PreToolUse")
            response_validator.assert_valid("PreToolUse", response)
        else:
            assert expected_decision == Decision.ALLOW


class TestTddEnforcementHandler:
    """Test TddEnforcementHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.pre_tool_use.tdd_enforcement import (
            TddEnforcementHandler,
        )

        return TddEnforcementHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Blocked production code before tests
            (
                {
                    "tool_name": "Write",
                    "tool_input": {
                        "file_path": "/workspace/src/features/new_feature.py",
                        "content": "def new_function(): pass",
                    },
                },
                Decision.DENY,
                "Block new feature without test",
            ),
            # Allowed test files
            (
                {
                    "tool_name": "Write",
                    "tool_input": {
                        "file_path": "/workspace/tests/test_new_feature.py",
                        "content": "def test_new_function(): pass",
                    },
                },
                Decision.ALLOW,
                "Allow test file creation",
            ),
            # Allowed edits to existing files
            (
                {
                    "tool_name": "Edit",
                    "tool_input": {
                        "file_path": "/workspace/src/existing.py",
                        "old_string": "old",
                        "new_string": "new",
                    },
                },
                Decision.ALLOW,
                "Allow edits to existing files",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid PreToolUse response."""
        if handler.matches(hook_input):
            result = handler.handle(hook_input)
            assert result.decision == expected_decision, f"Failed: {description}"
            response = result.to_json("PreToolUse")
            response_validator.assert_valid("PreToolUse", response)
        else:
            assert expected_decision == Decision.ALLOW


class TestGitStashHandler:
    """Test GitStashHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.pre_tool_use.git_stash import GitStashHandler

        return GitStashHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Warning about git stash
            (
                {"tool_name": "Bash", "tool_input": {"command": "git stash"}},
                Decision.ALLOW,
                "Warn about git stash",
            ),
            (
                {"tool_name": "Bash", "tool_input": {"command": "git stash push -m 'WIP'"}},
                Decision.ALLOW,
                "Warn about git stash push",
            ),
            # Allow non-stash commands
            (
                {"tool_name": "Bash", "tool_input": {"command": "git status"}},
                Decision.ALLOW,
                "Allow git status",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid PreToolUse response."""
        if handler.matches(hook_input):
            result = handler.handle(hook_input)
            assert result.decision == expected_decision, f"Failed: {description}"
            response = result.to_json("PreToolUse")
            response_validator.assert_valid("PreToolUse", response)


class TestWorktreeFileCopyHandler:
    """Test WorktreeFileCopyHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.pre_tool_use.worktree_file_copy import (
            WorktreeFileCopyHandler,
        )

        return WorktreeFileCopyHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Allowed operations (non-worktree or non-copy)
            (
                {"tool_name": "Bash", "tool_input": {"command": "cp file1.txt file2.txt"}},
                Decision.ALLOW,
                "Allow normal file copy",
            ),
            (
                {"tool_name": "Read", "tool_input": {"file_path": "/workspace/test.py"}},
                Decision.ALLOW,
                "Allow Read tool",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid PreToolUse response."""
        if handler.matches(hook_input):
            result = handler.handle(hook_input)
            assert result.decision == expected_decision, f"Failed: {description}"
            response = result.to_json("PreToolUse")
            response_validator.assert_valid("PreToolUse", response)


# =============================================================================
# PostToolUse Handlers (3 handlers)
# =============================================================================


class TestBashErrorDetectorHandler:
    """Test BashErrorDetectorHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.post_tool_use.bash_error_detector import (
            BashErrorDetectorHandler,
        )

        return BashErrorDetectorHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Success cases (allow)
            (
                {
                    "tool_name": "Bash",
                    "tool_result": {"exit_code": 0, "stdout": "Success", "stderr": ""},
                },
                Decision.ALLOW,
                "Allow successful command",
            ),
            # Error cases (context only, still allow)
            (
                {
                    "tool_name": "Bash",
                    "tool_result": {
                        "exit_code": 1,
                        "stdout": "",
                        "stderr": "Error: file not found",
                    },
                },
                Decision.ALLOW,
                "Allow with error context",
            ),
            # Non-Bash tools
            (
                {"tool_name": "Read", "tool_result": {"content": "file contents"}},
                Decision.ALLOW,
                "Allow non-Bash tools",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid PostToolUse response."""
        if handler.matches(hook_input):
            result = handler.handle(hook_input)
            assert result.decision == expected_decision, f"Failed: {description}"
            response = result.to_json("PostToolUse")
            response_validator.assert_valid("PostToolUse", response)


# =============================================================================
# SessionStart Handlers (2 handlers)
# =============================================================================


class TestYoloContainerDetectionHandler:
    """Test YoloContainerDetectionHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.session_start.yolo_container_detection import (
            YoloContainerDetectionHandler,
        )

        return YoloContainerDetectionHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Always returns context (YOLO status)
            (
                {"session_id": "test-session", "timestamp": "2026-01-27T00:00:00Z"},
                Decision.ALLOW,
                "Detect YOLO container status",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid SessionStart response."""
        result = handler.handle(hook_input)
        assert result.decision == expected_decision, f"Failed: {description}"
        response = result.to_json("SessionStart")
        response_validator.assert_valid("SessionStart", response)


# =============================================================================
# PreCompact Handlers (2 handlers)
# =============================================================================


class TestTranscriptArchiverHandler:
    """Test TranscriptArchiverHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.pre_compact.transcript_archiver import (
            TranscriptArchiverHandler,
        )

        return TranscriptArchiverHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Always archives and returns context
            (
                {"session_id": "test-session", "transcript_path": "/tmp/transcript.jsonl"},
                Decision.ALLOW,
                "Archive transcript before compaction",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid PreCompact response."""
        result = handler.handle(hook_input)
        assert result.decision == expected_decision, f"Failed: {description}"
        response = result.to_json("PreCompact")
        response_validator.assert_valid("PreCompact", response)


# =============================================================================
# UserPromptSubmit Handlers (2 handlers)
# =============================================================================


class TestGitContextInjectorHandler:
    """Test GitContextInjectorHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.user_prompt_submit.git_context_injector import (
            GitContextInjectorHandler,
        )

        return GitContextInjectorHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Injects git context
            (
                {"user_prompt": "Fix the bug", "session_id": "test"},
                Decision.ALLOW,
                "Inject git context",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid UserPromptSubmit response."""
        result = handler.handle(hook_input)
        assert result.decision == expected_decision, f"Failed: {description}"
        response = result.to_json("UserPromptSubmit")
        response_validator.assert_valid("UserPromptSubmit", response)


# =============================================================================
# SubagentStop Handlers (3 handlers)
# =============================================================================


class TestSubagentCompletionLoggerHandler:
    """Test SubagentCompletionLoggerHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.subagent_stop.subagent_completion_logger import (
            SubagentCompletionLoggerHandler,
        )

        return SubagentCompletionLoggerHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Logs subagent completion
            (
                {"subagent_type": "Explore", "status": "completed", "result": "Found 5 files"},
                Decision.ALLOW,
                "Log subagent completion",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid SubagentStop response."""
        result = handler.handle(hook_input)
        assert result.decision == expected_decision, f"Failed: {description}"
        response = result.to_json("SubagentStop")
        response_validator.assert_valid("SubagentStop", response)


# =============================================================================
# Notification Handlers (1 handler)
# =============================================================================


class TestNotificationLoggerHandler:
    """Test NotificationLoggerHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.notification.notification_logger import (
            NotificationLoggerHandler,
        )

        return NotificationLoggerHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Logs notifications
            (
                {"notification_type": "info", "message": "Test notification"},
                Decision.ALLOW,
                "Log notification",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid Notification response."""
        result = handler.handle(hook_input)
        assert result.decision == expected_decision, f"Failed: {description}"
        response = result.to_json("Notification")
        response_validator.assert_valid("Notification", response)


# =============================================================================
# SessionEnd Handlers (1 handler)
# =============================================================================


class TestCleanupHandler:
    """Test CleanupHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.session_end.cleanup_handler import CleanupHandler

        return CleanupHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Performs cleanup
            (
                {"session_id": "test-session", "reason": "user_exit"},
                Decision.ALLOW,
                "Cleanup on session end",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid SessionEnd response."""
        result = handler.handle(hook_input)
        assert result.decision == expected_decision, f"Failed: {description}"
        response = result.to_json("SessionEnd")
        response_validator.assert_valid("SessionEnd", response)


# =============================================================================
# Stop Handlers (1 handler)
# =============================================================================


class TestTaskCompletionCheckerHandler:
    """Test TaskCompletionCheckerHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.stop.task_completion_checker import (
            TaskCompletionCheckerHandler,
        )

        return TaskCompletionCheckerHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Check task completion
            (
                {"reason": "user_stop", "tasks_pending": 0},
                Decision.ALLOW,
                "Allow stop when no tasks pending",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid Stop response."""
        result = handler.handle(hook_input)
        assert result.decision == expected_decision, f"Failed: {description}"
        response = result.to_json("Stop")
        response_validator.assert_valid("Stop", response)


# =============================================================================
# PermissionRequest Handlers (1 handler)
# =============================================================================


class TestAutoApproveReadsHandler:
    """Test AutoApproveReadsHandler response validation."""

    @pytest.fixture
    def handler(self):
        from claude_code_hooks_daemon.handlers.permission_request.auto_approve_reads import (
            AutoApproveReadsHandler,
        )

        return AutoApproveReadsHandler()

    @pytest.mark.parametrize(
        "hook_input,expected_decision,description",
        [
            # Auto-approve read operations
            (
                {"permission_type": "file_read", "resource": "/workspace/file.txt"},
                Decision.ALLOW,
                "Auto-approve file read",
            ),
            # Deny write operations
            (
                {"permission_type": "file_write", "resource": "/workspace/file.txt"},
                Decision.DENY,
                "Block file write",
            ),
        ],
    )
    def test_response_validity(
        self, handler, hook_input, expected_decision, description, response_validator
    ):
        """Test handler returns valid PermissionRequest response."""
        if handler.matches(hook_input):
            result = handler.handle(hook_input)
            assert result.decision == expected_decision, f"Failed: {description}"
            response = result.to_json("PermissionRequest")
            response_validator.assert_valid("PermissionRequest", response)
        else:
            assert expected_decision == Decision.ALLOW
