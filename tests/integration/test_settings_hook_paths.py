"""Integration tests for .claude/settings.json hook path configuration.

This test ensures hook paths use $CLAUDE_PROJECT_DIR to be robust against
CWD changes during Bash tool calls.
"""

import json
from pathlib import Path


def test_hook_paths_use_project_dir_variable():
    """Verify all hook paths use $CLAUDE_PROJECT_DIR for CWD robustness.

    Bug: Hook paths configured as ".claude/hooks/pre-tool-use" break when
    Bash tool calls change CWD away from project root.

    Fix: All hook paths must use "$CLAUDE_PROJECT_DIR"/.claude/hooks/*
    to be robust against CWD changes.
    """
    settings_file = Path(__file__).parent.parent.parent / ".claude" / "settings.json"
    assert settings_file.exists(), "settings.json not found"

    with open(settings_file) as f:
        settings = json.load(f)

    # Check statusLine command uses $CLAUDE_PROJECT_DIR
    if "statusLine" in settings and "command" in settings["statusLine"]:
        status_cmd = settings["statusLine"]["command"]
        assert (
            "$CLAUDE_PROJECT_DIR" in status_cmd
        ), f"statusLine command must use $CLAUDE_PROJECT_DIR, got: {status_cmd}"

    # Check all hook event commands use $CLAUDE_PROJECT_DIR
    if "hooks" in settings:
        for event_name, hook_configs in settings["hooks"].items():
            for hook_config in hook_configs:
                if "hooks" in hook_config:
                    for hook in hook_config["hooks"]:
                        if hook.get("type") == "command":
                            cmd = hook["command"]
                            assert "$CLAUDE_PROJECT_DIR" in cmd, (
                                f"{event_name} hook command must use $CLAUDE_PROJECT_DIR, "
                                f"got: {cmd}"
                            )


def test_hook_paths_point_to_claude_hooks_directory():
    """Verify hook paths point to .claude/hooks/ directory."""
    settings_file = Path(__file__).parent.parent.parent / ".claude" / "settings.json"

    with open(settings_file) as f:
        settings = json.load(f)

    # Check statusLine
    if "statusLine" in settings and "command" in settings["statusLine"]:
        status_cmd = settings["statusLine"]["command"]
        assert (
            ".claude/hooks/" in status_cmd
        ), f"statusLine should reference .claude/hooks/, got: {status_cmd}"

    # Check hook events
    if "hooks" in settings:
        for event_name, hook_configs in settings["hooks"].items():
            for hook_config in hook_configs:
                if "hooks" in hook_config:
                    for hook in hook_config["hooks"]:
                        if hook.get("type") == "command":
                            cmd = hook["command"]
                            assert ".claude/hooks/" in cmd, (
                                f"{event_name} hook should reference .claude/hooks/, " f"got: {cmd}"
                            )


def test_every_command_including_status_line_is_bash_invoked():
    """Plan 00102 Phase 6: the exec bit must be irrelevant for EVERY command.

    The two tests above check `$CLAUDE_PROJECT_DIR` and `.claude/hooks/`, and
    both pass whether or not the command is invoked through `bash`. That gap
    is why the tracked statusLine stayed bare through all of Plan 00102 Tier 1
    while every event hook was migrated: the one test that looked at the
    statusLine command could not see the property that mattered.
    """
    settings_file = Path(__file__).parent.parent.parent / ".claude" / "settings.json"
    with open(settings_file) as f:
        settings = json.load(f)

    commands = {"statusLine": settings["statusLine"]["command"]}
    for event_name, hook_configs in settings["hooks"].items():
        for hook_config in hook_configs:
            for hook in hook_config.get("hooks", []):
                if hook.get("type") == "command" and "command" in hook:
                    commands[event_name] = hook["command"]

    bare = {name: cmd for name, cmd in commands.items() if not cmd.startswith("bash ")}
    assert not bare, (
        "every settings.json command must be invoked via `bash <path>` so a "
        f"dropped exec bit cannot break it — bare: {bare!r}"
    )
