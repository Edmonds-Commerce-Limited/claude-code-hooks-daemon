#!/usr/bin/env python3
"""Install claude-code-hooks-daemon into a Claude Code project.

DEPRECATION NOTICE:
    This script is superseded by the modular bash installer:
      - Layer 1: install.sh (curl-fetched entry point)
      - Layer 2: scripts/install_version.sh (version-specific orchestrator)
      - Library: scripts/install/*.sh (shared modules)

    The new architecture eliminates code duplication between install and
    upgrade paths, adds config preservation with diff/merge/validate, and
    provides full state rollback on failure.

    This file is retained for backward compatibility with older tags that
    don't have the Layer 2 installer. New installations should use:
      curl -sSL <repo>/install.sh | bash

This script:
1. Backs up existing .claude/hooks directory (if exists)
2. Creates all hook entry point files
3. Creates .claude/settings.json registering all hooks
4. Creates .claude/hooks-daemon.yaml with handler configuration
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime


class InstallationError(Exception):
    """Error during installation validation."""

    pass


def is_hooks_daemon_repo(directory: Path) -> bool:
    """Check if directory is the hooks-daemon repository by git remote.

    Uses git remote URL as source of truth rather than magic path detection.
    This correctly identifies the hooks-daemon repo even if cloned with a
    different directory name.

    Args:
        directory: Directory to check

    Returns:
        True if directory is the hooks-daemon repository
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        remote_url = result.stdout.strip().lower()
        # Match any of the known hooks-daemon repo URLs
        hooks_daemon_patterns = [
            "claude-code-hooks-daemon",
            "claude_code_hooks_daemon",
        ]
        return any(pattern in remote_url for pattern in hooks_daemon_patterns)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _load_config_safe(project_root: Path) -> dict | None:
    """Safely load config file without raising exceptions.

    Args:
        project_root: Project root directory

    Returns:
        Config dict or None if loading fails
    """
    import yaml

    config_file = project_root / ".claude" / "hooks-daemon.yaml"
    if not config_file.exists():
        return None

    try:
        with config_file.open() as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def _validate_not_nested(project_root: Path) -> None:
    """Fail fast if nested installation detected.

    Checks for two scenarios:
    1. Existing nested structure (.claude/hooks-daemon/.claude)
    2. Trying to install in the hooks-daemon repo without self_install_mode

    Args:
        project_root: Project root to validate

    Raises:
        InstallationError: If nested installation detected
    """
    # Check for nested hooks-daemon installation inside hooks-daemon
    # Having .claude/hooks-daemon/.claude is fine (the repo has its own .claude dir).
    # A true nested install is .claude/hooks-daemon/.claude/hooks-daemon.
    nested_install = project_root / ".claude" / "hooks-daemon" / ".claude" / "hooks-daemon"
    if nested_install.exists():
        raise InstallationError(
            f"NESTED INSTALLATION DETECTED!\n"
            f"Found: {nested_install}\n"
            f"Remove {project_root / '.claude' / 'hooks-daemon'} and reinstall."
        )

    # Check if we're inside an existing hooks-daemon directory
    hooks_daemon_marker = project_root / ".claude" / "hooks-daemon" / "src"
    if hooks_daemon_marker.exists():
        # Check for self_install_mode in the outer project's config
        config = _load_config_safe(project_root)
        if config:
            daemon_config = config.get("daemon", {})
            if daemon_config.get("self_install_mode", False):
                return  # Self-install mode enabled, allow

        raise InstallationError(
            f"Cannot install: appears to be inside an existing hooks-daemon installation.\n"
            f"Found daemon source at: {hooks_daemon_marker}\n"
            f"To develop on hooks-daemon itself, set 'self_install_mode: true' in config."
        )


def validate_installation_target(project_root: Path, self_install_requested: bool = False) -> None:
    """Comprehensive pre-flight validation before installation.

    Validates:
    1. Not inside an existing hooks-daemon installation
    2. Not the hooks-daemon repo itself (unless self_install_mode)
    3. No nested structure exists

    Args:
        project_root: Project root to install into
        self_install_requested: Whether --self-install flag was passed

    Raises:
        InstallationError: If installation would create invalid state
    """
    # 1. Check not inside existing hooks-daemon installation
    for parent in project_root.parents:
        if (parent / ".claude" / "hooks-daemon").exists():
            raise InstallationError(
                f"Cannot install: {project_root} is inside an existing installation at {parent}"
            )

    # 2. Check git remote if this looks like a git repo
    if (project_root / ".git").exists():
        if is_hooks_daemon_repo(project_root):
            # Check if self-install is being requested or already configured
            config = _load_config_safe(project_root)
            has_self_install_config = config and config.get("daemon", {}).get(
                "self_install_mode", False
            )

            if not self_install_requested and not has_self_install_config:
                raise InstallationError(
                    "This is the hooks-daemon repository.\n"
                    "To install for development, use --self-install flag or add to "
                    ".claude/hooks-daemon.yaml:\n"
                    "  daemon:\n"
                    "    self_install_mode: true"
                )

    # 3. Check for nested structure
    _validate_not_nested(project_root)


def find_project_root(explicit_root: Path | None = None) -> Path:
    """Find project root by looking for .claude directory.

    No magic path detection - uses explicit paths and git remote as source of truth.

    Args:
        explicit_root: Explicitly specified project root (overrides detection)

    Returns:
        Path to project root directory

    Raises:
        InstallationError: If nested installation detected
    """
    if explicit_root:
        resolved = explicit_root.resolve()
        # Validate but don't check self_install_mode yet (that's done in main)
        return resolved

    current = Path.cwd()

    # Search upward for .claude directory
    for candidate in [current, *current.parents]:
        claude_dir = candidate / ".claude"
        if claude_dir.exists():
            return candidate

    # Not found - return current directory and we'll create .claude
    # (validation happens in main() after we know about --self-install flag)
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

    return hook_file


def create_status_line_script(hooks_dir: Path) -> Path:
    """Create status-line script with custom logic for displaying status.

    Status line has different logic than standard forwarders:
    - Returns plain text (not JSON)
    - Joins context array into a single line
    - Has fallback for empty responses

    Args:
        hooks_dir: Path to .claude/hooks directory

    Returns:
        Path to created hook file
    """
    hook_file = hooks_dir / "status-line"

    hook_content = """#!/bin/bash
#
# Claude Code Hooks - Status Line
#
# Forwards Status event to daemon via Unix socket and outputs plain text.
# This hook is called by Claude Code to populate the status line display.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../init.sh"

# Ensure daemon is running (lazy startup)
if ! ensure_daemon; then
    # ERROR: Daemon failed to start - make it visible
    echo "⚠️ DAEMON FAILED"
    exit 1
fi

# Pipe JSON directly through socket
# Add hook_event_name to input, then wrap in standard request format
# Note: Status event returns {"text": "..."} directly
jq -c '. + {hook_event_name: "Status"} | {event: "Status", hook_input: .}' | send_request_stdin | jq -r '
  if .error then
    "⚠️ ERROR: " + .error
  elif .text then
    .text
  else
    "⚠️ NO STATUS DATA"
  end
'
"""

    hook_file.write_text(hook_content)
    hook_file.chmod(0o755)  # Make executable

    return hook_file


def check_git_filemode(project_root: Path) -> bool:
    """Check if git core.fileMode is disabled.

    Args:
        project_root: Project root directory

    Returns:
        True if core.fileMode=false, False otherwise
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "config", "--get", "core.fileMode"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        # core.fileMode=false means git doesn't track permission changes
        return result.returncode == 0 and result.stdout.strip().lower() == "false"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def update_git_index_executable(project_root: Path, hook_files: list[Path]) -> tuple[bool, bool]:
    """Update git index to mark hook files as executable.

    Required when core.fileMode=false - git won't track permission changes
    automatically, so we must explicitly update the index.

    Args:
        project_root: Project root directory
        hook_files: List of hook file paths to mark as executable

    Returns:
        Tuple of (success, files_were_tracked)
        - success: True if update succeeded or files aren't tracked yet
        - files_were_tracked: True if files were already in git index
    """
    import subprocess

    # Convert paths to relative paths from project root
    relative_paths = []
    for hook_file in hook_files:
        try:
            rel_path = hook_file.relative_to(project_root)
            relative_paths.append(str(rel_path))
        except ValueError:
            # File not under project_root, skip
            continue

    if not relative_paths:
        return False, False

    try:
        # First check if any files are actually tracked in git
        # git ls-files returns tracked files
        result = subprocess.run(
            ["git", "ls-files"] + relative_paths,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
        )

        # If no tracked files found, return success but indicate files aren't tracked
        if not result.stdout.strip():
            return True, False

        # Files are tracked, update the index
        subprocess.run(
            ["git", "update-index", "--chmod=+x"] + relative_paths,
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return True, True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False, False


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


def copy_slash_commands(project_root: Path, daemon_dir: Path, self_install: bool = False) -> None:
    """Copy slash commands to .claude/commands directory.

    Args:
        project_root: Project root directory
        daemon_dir: Path to daemon repository
        self_install: If True, create symlink instead of copying
    """
    import shutil

    # Create .claude/commands directory if it doesn't exist
    commands_dir = project_root / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    # Copy hooks-daemon-update command
    source_cmd = daemon_dir / ".claude" / "commands" / "hooks-daemon-update.md"
    dest_cmd = commands_dir / "hooks-daemon-update.md"

    if not source_cmd.exists():
        # Command file doesn't exist in daemon - skip silently
        # This allows older daemon versions to work without the command
        return

    if self_install:
        # For self-installation, create symlink to avoid duplication
        if dest_cmd.exists() or dest_cmd.is_symlink():
            dest_cmd.unlink()
        dest_cmd.symlink_to(source_cmd)
        print(f"   ✅ Symlinked /hooks-daemon-update command")
    else:
        shutil.copy2(source_cmd, dest_cmd)
        print(f"   ✅ Copied /hooks-daemon-update command")


def create_all_hooks(hooks_dir: Path) -> list[Path]:
    """Create all Claude Code hook forwarder scripts.

    Returns:
        List of created hook file paths
    """
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

    hook_files = []
    for hook_name, event_name in daemon_hooks.items():
        hook_file = create_forwarder_script(hooks_dir, hook_name, event_name)
        hook_files.append(hook_file)
        print(f"   ✅ {hook_name}")

    # Create status-line script (custom logic, not a standard forwarder)
    status_line_file = create_status_line_script(hooks_dir)
    hook_files.append(status_line_file)
    print(f"   ✅ status-line")

    return hook_files


def create_settings_json(project_root: Path, force: bool = False) -> None:
    """Create .claude/settings.json registering all hooks."""
    settings_file = project_root / ".claude" / "settings.json"

    # Backup existing settings.json if it exists
    if settings_file.exists() and not force:
        backup_file = project_root / ".claude" / "settings.json.bak"

        # If backup already exists, add timestamp
        if backup_file.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = project_root / ".claude" / f"settings.json.bak.{timestamp}"

        settings_file.rename(backup_file)
        print(f"✅ Backed up existing settings.json to {backup_file.relative_to(project_root)}")

    settings = {
        "statusLine": {"type": "command", "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/status-line'},
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [
                        {"type": "command", "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/pre-tool-use', "timeout": 60}
                    ]
                }
            ],
            "PostToolUse": [
                {
                    "hooks": [
                        {"type": "command", "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/post-tool-use', "timeout": 60}
                    ]
                }
            ],
            "SessionStart": [
                {"hooks": [{"type": "command", "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/session-start'}]}
            ],
            "Notification": [
                {"hooks": [{"type": "command", "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/notification'}]}
            ],
            "PermissionRequest": [
                {"hooks": [{"type": "command", "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/permission-request'}]}
            ],
            "PreCompact": [
                {"hooks": [{"type": "command", "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/pre-compact'}]}
            ],
            "SessionEnd": [
                {"hooks": [{"type": "command", "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/session-end'}]}
            ],
            "Stop": [{"hooks": [{"type": "command", "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/stop'}]}],
            "SubagentStop": [
                {"hooks": [{"type": "command", "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/subagent-stop'}]}
            ],
            "UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/user-prompt-submit'}]}
            ],
        },
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

    # Backup existing config if it exists
    if config_file.exists() and not force:
        backup_file = project_root / ".claude" / "hooks-daemon.yaml.bak"

        # If backup already exists, add timestamp
        if backup_file.exists():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = project_root / ".claude" / f"hooks-daemon.yaml.bak.{timestamp}"

        config_file.rename(backup_file)
        print(f"✅ Backed up existing hooks-daemon.yaml to {backup_file.relative_to(project_root)}")

    config = """version: "1.0"

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

  # SessionStart handlers (run when session starts)
  session_start:
    yolo_container_detection:     # Detects YOLO container environments (enabled by default)
      enabled: true                # Set to false to disable YOLO detection
      priority: 40                 # Workflow range priority
      min_confidence_score: 3      # Minimum score to trigger detection (0-12 range)
      show_detailed_indicators: true   # Show detected indicators in context
      show_workflow_tips: true     # Show container workflow implications

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

  # UserPromptSubmit handlers (run when user submits prompt)
  user_prompt_submit:
    # auto_continue:  # Auto-continues on 'continue' keyword
    #   enabled: false # Optional - enable for auto-continue behavior
    #   priority: 10

  # Other hook events
  permission_request: {}
  notification: {}
  stop: {}

  # Status line handlers (provide custom status line display)
  status_line: {}

# Project-level handlers (custom handlers in .claude/hooks/handlers/)
# Uncomment and customize to add custom handlers:
# plugins:
#   paths: []  # Optional: additional Python module search paths
#   plugins:   # List of plugin configurations
#     # Example: Single handler from a file
#     - path: ".claude/hooks/handlers/pre_tool_use/my_handler.py"
#       handlers: ["MyHandler"]  # Optional: specific class names (null = load all)
#       enabled: true
#
#     # Example: Load all handlers from a directory module
#     - path: ".claude/hooks/handlers/post_tool_use/"
#       handlers: null  # Load all Handler classes found
#       enabled: true
plugins:
  paths: []
  plugins: []
"""

    config_file.write_text(config)
    print(f"✅ Created {config_file.relative_to(project_root)}")


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
                example_handler.write_text(
                    '''"""ExampleHandler - template for project-level handlers."""

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
'''
                )

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

    # File existence checks (excluding .gitignore)
    checks = [
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

    # Validate .gitignore CONTENT (not just existence)
    gitignore_valid, missing = verify_gitignore_content(project_root)
    if gitignore_valid:
        print(f"   ✅ .gitignore (with required patterns)")
    else:
        print(f"   ❌ .gitignore INVALID")
        if missing == ["File does not exist"]:
            print(f"      File does not exist")
        elif missing == ["File is empty"]:
            print(f"      File is empty")
        else:
            print(f"      Missing required patterns: {', '.join(missing)}")
        print(f"      See instructions above for required content")
        all_good = False

    return all_good


def verify_gitignore_content(project_root: Path) -> tuple[bool, list[str]]:
    """Verify .gitignore contains required patterns by READING the file.

    Args:
        project_root: Project root directory

    Returns:
        Tuple of (is_valid, missing_patterns)
    """
    gitignore_path = project_root / ".claude" / ".gitignore"

    if not gitignore_path.exists():
        return False, ["File does not exist"]

    # READ the file content
    content = gitignore_path.read_text()

    if not content.strip():
        return False, ["File is empty"]

    # Critical patterns that MUST be present
    required_patterns = [
        "hooks-daemon/",
        "hooks.bak/",
        "*.sock",
        "*.pid",
    ]

    missing = [p for p in required_patterns if p not in content]

    return len(missing) == 0, missing


def show_gitignore_instructions(project_root: Path, daemon_dir: Path) -> None:
    """Show MANDATORY instructions for creating .claude/.gitignore.

    Reads the daemon's own .claude/.gitignore as the template and displays it
    with strong instructions. Never writes the file automatically.

    Args:
        project_root: Project root directory
        daemon_dir: Daemon repository directory (source of template)
    """
    root_gitignore = project_root / ".gitignore"
    claude_gitignore = project_root / ".claude" / ".gitignore"
    template_gitignore = daemon_dir / ".claude" / ".gitignore"

    # Check if root .gitignore blocks .claude/
    if root_gitignore.exists():
        content = root_gitignore.read_text()
        blocking_patterns = [".claude/", ".claude/*", "/.claude/", "/.claude/*"]

        for pattern in blocking_patterns:
            if pattern in content:
                print("\n⚠️  CRITICAL: Git Integration Issue Detected")
                print(f"   Your root .gitignore contains: {pattern}")
                print("   This will prevent .claude/ configuration files from being tracked.")
                print("\n🔧 REQUIRED Action:")
                print("   1. Remove '.claude/' from your root .gitignore")
                print("   2. Create .claude/.gitignore (instructions below)")
                print()
                break

    # Show MANDATORY .gitignore creation instructions
    if not claude_gitignore.exists():
        print("\n" + "=" * 70)
        print("⚠️  CRITICAL: .claude/.gitignore MUST be created")
        print("=" * 70)
        print("\nWithout this file, you will commit generated files (hooks-daemon/,")
        print("*.bak files, runtime files) which should NOT be in version control.")
        print("\n🔧 REQUIRED Action: Create .claude/.gitignore with this content:")
        print("\n" + "-" * 70)

        # Read and display template - FATAL if missing
        if not template_gitignore.exists():
            print(f"\n❌ FATAL ERROR: Template .gitignore not found")
            print(f"   Expected at: {template_gitignore}")
            print(f"   This file is required for installation.")
            print(f"\n   The daemon repository is corrupted or incomplete.")
            print(
                f"   Please clone from: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon"
            )
            sys.exit(1)

        template_content = template_gitignore.read_text()
        print(template_content)

        print("-" * 70)
        print("\n📋 Copy command:")
        print(f"   cp {template_gitignore} {claude_gitignore}")
        print("\n📚 Template source (single source of truth):")
        print(
            "   https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/blob/main/.claude/.gitignore"
        )
        print("\n" + "=" * 70)
        print()


def main() -> int:
    """Main installation function."""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="Install claude-code-hooks-daemon into a Claude Code project"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing configuration files without prompting",
    )
    parser.add_argument(
        "--self-install",
        action="store_true",
        help="Install hooks on the daemon repository itself (self-installation mode)",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        help="Explicitly specify the project root directory (must contain or will create .claude/)",
    )
    args = parser.parse_args()

    print("🚀 Claude Code Hooks Daemon Installer\n")

    # Find project root
    project_root = find_project_root(explicit_root=args.project_root)

    # Validate project root
    if not project_root.exists():
        print(f"❌ Error: Project root does not exist: {project_root}")
        return 1

    print(f"📁 Project root: {project_root}")

    # Find daemon directory (where this script lives)
    daemon_dir = Path(__file__).parent.resolve()

    # Detect self-installation early (needed for validation)
    self_install = args.self_install or (daemon_dir == project_root)

    # Pre-flight validation - fail fast if installation would create invalid state
    try:
        validate_installation_target(project_root, self_install_requested=self_install)
    except InstallationError as e:
        print(f"❌ Installation Error:\n{e}")
        return 1

    # CLIENT PROJECT SAFETY CHECKS (skip for self-install mode)
    if not self_install:
        print("\n🔍 Running client installation safety checks...")
        # Import validator only when needed (after venv is set up)
        sys.path.insert(0, str(Path(__file__).parent / "src"))
        from claude_code_hooks_daemon.install import ClientInstallValidator

        validation_result = ClientInstallValidator.validate_pre_install(project_root)

        # Display warnings
        for warning in validation_result.warnings:
            print(f"⚠️  {warning}")

        # Display errors and fail if any
        if not validation_result.passed:
            print(f"\n❌ Pre-installation validation failed with {len(validation_result.errors)} error(s):\n")
            for error in validation_result.errors:
                print(f"❌ {error}\n")
            print("Installation aborted. Please fix the issues above and try again.")
            return 1

        print("✅ Pre-installation checks passed")

    # Create .claude directory if it doesn't exist
    claude_dir = project_root / ".claude"
    claude_dir.mkdir(exist_ok=True)

    # Backup existing hooks
    backup_existing_hooks(project_root)

    # Show MANDATORY .gitignore instructions (never writes file automatically)
    show_gitignore_instructions(project_root, daemon_dir)

    # Log self-installation mode if applicable
    if self_install:
        print("🔄 Self-installation mode detected")

    # Copy init.sh to .claude directory
    print("\n📝 Copying lifecycle scripts...")
    copy_init_script(project_root, daemon_dir, self_install=self_install)

    # Copy slash commands
    copy_slash_commands(project_root, daemon_dir, self_install=self_install)

    # Create all hook files
    hooks_dir = project_root / ".claude" / "hooks"
    hook_files = create_all_hooks(hooks_dir)

    # Handle git core.fileMode=false (permission tracking disabled)
    if check_git_filemode(project_root):
        print("\n⚠️  Git Permission Tracking Disabled")
        print("   Detected: core.fileMode=false")
        print("   Git will NOT track executable permission changes automatically.")

        success, files_tracked = update_git_index_executable(project_root, hook_files)

        if files_tracked:
            # Files are already tracked - index was updated
            print("\n   ✅ Git index updated - hook files marked as executable")
            print("\n   ⚠️  ACTION REQUIRED:")
            print("      You must commit these permission changes:")
            print("      git commit -m 'chore: Make Claude hook dispatcher scripts executable'")
        elif success:
            # Files not yet tracked - need to add them first
            print("\n   ℹ️  Hook files are not yet tracked by git")
            print("\n   ⚠️  ACTION REQUIRED:")
            print("      1. Add hook files to git:")
            print("         git add .claude/hooks/*")
            print("      2. Mark as executable in git index:")
            hook_paths = " ".join([str(f.relative_to(project_root)) for f in hook_files])
            print(f"         git update-index --chmod=+x {hook_paths}")
            print("      3. Commit the changes:")
            print("         git commit -m 'chore: Add Claude hook dispatcher scripts'")
        else:
            # Error occurred
            print("\n   ⚠️  Failed to check/update git index")
            print("\n   Manual fix required:")
            print("      1. Add hook files: git add .claude/hooks/*")
            hook_paths = " ".join([str(f.relative_to(project_root)) for f in hook_files])
            print(f"      2. Mark executable: git update-index --chmod=+x {hook_paths}")
            print("      3. Commit: git commit -m 'chore: Add Claude hook dispatcher scripts'")

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
        # POST-INSTALLATION SAFETY CHECKS (skip for self-install mode)
        if not self_install:
            print("\n🔍 Running post-installation verification...")
            # Import validator only when needed (already imported in pre-install)
            if 'ClientInstallValidator' not in locals():
                sys.path.insert(0, str(Path(__file__).parent / "src"))
                from claude_code_hooks_daemon.install import ClientInstallValidator

            validation_result = ClientInstallValidator.validate_post_install(project_root)

            # Display warnings
            for warning in validation_result.warnings:
                print(f"⚠️  {warning}")

            # Display errors and fail if any
            if not validation_result.passed:
                print(f"\n❌ Post-installation validation failed with {len(validation_result.errors)} error(s):\n")
                for error in validation_result.errors:
                    print(f"❌ {error}\n")
                print("\n⚠️  Installation files were created but validation failed.")
                print("This may indicate a bug in the installer. Please file a bug report.")
                return 1

            print("✅ Post-installation verification passed")

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
        print("\n📚 Installation Summary:")
        print("Files Created by Installer:")
        print("   • .claude/init.sh - Daemon lifecycle functions")
        print("   • .claude/hooks/* - Forwarder scripts (route to daemon)")
        print("   • .claude/settings.json - Hook registration")
        print("   • .claude/hooks-daemon.yaml - Handler configuration")
        print("\nFiles Verified (Created Manually):")
        print("   • .claude/.gitignore - Git exclusion patterns")
        print("\n⚠️  Remember to commit .claude/ files (except hooks-daemon/) to git!")
        return 0
    else:
        print("\n❌ Installation failed - some files missing")
        return 1


if __name__ == "__main__":
    sys.exit(main())
