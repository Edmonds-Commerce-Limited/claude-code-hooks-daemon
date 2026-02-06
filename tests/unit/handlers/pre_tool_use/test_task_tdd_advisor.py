"""Comprehensive tests for TaskTddAdvisorHandler."""

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.task_tdd_advisor import (
    TaskTddAdvisorHandler,
)


class TestTaskTddAdvisorHandler:
    """Test suite for TaskTddAdvisorHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler instance."""
        return TaskTddAdvisorHandler()

    # Initialization Tests
    def test_init_sets_correct_name(self, handler):
        """Handler name should be 'task-tdd-advisor'."""
        assert handler.name == "task-tdd-advisor"

    def test_init_sets_correct_priority(self, handler):
        """Handler priority should be in workflow range (36-55)."""
        assert 36 <= handler.priority <= 55

    def test_init_sets_non_terminal_flag(self, handler):
        """Handler should be non-terminal (advisory)."""
        assert handler.terminal is False

    # matches() - Positive Cases: Task tool with implementation keywords (MATCH)
    def test_matches_task_with_implement_keyword(self, handler):
        """Should match Task with 'implement' in prompt."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "implement a new handler for blocking sed commands",
                "description": "Implement sed blocker",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_task_with_create_handler_keyword(self, handler):
        """Should match Task with 'create handler' in prompt."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "create a handler to enforce TDD workflow",
                "description": "Create TDD handler",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_task_with_write_code_keyword(self, handler):
        """Should match Task with 'write code' in prompt."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "write code to validate lock files",
                "description": "Write lock file validator",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_task_with_add_feature_keyword(self, handler):
        """Should match Task with 'add feature' in prompt."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "add feature to block npm global installs",
                "description": "Add npm feature",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_task_with_build_keyword(self, handler):
        """Should match Task with 'build' in prompt."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "build a new validation system",
                "description": "Build validator",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_task_with_develop_keyword(self, handler):
        """Should match Task with 'develop' in prompt."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "python-developer",
                "prompt": "develop a plugin system",
                "description": "Develop plugins",
            },
        }
        assert handler.matches(hook_input) is True

    def test_matches_task_case_insensitive(self, handler):
        """Should match keywords case-insensitively."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "IMPLEMENT new feature",
                "description": "Test",
            },
        }
        assert handler.matches(hook_input) is True

    # matches() - Negative Cases: Task tool without implementation keywords (NO MATCH)
    def test_matches_task_research_only_returns_false(self, handler):
        """Should NOT match Task for research/exploration."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "Explore",
                "prompt": "search for error handling patterns in the codebase",
                "description": "Research errors",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_task_debugging_returns_false(self, handler):
        """Should NOT match Task for debugging."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "debug the failing test in test_sed_blocker.py",
                "description": "Debug test",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_task_fix_keyword_returns_false(self, handler):
        """Should NOT match Task with 'fix' (bug fixes have different workflow)."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "fix the sed blocker false positive",
                "description": "Fix bug",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_task_investigate_returns_false(self, handler):
        """Should NOT match Task for investigation."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "Explore",
                "prompt": "investigate how handlers are loaded",
                "description": "Investigate",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_task_analyze_returns_false(self, handler):
        """Should NOT match Task for analysis."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "analyze the test coverage report",
                "description": "Analyze coverage",
            },
        }
        assert handler.matches(hook_input) is False

    # matches() - Edge Cases
    def test_matches_non_task_tool_returns_false(self, handler):
        """Should NOT match non-Task tools."""
        hook_input = {"tool_name": "Write", "tool_input": {"file_path": "/workspace/test.py"}}
        assert handler.matches(hook_input) is False

    def test_matches_task_without_prompt_returns_false(self, handler):
        """Should NOT match Task when prompt is missing."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "general-purpose", "description": "Test"},
        }
        assert handler.matches(hook_input) is False

    def test_matches_task_with_empty_prompt_returns_false(self, handler):
        """Should NOT match Task with empty prompt."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "",
                "description": "Test",
            },
        }
        assert handler.matches(hook_input) is False

    def test_matches_task_with_none_prompt_returns_false(self, handler):
        """Should NOT match Task when prompt is None."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": None,
                "description": "Test",
            },
        }
        assert handler.matches(hook_input) is False

    # handle() Tests - Advisory message content
    def test_handle_returns_allow_decision(self, handler):
        """handle() should return allow decision (advisory)."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "implement new handler",
                "description": "Test",
            },
        }
        result = handler.handle(hook_input)
        assert result.decision == "allow"

    def test_handle_reason_mentions_tdd(self, handler):
        """handle() reason should mention TDD."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "implement new handler",
                "description": "Test",
            },
        }
        result = handler.handle(hook_input)
        assert "TDD" in result.reason

    def test_handle_reason_mentions_tests_first(self, handler):
        """handle() reason should mention writing tests first."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "create handler",
                "description": "Test",
            },
        }
        result = handler.handle(hook_input)
        assert "test" in result.reason.lower()

    def test_handle_reason_mentions_red_green_refactor(self, handler):
        """handle() reason should mention red-green-refactor cycle."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "implement feature",
                "description": "Test",
            },
        }
        result = handler.handle(hook_input)
        assert "red" in result.reason.lower() or "green" in result.reason.lower()

    def test_handle_context_contains_tdd_reminder(self, handler):
        """handle() should inject TDD reminder in context."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "implement handler",
                "description": "Test",
            },
        }
        result = handler.handle(hook_input)
        assert len(result.context) > 0
        assert any("TDD" in str(ctx) or "test" in str(ctx).lower() for ctx in result.context)

    def test_handle_guidance_is_none(self, handler):
        """handle() guidance should be None."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "implement handler",
                "description": "Test",
            },
        }
        result = handler.handle(hook_input)
        assert result.guidance is None

    # Integration Tests
    def test_full_workflow_advises_on_implementation_task(self, handler):
        """Complete workflow: Advise on TDD for implementation task."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "python-developer",
                "prompt": "implement a handler to block direct edits to lock files",
                "description": "Implement lock file blocker",
            },
        }

        # Should match
        assert handler.matches(hook_input) is True

        # Should advise (allow)
        result = handler.handle(hook_input)
        assert result.decision == "allow"
        assert "TDD" in result.reason
        assert len(result.context) > 0

    def test_full_workflow_allows_research_task_without_advice(self, handler):
        """Complete workflow: Allow research task without TDD advice."""
        hook_input = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "Explore",
                "prompt": "search for all handler files in the codebase",
                "description": "Find handlers",
            },
        }

        # Should not match
        assert handler.matches(hook_input) is False

    def test_comprehensive_implementation_keywords_detection(self, handler):
        """Should detect all implementation-related keywords."""
        implementation_keywords = [
            "implement",
            "create handler",
            "write code",
            "add feature",
            "build",
            "develop",
            "code up",
            "write handler",
        ]

        for keyword in implementation_keywords:
            hook_input = {
                "tool_name": "Task",
                "tool_input": {
                    "subagent_type": "general-purpose",
                    "prompt": f"Please {keyword} for testing",
                    "description": "Test",
                },
            }
            assert handler.matches(hook_input) is True, f"Should match keyword: {keyword}"

    def test_comprehensive_non_implementation_keywords_ignored(self, handler):
        """Should NOT match non-implementation keywords."""
        non_implementation_keywords = [
            "search",
            "find",
            "debug",
            "fix",
            "investigate",
            "analyze",
            "explore",
            "read",
            "review",
        ]

        for keyword in non_implementation_keywords:
            hook_input = {
                "tool_name": "Task",
                "tool_input": {
                    "subagent_type": "general-purpose",
                    "prompt": f"Please {keyword} the codebase",
                    "description": "Test",
                },
            }
            assert handler.matches(hook_input) is False, f"Should NOT match keyword: {keyword}"
