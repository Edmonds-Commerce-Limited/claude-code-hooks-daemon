"""Integration tests for handler config loading and E2E blocking behavior.

CRITICAL: These tests verify that the handler system actually works as advertised:
1. enabled=false in config prevents handler loading
2. Terminal handlers actually block operations
3. DENY decisions propagate through the full stack

These tests address the bug where markdown_organization was disabled in config
but tests didn't catch it because unit tests bypass config loading.

Test Philosophy:
- Unit tests verify handler logic in isolation
- Integration tests verify config loading and registration
- E2E tests verify blocking through the full daemon stack
"""

from pathlib import Path
from typing import Any

import yaml

from claude_code_hooks_daemon.config.loader import ConfigLoader
from claude_code_hooks_daemon.constants import Priority
from claude_code_hooks_daemon.core.event import EventType
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.core.router import EventRouter
from claude_code_hooks_daemon.handlers.registry import HandlerRegistry


class TestHandlerConfigLoading:
    """Test that config correctly controls handler registration."""

    def test_enabled_true_loads_handler(self, tmp_path: Path) -> None:
        """Test that enabled=true (or default) loads handler."""
        # Create config with destructive_git enabled
        config_file = tmp_path / "config.yaml"
        config_data = {
            "version": "1.0",
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}},
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Load config
        config = ConfigLoader.load(config_file)

        # Create router and registry
        router = EventRouter()
        registry = HandlerRegistry()
        registry.discover()

        # Register handlers with config
        count = registry.register_all(router, config=config.get("handlers"))

        # Verify handler was registered (actual name is prevent-destructive-git)
        pre_tool_use_chain = router.get_chain(EventType.PRE_TOOL_USE)
        handler = pre_tool_use_chain.get("prevent-destructive-git")

        assert handler is not None, "Handler should be registered when enabled=true"
        assert handler.name == "prevent-destructive-git"
        assert count > 0

    def test_enabled_false_skips_handler(self, tmp_path: Path) -> None:
        """CRITICAL: Test that enabled=false prevents handler loading.

        This is the test that would have caught the markdown_organization bug.
        """
        # Create config with destructive_git disabled
        config_file = tmp_path / "config.yaml"
        config_data = {
            "version": "1.0",
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": False}}},
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Load config
        config = ConfigLoader.load(config_file)

        # Create router and registry
        router = EventRouter()
        registry = HandlerRegistry()
        registry.discover()

        # Register handlers with config
        registry.register_all(router, config=config.get("handlers"))

        # Verify handler was NOT registered
        pre_tool_use_chain = router.get_chain(EventType.PRE_TOOL_USE)
        handler = pre_tool_use_chain.get("prevent-destructive-git")

        assert handler is None, "Handler should NOT be registered when enabled=false"

    def test_default_enabled_state_loads_handler(self, tmp_path: Path) -> None:
        """Test that handlers load by default when no config specified."""
        # Create minimal config (no handler section)
        config_file = tmp_path / "config.yaml"
        config_data = {"version": "1.0"}
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Load config
        config = ConfigLoader.load(config_file)

        # Create router and registry
        router = EventRouter()
        registry = HandlerRegistry()
        registry.discover()

        # Register handlers with minimal config
        count = registry.register_all(router, config=config.get("handlers"))

        # Verify at least some handlers were registered (default enabled)
        assert count > 0, "Handlers should be registered by default"

        # Check that destructive_git loaded (it defaults to enabled)
        pre_tool_use_chain = router.get_chain(EventType.PRE_TOOL_USE)
        handler = pre_tool_use_chain.get("prevent-destructive-git")
        assert handler is not None, "Handlers should load by default"

    def test_multiple_handlers_selective_enabling(self, tmp_path: Path) -> None:
        """Test that we can enable/disable handlers independently."""
        # Create config enabling one handler, disabling another
        config_file = tmp_path / "config.yaml"
        config_data = {
            "version": "1.0",
            "handlers": {
                "pre_tool_use": {
                    "destructive_git": {"enabled": True},
                    "sed_blocker": {"enabled": False},
                }
            },
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Load config
        config = ConfigLoader.load(config_file)

        # Create router and registry
        router = EventRouter()
        registry = HandlerRegistry()
        registry.discover()

        # Register handlers with config
        registry.register_all(router, config=config.get("handlers"))

        # Verify selective loading
        pre_tool_use_chain = router.get_chain(EventType.PRE_TOOL_USE)

        destructive_git = pre_tool_use_chain.get("prevent-destructive-git")
        sed_blocker = pre_tool_use_chain.get("block-sed-command")

        assert destructive_git is not None, "Enabled handler should be loaded"
        assert sed_blocker is None, "Disabled handler should NOT be loaded"


class TestTerminalHandlerBlocking:
    """Test that terminal handlers actually block operations E2E."""

    def test_terminal_handler_stops_chain_execution(self) -> None:
        """Test that terminal=True actually stops handler chain."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
            DestructiveGitHandler,
        )
        from claude_code_hooks_daemon.handlers.pre_tool_use.sed_blocker import (
            SedBlockerHandler,
        )

        # Create router and add handlers
        router = EventRouter()

        # Add destructive_git (terminal, priority 10)
        destructive_git = DestructiveGitHandler()
        assert destructive_git.terminal, "DestructiveGitHandler should be terminal"
        router.register(EventType.PRE_TOOL_USE, destructive_git)

        # Add sed_blocker (terminal, priority 15) - lower priority, runs after
        sed_blocker = SedBlockerHandler()
        assert sed_blocker.terminal, "SedBlockerHandler should be terminal"
        router.register(EventType.PRE_TOOL_USE, sed_blocker)

        # Test: destructive git command should be blocked by first handler
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Verify terminal behavior
        assert result.result.decision == Decision.DENY
        assert result.terminated_by == "prevent-destructive-git"
        assert "prevent-destructive-git" in result.handlers_executed
        assert (
            "block-sed-command" not in result.handlers_executed
        ), "Second handler should NOT execute after terminal handler"

    def test_deny_decision_blocks_operation(self) -> None:
        """CRITICAL: Test that DENY decision actually blocks operations.

        This verifies the contract: terminal=True + DENY = operation blocked.
        """
        from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
            DestructiveGitHandler,
        )

        # Create router and add handler
        router = EventRouter()
        handler = DestructiveGitHandler()
        router.register(EventType.PRE_TOOL_USE, handler)

        # Test: destructive command
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Verify blocking
        assert result.result.decision == Decision.DENY
        assert result.terminated_by == "prevent-destructive-git"
        assert result.result.reason is not None
        assert len(result.result.reason) > 0, "Should provide reason for blocking"

    def test_allow_decision_continues_chain(self) -> None:
        """Test that ALLOW decisions allow non-matching handlers to execute."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.destructive_git import (
            DestructiveGitHandler,
        )

        # Create router and add handler
        router = EventRouter()
        handler = DestructiveGitHandler()
        router.register(EventType.PRE_TOOL_USE, handler)

        # Test: safe command
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git status"}}

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Verify the handler didn't match (safe command)
        assert "prevent-destructive-git" not in result.handlers_matched
        # Result should be ALLOW (default fallback)
        assert result.result.decision == Decision.ALLOW

    def test_non_terminal_handler_accumulates_context(self) -> None:
        """Test that non-terminal handlers accumulate context and continue."""
        from claude_code_hooks_daemon.handlers.pre_tool_use.british_english import (
            BritishEnglishHandler,
        )

        # Create router and add non-terminal handler
        router = EventRouter()

        # British English (non-terminal, advisory)
        british_english = BritishEnglishHandler()
        assert not british_english.terminal, "BritishEnglishHandler should be non-terminal"
        router.register(EventType.PRE_TOOL_USE, british_english)

        # Test: Write markdown file with American spelling (BritishEnglish checks .md files)
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/workspace/docs/test.md",
                "content": "The color of the organization is blue.",
            },
        }

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Verify non-terminal behavior
        assert result.result.decision == Decision.ALLOW
        assert result.terminated_by is None, "No terminal handler should stop chain"
        assert "enforce-british-english" in result.handlers_executed
        # Reason should contain the warning (handler puts message in reason, not context)
        assert result.result.reason is not None
        assert len(result.result.reason) > 0


class TestEndToEndBlockingScenarios:
    """E2E tests simulating real Claude Code scenarios."""

    def test_destructive_git_blocks_force_push_e2e(self, tmp_path: Path) -> None:
        """E2E: Verify force push is blocked through full stack with config."""
        # Create production-like config
        config_file = tmp_path / "config.yaml"
        config_data = {
            "version": "1.0",
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 10}}},
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Load config and setup system
        config = ConfigLoader.load(config_file)
        router = EventRouter()
        registry = HandlerRegistry()
        registry.discover()
        registry.register_all(router, config=config.get("handlers"))

        # Simulate Claude Code attempting force push
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "git push --force origin main",
                "description": "Push changes to remote",
            },
        }

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Verify blocking
        assert result.result.decision == Decision.DENY
        # Reason should mention destructive git or force
        assert (
            "force" in result.result.reason.lower() or "destructive" in result.result.reason.lower()
        )
        assert result.terminated_by == "prevent-destructive-git"

    def test_sed_blocker_prevents_inline_edits_e2e(self, tmp_path: Path) -> None:
        """E2E: Verify sed commands are blocked with proper config."""
        # Create config
        config_file = tmp_path / "config.yaml"
        config_data = {
            "version": "1.0",
            "handlers": {"pre_tool_use": {"sed_blocker": {"enabled": True, "priority": 15}}},
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Setup system
        config = ConfigLoader.load(config_file)
        router = EventRouter()
        registry = HandlerRegistry()
        registry.discover()
        registry.register_all(router, config=config.get("handlers"))

        # Simulate sed command
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {
                "command": "sed -i 's/foo/bar/g' file.txt",
                "description": "Replace text in file",
            },
        }

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Verify blocking
        assert result.result.decision == Decision.DENY
        assert "sed" in result.result.reason.lower()
        assert result.terminated_by == "block-sed-command"

    def test_disabled_handler_does_not_block_e2e(self, tmp_path: Path) -> None:
        """CRITICAL E2E: Verify disabled handler doesn't interfere.

        This simulates the markdown_organization bug scenario.
        """
        # Create config with handler disabled
        config_file = tmp_path / "config.yaml"
        config_data = {
            "version": "1.0",
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": False}}},  # DISABLED
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Setup system
        config = ConfigLoader.load(config_file)
        router = EventRouter()
        registry = HandlerRegistry()
        registry.discover()
        registry.register_all(router, config=config.get("handlers"))

        # Attempt destructive command (would normally be blocked)
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "git reset --hard HEAD"}}

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Verify NOT blocked (handler is disabled)
        assert result.result.decision == Decision.ALLOW
        assert result.terminated_by is None
        assert "prevent-destructive-git" not in result.handlers_executed


class TestConfigPriorityOverride:
    """Test that config can override handler priority."""

    def test_config_overrides_handler_priority(self, tmp_path: Path) -> None:
        """Test that priority in config overrides handler default."""
        # Create config with custom priority
        config_file = tmp_path / "config.yaml"
        config_data = {
            "version": "1.0",
            "handlers": {"pre_tool_use": {"destructive_git": {"enabled": True, "priority": 99}}},
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Setup system
        config = ConfigLoader.load(config_file)
        router = EventRouter()
        registry = HandlerRegistry()
        registry.discover()
        registry.register_all(router, config=config.get("handlers"))

        # Get handler and verify priority
        chain = router.get_chain(EventType.PRE_TOOL_USE)
        handler = chain.get("prevent-destructive-git")

        assert handler is not None
        assert handler.priority == 99, "Config priority should override default"

    def test_priority_affects_execution_order(self) -> None:
        """Test that lower priority executes first."""
        from claude_code_hooks_daemon.core.handler import Handler
        from claude_code_hooks_daemon.core.hook_result import HookResult

        # Create test handlers with different priorities
        class LowPriorityHandler(Handler):
            def __init__(self) -> None:
                super().__init__(name="low", priority=Priority.DESTRUCTIVE_GIT, terminal=False)

            def matches(self, hook_input: dict[str, Any]) -> bool:
                return True

            def handle(self, hook_input: dict[str, Any]) -> HookResult:
                return HookResult(decision=Decision.ALLOW, context=["low executed"])

            def get_acceptance_tests(self) -> list[Any]:
                """Test handler - stub implementation."""
                from claude_code_hooks_daemon.core import AcceptanceTest, TestType

                return [
                    AcceptanceTest(
                        title="low priority handler",
                        command="echo 'test'",
                        description="Low priority test handler",
                        expected_decision=Decision.ALLOW,
                        expected_message_patterns=[r".*"],
                        test_type=TestType.BLOCKING,
                    )
                ]

        class HighPriorityHandler(Handler):
            def __init__(self) -> None:
                super().__init__(name="high", priority=Priority.HELLO_WORLD, terminal=False)

            def matches(self, hook_input: dict[str, Any]) -> bool:
                return True

            def handle(self, hook_input: dict[str, Any]) -> HookResult:
                return HookResult(decision=Decision.ALLOW, context=["high executed"])

            def get_acceptance_tests(self) -> list[Any]:
                """Test handler - stub implementation."""
                from claude_code_hooks_daemon.core import AcceptanceTest, TestType

                return [
                    AcceptanceTest(
                        title="high priority handler",
                        command="echo 'test'",
                        description="High priority test handler",
                        expected_decision=Decision.ALLOW,
                        expected_message_patterns=[r".*"],
                        test_type=TestType.BLOCKING,
                    )
                ]

        # Create router and add handlers out of order
        router = EventRouter()
        router.register(EventType.PRE_TOOL_USE, HighPriorityHandler())
        router.register(EventType.PRE_TOOL_USE, LowPriorityHandler())

        # Execute
        result = router.route(EventType.PRE_TOOL_USE, {"tool_name": "Test"})

        # Verify execution order (lower priority numbers execute first)
        # high has priority 5, low has priority 10
        assert result.handlers_executed == ["high", "low"]


class TestMarkdownOrganizationHandlerIntegration:
    """Integration tests for MarkdownOrganizationHandler config and blocking.

    CRITICAL: These tests address the bug where markdown_organization was
    disabled in config but tests didn't catch it.
    """

    def test_markdown_handler_loads_from_config(
        self, tmp_path: Path, project_context: Path
    ) -> None:
        """Test that markdown_organization handler loads when enabled in config."""
        # Create config with markdown_organization enabled
        config_file = tmp_path / "config.yaml"
        config_data = {
            "version": "1.0",
            "handlers": {
                "pre_tool_use": {"markdown_organization": {"enabled": True, "priority": 35}}
            },
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Load config
        config = ConfigLoader.load(config_file)

        # Create router and registry
        router = EventRouter()
        registry = HandlerRegistry()
        registry.discover()

        # Register handlers with config
        count = registry.register_all(router, config=config.get("handlers"))

        # Verify handler was registered
        pre_tool_use_chain = router.get_chain(EventType.PRE_TOOL_USE)
        handler = pre_tool_use_chain.get("enforce-markdown-organization")

        assert handler is not None, "Handler should be registered when enabled=true"
        assert handler.name == "enforce-markdown-organization"
        assert count > 0

    def test_markdown_handler_disabled_in_config_prevents_loading(
        self, tmp_path: Path, project_context: Path
    ) -> None:
        """CRITICAL: Test that enabled=false prevents markdown handler loading.

        This is the exact bug scenario - handler disabled but tests didn't catch it.
        """
        # Create config with markdown_organization DISABLED
        config_file = tmp_path / "config.yaml"
        config_data = {
            "version": "1.0",
            "handlers": {"pre_tool_use": {"markdown_organization": {"enabled": False}}},
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Load config
        config = ConfigLoader.load(config_file)

        # Create router and registry
        router = EventRouter()
        registry = HandlerRegistry()
        registry.discover()

        # Register handlers with config
        registry.register_all(router, config=config.get("handlers"))

        # Verify handler was NOT registered
        pre_tool_use_chain = router.get_chain(EventType.PRE_TOOL_USE)
        handler = pre_tool_use_chain.get("enforce-markdown-organization")

        assert handler is None, "Handler should NOT be registered when enabled=false"

    def test_markdown_handler_blocks_invalid_location_e2e(
        self, tmp_path: Path, project_context: Path
    ) -> None:
        """E2E: Verify markdown handler blocks writes to invalid locations."""
        # Create config with markdown_organization enabled
        config_file = tmp_path / "config.yaml"
        config_data = {
            "version": "1.0",
            "handlers": {
                "pre_tool_use": {"markdown_organization": {"enabled": True, "priority": 35}}
            },
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Setup system
        config = ConfigLoader.load(config_file)
        router = EventRouter()
        registry = HandlerRegistry()
        registry.discover()
        registry.register_all(router, config=config.get("handlers"))

        # Simulate Write to invalid location (src/invalid.md) - use absolute path
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(project_context / "src" / "invalid.md"),
                "content": "# Test",
            },
        }

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Verify blocking
        assert result.result.decision == Decision.DENY
        assert "MARKDOWN FILE IN WRONG LOCATION" in result.result.reason
        assert result.terminated_by == "enforce-markdown-organization"

    def test_markdown_handler_allows_valid_location_e2e(
        self, tmp_path: Path, project_context: Path
    ) -> None:
        """E2E: Verify markdown handler allows writes to valid locations."""
        # Create config
        config_file = tmp_path / "config.yaml"
        config_data = {
            "version": "1.0",
            "handlers": {
                "pre_tool_use": {"markdown_organization": {"enabled": True, "priority": 35}}
            },
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Setup system
        config = ConfigLoader.load(config_file)
        router = EventRouter()
        registry = HandlerRegistry()
        registry.discover()
        registry.register_all(router, config=config.get("handlers"))

        # Simulate Write to valid location (CLAUDE/test.md) - use absolute path
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(project_context / "CLAUDE" / "test.md"),
                "content": "# Test",
            },
        }

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Verify allowed (handler doesn't match valid locations)
        assert result.result.decision == Decision.ALLOW
        assert "enforce-markdown-organization" not in result.handlers_matched

    def test_planning_mode_redirect_e2e(self, project_context: Path) -> None:
        """E2E: Verify planning mode write interception when feature enabled.

        This tests the new planning mode integration feature.
        """
        # Use project_context which already has CLAUDE/Plan structure
        plan_dir = project_context / "CLAUDE" / "Plan"
        assert plan_dir.exists(), "Plan directory should exist from fixture"

        # Create config with planning mode tracking enabled
        config_file = project_context / ".claude" / "hooks-daemon.yaml"
        config_data = {
            "version": "1.0",
            "handlers": {
                "pre_tool_use": {
                    "markdown_organization": {
                        "enabled": True,
                        "priority": 35,
                        "track_plans_in_project": "CLAUDE/Plan",
                        "plan_workflow_docs": "CLAUDE/PlanWorkflow.md",
                    }
                }
            },
        }
        with config_file.open("w") as f:
            yaml.dump(config_data, f)

        # Setup system
        config = ConfigLoader.load(config_file)
        router = EventRouter()
        registry = HandlerRegistry()
        registry.discover()

        # Register handlers with config - this should configure the handler
        registry.register_all(router, config=config.get("handlers"))

        # Get the handler and manually configure it (since registry doesn't set these yet)
        pre_tool_use_chain = router.get_chain(EventType.PRE_TOOL_USE)
        handler = pre_tool_use_chain.get("enforce-markdown-organization")
        assert handler is not None

        # Manually set config (workaround until registry supports handler options)
        handler._workspace_root = project_context
        handler._track_plans_in_project = "CLAUDE/Plan"
        handler._plan_workflow_docs = "CLAUDE/PlanWorkflow.md"

        # Simulate planning mode write (to ~/.claude/plans/)
        hook_input = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/home/user/.claude/plans/my-test-plan.md",
                "content": "# My Test Plan\n\nThis is a test.",
            },
        }

        result = router.route(EventType.PRE_TOOL_USE, hook_input)

        # Verify interception and redirect
        assert result.result.decision == Decision.ALLOW
        assert result.terminated_by == "enforce-markdown-organization"
        assert result.result.context is not None
        assert len(result.result.context) > 0

        # Verify plan folder was created
        created_folders = list(plan_dir.iterdir())
        assert len(created_folders) == 1
        assert created_folders[0].name.startswith("00001-")

        # Verify PLAN.md was created
        plan_file = created_folders[0] / "PLAN.md"
        assert plan_file.exists()
        content = plan_file.read_text()
        assert "# My Test Plan" in content
