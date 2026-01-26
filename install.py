#!/usr/bin/env python3
"""Install claude-code-hooks-daemon into a Claude Code project.

This script:
1. Backs up existing .claude/hooks directory (if exists)
2. Creates all hook entry point files
3. Creates .claude/settings.json registering all hooks
4. Creates .claude/hooks-daemon.yaml with handler configuration
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime


def find_project_root() -> Path:
    """Find project root by looking for .claude directory."""
    current = Path.cwd()

    # Check current directory first
    if (current / ".claude").exists():
        return current

    # Search upward through parents
    for parent in current.parents:
        if (parent / ".claude").exists():
            return parent

    # If not found, use current directory and we'll create .claude
    return current


def backup_existing_hooks(project_root: Path) -> None:
    """Backup existing .claude/hooks directory if it exists."""
    hooks_dir = project_root / ".claude" / "hooks"

    if hooks_dir.exists():
        backup_dir = project_root / ".claude" / "hooks.bak"

        # If backup already exists, add timestamp
        if backup_dir.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = project_root / ".claude" / f"hooks.bak.{timestamp}"

        hooks_dir.rename(backup_dir)
        print(f"✅ Backed up existing hooks to {backup_dir.relative_to(project_root)}")

    # Create fresh hooks directory
    hooks_dir.mkdir(parents=True, exist_ok=True)


def create_forwarder_script(hooks_dir: Path, hook_name: str, event_name: str) -> None:
    """Create a forwarder script that routes to daemon via Unix socket.

    Args:
        hooks_dir: Path to .claude/hooks directory
        hook_name: Hook filename (e.g., 'pre-tool-use')
        event_name: Event name for JSON (e.g., 'PreToolUse')
    """
    hook_file = hooks_dir / hook_name

    hook_content = f"""#!/bin/bash
#
# Claude Code Hooks - {event_name} Forwarder
#
# Forwards {event_name} hook calls to daemon via Unix socket.
# CRITICAL: Pipes JSON directly - NEVER store in shell variables.
# CRITICAL: All errors output valid JSON to stdout for agent visibility.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
source "$SCRIPT_DIR/../init.sh"

# Try to start daemon - if it fails, output proper JSON error to stdout
if ! ensure_daemon; then
    emit_hook_error "{event_name}" "daemon_startup_failed" \\
        "Failed to start hooks daemon. Check logs with: python -m claude_code_hooks_daemon.daemon.cli logs"
    exit 0  # Exit 0 so Claude processes the JSON response
fi

# Pipe directly from stdin through jq to daemon - no shell variable storage
# send_request_stdin handles socket errors internally and outputs JSON on failure
jq -c '{{event: "{event_name}", hook_input: .}}' | send_request_stdin
"""

    hook_file.write_text(hook_content)
    hook_file.chmod(0o755)  # Make executable


def copy_init_script(project_root: Path, daemon_dir: Path, self_install: bool = False) -> None:
    """Copy init.sh script to .claude directory.

    Args:
        project_root: Project root directory
        daemon_dir: Path to daemon repository
        self_install: If True, create symlink instead of copying
    """
    import shutil

    source_init = daemon_dir / "init.sh"
    dest_init = project_root / ".claude" / "init.sh"

    if not source_init.exists():
        raise FileNotFoundError(f"init.sh not found at {source_init}")

    if self_install:
        # For self-installation, create symlink to avoid duplication
        if dest_init.exists() or dest_init.is_symlink():
            dest_init.unlink()
        dest_init.symlink_to(source_init)
        print(f"   ✅ Symlinked init.sh")
    else:
        shutil.copy2(source_init, dest_init)
        dest_init.chmod(0o755)  # Make executable
        print(f"   ✅ Copied init.sh")


def create_all_hooks(hooks_dir: Path) -> None:
    """Create all Claude Code hook forwarder scripts."""
    print("\n📝 Creating hook forwarder scripts...")

    # All hooks now use daemon forwarder pattern
    daemon_hooks = {
        "pre-tool-use": "PreToolUse",
        "post-tool-use": "PostToolUse",
        "session-start": "SessionStart",
        "permission-request": "PermissionRequest",
        "notification": "Notification",
        "user-prompt-submit": "UserPromptSubmit",
        "stop": "Stop",
        "subagent-stop": "SubagentStop",
        "pre-compact": "PreCompact",
        "session-end": "SessionEnd",
    }

    for hook_name, event_name in daemon_hooks.items():
        create_forwarder_script(hooks_dir, hook_name, event_name)
        print(f"   ✅ {hook_name}")


def create_settings_json(project_root: Path, force: bool = False) -> None:
    """Create .claude/settings.json registering all hooks."""
    settings_file = project_root / ".claude" / "settings.json"

    # Check if settings.json already exists
    if settings_file.exists() and not force:
        print(f"\n⚠️  {settings_file.relative_to(project_root)} already exists")
        response = input("   Overwrite? [y/N]: ").strip().lower()
        if response != 'y':
            print("   Skipped settings.json")
            return

    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": ".claude/hooks/pre-tool-use",
                            "timeout": 60
                        }
                    ]
                }
            ],
            "PostToolUse": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": ".claude/hooks/post-tool-use",
                            "timeout": 60
                        }
                    ]
                }
            ],
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": ".claude/hooks/session-start"
                        }
                    ]
                }
            ],
            "Notification": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": ".claude/hooks/notification"
                        }
                    ]
                }
            ],
            "PermissionRequest": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": ".claude/hooks/permission-request"
                        }
                    ]
                }
            ],
            "PreCompact": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": ".claude/hooks/pre-compact"
                        }
                    ]
                }
            ],
            "SessionEnd": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": ".claude/hooks/session-end"
                        }
                    ]
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": ".claude/hooks/stop"
                        }
                    ]
                }
            ],
            "SubagentStop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": ".claude/hooks/subagent-stop"
                        }
                    ]
                }
            ],
            "UserPromptSubmit": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": ".claude/hooks/user-prompt-submit"
                        }
                    ]
                }
            ]
        }
    }

    settings_file.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"✅ Created {settings_file.relative_to(project_root)}")


def create_daemon_env(project_root: Path, daemon_root: str) -> None:
    """Create .claude/hooks-daemon.env to override daemon root directory.

    Args:
        project_root: Project root directory
        daemon_root: Path to daemon root directory
    """
    env_file = project_root / ".claude" / "hooks-daemon.env"

    env_content = f"""# Claude Code Hooks Daemon - Environment Configuration
#
# This file overrides default daemon paths for self-installation or custom setups.
# It is sourced by init.sh before daemon startup.

# Root directory of the hooks daemon installation
# Default: $PROJECT_PATH/.claude/hooks-daemon
# Self-install: $PROJECT_PATH (project root)
HOOKS_DAEMON_ROOT_DIR="{daemon_root}"
"""

    env_file.write_text(env_content)
    print(f"✅ Created {env_file.relative_to(project_root)}")


def create_daemon_config(project_root: Path, force: bool = False) -> None:
    """Create .claude/hooks-daemon.yaml configuration."""
    config_file = project_root / ".claude" / "hooks-daemon.yaml"

    # Check if config already exists
    if config_file.exists() and not force:
        print(f"\n⚠️  {config_file.relative_to(project_root)} already exists")
        response = input("   Overwrite? [y/N]: ").strip().lower()
        if response != 'y':
            print("   Skipped hooks-daemon.yaml")
            return

    config = """version: 1.0

# Daemon configuration
daemon:
  idle_timeout_seconds: 600  # Auto-shutdown after 10 minutes of inactivity
  log_level: INFO

  # enable_hello_world_handlers: true  # Uncomment to test hooks are working
                                       # Shows "✅ {Event} hook system active" messages

# Built-in handler configuration
# Handlers run in priority order (lower number = earlier execution)
# Priority ranges: 5=test, 10-20=safety, 25-45=workflow, 50-60=tool usage
handlers:
  # PreToolUse handlers (run before every tool call)
  pre_tool_use:
    # SAFETY HANDLERS (Priority 10-20)
    destructive_git:       # Blocks git reset --hard, git clean -f, etc
      enabled: true
      priority: 10

    sed_blocker:           # Blocks sed command usage (use Edit tool instead)
      enabled: true
      priority: 10

    absolute_path:         # Enforces absolute paths in file operations
      enabled: true
      priority: 12

    worktree_file_copy:    # Prevents copying files between git worktrees
      enabled: true
      priority: 15

    git_stash:             # Warns about git stash (stashes can be lost)
      enabled: true
      priority: 20

    # CODE QUALITY HANDLERS (Priority 25-45)
    eslint_disable:        # Prevents ESLint suppression comments
      enabled: true
      priority: 30

    tdd_enforcement:       # Enforces test-first development
      enabled: true
      priority: 35

    # WORKFLOW HANDLERS (Priority 40-50)
    validate_plan_number:  # Validates plan number format (001-, 002-, etc)
      enabled: false       # Optional - enable for projects using CLAUDE/Plan/
      priority: 40

    plan_time_estimates:   # Blocks time estimates in plan files
      enabled: false       # Optional - enable for projects using CLAUDE/Plan/
      priority: 45

    plan_workflow:         # Provides guidance when creating plans
      enabled: false       # Optional - enable for projects using CLAUDE/Plan/
      priority: 45

    npm_command:           # Restricts npm commands to approved list
      enabled: false       # Optional - enable for strict npm usage control
      priority: 50

    markdown_organization: # Enforces markdown file organization rules
      enabled: false       # Optional - enable for strict md organization
      priority: 50

    # TOOL USAGE HANDLERS (Priority 50-60)
    web_search_year:       # Fixes year in web search queries (uses current year)
      enabled: true
      priority: 55

    british_english:       # Warns about American English spelling
      enabled: true
      priority: 60

  # PostToolUse handlers (run after tool execution)
  post_tool_use:
    # validate_eslint_on_write:  # Runs ESLint after file writes
    #   enabled: false            # Optional - enable for automatic ESLint validation
    #   priority: 10

    # validate_sitemap:          # Validates sitemap structure after writes
    #   enabled: false            # Optional - enable for sitemap validation
    #   priority: 20

  # SessionStart handlers (run when session starts)
  session_start:
    # workflow_state_restoration:  # Restores workflow state after compaction
    #   enabled: false              # Optional - enable for workflow state management
    #   priority: 10

  # PreCompact handlers (run before conversation compaction)
  pre_compact:
    # workflow_state_pre_compact:  # Saves workflow state before compaction
    #   enabled: false              # Optional - enable for workflow state management
    #   priority: 10

  # SessionEnd handlers (run when session ends)
  session_end: {}

  # SubagentStop handlers (run when subagent completes)
  subagent_stop:
    # remind_prompt_library:  # Reminds about prompt library after agent work
    #   enabled: false         # Optional - enable for prompt library reminders
    #   priority: 10

    # remind_validator:       # Reminds about HTML validation
    #   enabled: false         # Optional - enable for validation reminders
    #   priority: 20

  # UserPromptSubmit handlers (run when user submits prompt)
  user_prompt_submit:
    # auto_continue:  # Auto-continues on 'continue' keyword
    #   enabled: false # Optional - enable for auto-continue behavior
    #   priority: 10

  # Other hook events
  permission_request: {}
  notification: {}
  stop: {}

# Project-level handlers (custom handlers in .claude/hooks/handlers/)
# Example:
# plugins:
#   - type: "file"
#     path: ".claude/hooks/handlers/pre_tool_use/my_handler.py"
#     class: "MyHandler"
#     events: ["PreToolUse"]
plugins: []
"""

    config_file.write_text(config)
    print(f"✅ Created {config_file.relative_to(project_root)}")


def create_claude_gitignore(project_root: Path) -> None:
    """Create .claude/.gitignore to exclude daemon from project git.

    Args:
        project_root: Project root directory
    """
    gitignore_file = project_root / ".claude" / ".gitignore"

    gitignore_content = """# Claude Code Hooks Daemon
# Exclude the cloned daemon repository (users install it themselves)
hooks-daemon/

# Backup directories created during installation
hooks.bak/
hooks.bak.*/

# Environment files (may contain local paths)
hooks-daemon.env

# Daemon runtime files
*.sock
*.pid

# Python cache
__pycache__/
*.pyc
*.pyo
*.pyd

# Virtual environments (if created locally)
venv/
.venv/
"""

    gitignore_file.write_text(gitignore_content)
    print(f"✅ Created {gitignore_file.relative_to(project_root)}")


def create_project_handler_structure(project_root: Path) -> None:
    """Create project-level handler directory structure with examples.

    Creates .claude/hooks/handlers/ with subdirectories for each hook event,
    README files, and example handler templates.

    Args:
        project_root: Path to project root directory
    """
    print("\n📝 Creating project handler structure...")

    handlers_root = project_root / ".claude" / "hooks" / "handlers"
    handlers_root.mkdir(parents=True, exist_ok=True)

    # Hook events (10 total)
    hook_events = [
        "pre_tool_use",
        "post_tool_use",
        "session_start",
        "session_end",
        "permission_request",
        "notification",
        "user_prompt_submit",
        "stop",
        "subagent_stop",
        "pre_compact",
    ]

    # Create main README
    main_readme = handlers_root / "README.md"
    if not main_readme.exists():
        main_readme.write_text("""# Project-Level Handlers

This directory contains **project-specific** handlers for Claude Code hooks.

## When to Use Project-Level Handlers

Use project-level handlers when you need custom hook behaviour that is:
- Specific to this project's workflow
- Not generally useful for other projects
- Related to project-specific conventions or policies

## Handler Development Workflow

1. **TDD Required** - Write tests FIRST, then implementation
2. **Use scaffolding tool** - Run handler creation command
3. **Implement matches() and handle()** methods
4. **Test thoroughly** - Minimum 95% coverage required
5. **Register in config** - Add to .claude/hooks-daemon.yaml

## Directory Structure

Each hook event has its own subdirectory:
- `pre_tool_use/` - Before tool execution
- `post_tool_use/` - After tool execution
- `session_start/` - When session begins
- (etc for all 10 hook events)

Each subdirectory contains:
- `README.md` - Event-specific guide
- Handler Python files
- `tests/` - Test files (required)

## Creating a New Handler

See individual event README files for examples and templates.

For general handler development, see:
.claude/hooks-daemon/README.md
""")
        print(f"   ✅ Created main README")

    # Create subdirectory for each event
    for event in hook_events:
        event_dir = handlers_root / event
        event_dir.mkdir(exist_ok=True)

        # Create tests subdirectory
        tests_dir = event_dir / "tests"
        tests_dir.mkdir(exist_ok=True)

        # Create event-specific README
        event_readme = event_dir / "README.md"
        if not event_readme.exists():
            event_readme.write_text(f"""# {event.replace('_', ' ').title()} Handlers

Project-level handlers for the **{event.replace('_', '')}** hook event.

## When This Hook Fires

[TODO: Describe when this hook event is triggered]

## Example Use Cases

- [Example 1]
- [Example 2]
- [Example 3]

## Creating a Handler

See `example_handler.py.example` for a complete template.

## Testing

All handlers MUST have tests in `tests/` directory.
Minimum 95% coverage required.
""")

        # Create example handler template (only for pre_tool_use as reference)
        if event == "pre_tool_use":
            example_handler = event_dir / "example_handler.py.example"
            if not example_handler.exists():
                example_handler.write_text('''"""ExampleHandler - template for project-level handlers."""

import sys
from pathlib import Path

# Add daemon to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "hooks-daemon/src"))

from claude_code_hooks_daemon.core import Handler, HookResult
from claude_code_hooks_daemon.core.utils import get_bash_command, get_file_path


class ExampleHandler(Handler):
    """Example handler showing the basic pattern.

    Replace this docstring with your handler's purpose.
    """

    def __init__(self) -> None:
        """Initialise handler with name and priority."""
        super().__init__(
            name="example-handler",
            priority=50,  # Adjust priority (5-60 range)
            terminal=True  # Set False for non-blocking guidance
        )

    def matches(self, hook_input: dict) -> bool:
        """Check if this handler should execute.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            True if handler should execute, False otherwise
        """
        # Example: Match all Bash tool calls
        command = get_bash_command(hook_input)
        if command and "example" in command:
            return True

        # Example: Match file operations
        file_path = get_file_path(hook_input)
        if file_path and file_path.startswith("/forbidden/"):
            return True

        return False

    def handle(self, hook_input: dict) -> HookResult:
        """Execute handler logic.

        Args:
            hook_input: Hook input dictionary from Claude Code

        Returns:
            HookResult with decision and optional reason/context
        """
        # Example: Block with reason
        return HookResult(
            decision="deny",
            reason="This is an example denial message",
        )

        # Example: Allow with guidance (non-terminal handler)
        # return HookResult(
        #     decision="allow",
        #     context="Example guidance message",
        # )
''')

            example_test = tests_dir / "test_example_handler.py.example"
            if not example_test.exists():
                example_test.write_text('''"""Tests for ExampleHandler."""

import pytest
import sys
from pathlib import Path

# Add project handlers to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from example_handler import ExampleHandler


class TestExampleHandler:
    """Test suite for ExampleHandler."""

    def test_handler_initialization(self):
        """Test handler is properly initialized."""
        handler = ExampleHandler()
        assert handler.name == "example-handler"
        assert handler.priority == 50
        assert handler.terminal is True

    def test_matches_bash_with_example_keyword(self):
        """Test handler matches Bash commands containing 'example'."""
        handler = ExampleHandler()
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo example test"}
        }
        assert handler.matches(hook_input) is True

    def test_does_not_match_other_bash(self):
        """Test handler ignores Bash commands without keyword."""
        handler = ExampleHandler()
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"}
        }
        assert handler.matches(hook_input) is False

    def test_handle_returns_deny(self):
        """Test handler returns deny decision."""
        handler = ExampleHandler()
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": "echo example"}
        }
        result = handler.handle(hook_input)
        assert result.decision == "deny"
        assert "example denial" in result.reason.lower()


# Run tests with: python3 -m pytest tests/test_example_handler.py -v
''')

    print(f"   ✅ Created {len(hook_events)} event directories with README files")
    print(f"   ✅ Created example handler and test templates in pre_tool_use/")


def verify_installation(project_root: Path) -> bool:
    """Verify installation was successful.

    Returns:
        True if all checks pass, False otherwise
    """
    print("\n🔍 Verifying installation...")

    checks = [
        (project_root / ".claude" / ".gitignore", ".gitignore"),
        (project_root / ".claude" / "init.sh", "init.sh"),
        (project_root / ".claude" / "hooks" / "pre-tool-use", "pre-tool-use hook"),
        (project_root / ".claude" / "settings.json", "settings.json"),
        (project_root / ".claude" / "hooks-daemon.yaml", "hooks-daemon.yaml"),
    ]

    all_good = True
    for path, description in checks:
        if path.exists():
            print(f"   ✅ {description}")
        else:
            print(f"   ❌ {description} NOT FOUND")
            all_good = False

    return all_good


def main() -> int:
    """Main installation function."""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Install claude-code-hooks-daemon into a Claude Code project"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing configuration files without prompting"
    )
    parser.add_argument(
        "--self-install",
        action="store_true",
        help="Install hooks on the daemon repository itself (self-installation mode)"
    )
    args = parser.parse_args()

    print("🚀 Claude Code Hooks Daemon Installer\n")

    # Find project root
    project_root = find_project_root()
    print(f"📁 Project root: {project_root}")

    # Create .claude directory if it doesn't exist
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(exist_ok=True)

    # Backup existing hooks
    backup_existing_hooks(project_root)

    # Create .gitignore to exclude daemon from project git
    create_claude_gitignore(project_root)

    # Find daemon directory (where this script lives)
    daemon_dir = Path(__file__).parent.resolve()

    # Detect self-installation (installer running from daemon repo itself)
    self_install = args.self_install or (daemon_dir == project_root)
    if self_install:
        print("🔄 Self-installation mode detected")

    # Copy init.sh to .claude directory
    print("\n📝 Copying lifecycle scripts...")
    copy_init_script(project_root, daemon_dir, self_install=self_install)

    # Create all hook files
    hooks_dir = project_root / ".claude" / "hooks"
    create_all_hooks(hooks_dir)

    # Create configuration files
    print("\n📝 Creating configuration files...")
    create_settings_json(project_root, force=args.force)
    create_daemon_config(project_root, force=args.force)

    # Create daemon environment file for self-installation
    if self_install:
        create_daemon_env(project_root, daemon_root="$PROJECT_PATH")

    # Create project handler directory structure
    create_project_handler_structure(project_root)

    # Verify installation
    if verify_installation(project_root):
        print("\n🎉 Installation complete!")
        print("\n📚 Daemon Architecture:")
        print("   • Lazy startup - daemon starts on first hook call")
        print("   • Auto-shutdown after 10 minutes of inactivity")
        print("   • Sub-millisecond response times after warmup")
        print("\n📚 Daemon Management:")
        print("   • Start:   python3 -m claude_code_hooks_daemon.daemon.cli start")
        print("   • Stop:    python3 -m claude_code_hooks_daemon.daemon.cli stop")
        print("   • Status:  python3 -m claude_code_hooks_daemon.daemon.cli status")
        print("   • Restart: python3 -m claude_code_hooks_daemon.daemon.cli restart")
        print("\n📚 Files Created:")
        print("   • .claude/.gitignore - Excludes hooks-daemon/ from git")
        print("   • .claude/init.sh - Daemon lifecycle functions")
        print("   • .claude/hooks/* - Forwarder scripts (route to daemon)")
        print("   • .claude/settings.json - Hook registration")
        print("   • .claude/hooks-daemon.yaml - Handler configuration")
        print("\n⚠️  Remember to commit .claude/ files (except hooks-daemon/) to git!")
        return 0
    else:
        print("\n❌ Installation failed - some files missing")
        return 1


if __name__ == "__main__":
    sys.exit(main())
