"""Tests for install.py hook path generation.

Ensures the installer creates settings.json with CWD-robust hook paths.
"""

import json
from pathlib import Path


def test_create_settings_json_uses_project_dir_variable(tmp_path):
    """Verify installer creates settings.json with $CLAUDE_PROJECT_DIR paths.

    Bug: Installer generates relative paths like ".claude/hooks/pre-tool-use"
    which break when Bash tool calls change CWD.

    Fix: All hook paths must use "$CLAUDE_PROJECT_DIR"/.claude/hooks/*
    """
    # Import the installer function
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    from install import create_settings_json

    # Create settings.json in temp directory
    project_root = tmp_path
    (project_root / ".claude").mkdir()

    create_settings_json(project_root, force=True)

    # Read generated settings.json
    settings_file = project_root / ".claude" / "settings.json"
    assert settings_file.exists(), "settings.json should be created"

    with open(settings_file) as f:
        settings = json.load(f)

    # Check statusLine uses $CLAUDE_PROJECT_DIR
    assert "$CLAUDE_PROJECT_DIR" in settings["statusLine"]["command"], (
        f"statusLine must use $CLAUDE_PROJECT_DIR, " f"got: {settings['statusLine']['command']}"
    )

    # Check all hook events use $CLAUDE_PROJECT_DIR
    for event_name, hook_configs in settings["hooks"].items():
        for hook_config in hook_configs:
            for hook in hook_config["hooks"]:
                if hook["type"] == "command":
                    cmd = hook["command"]
                    assert (
                        "$CLAUDE_PROJECT_DIR" in cmd
                    ), f"{event_name} hook must use $CLAUDE_PROJECT_DIR, got: {cmd}"
