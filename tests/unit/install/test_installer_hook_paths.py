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


def test_create_settings_json_invokes_hooks_via_bash(tmp_path):
    """Hook command strings must invoke the wrapper through `bash`, not directly.

    Plan 00102 Tier 1: invoking the wrapper as `bash <abs-path>` makes the
    file's executable bit irrelevant — `bash` reads the script as data, the
    kernel never has to honour `+x`. This eliminates an entire class of
    silent breakage (core.fileMode=false, Windows clones, tarball transfers,
    IDE-save mode loss, `cp` without `-p`).

    Every command MUST start with `bash `. statusLine is covered by its own
    test below rather than exempted — see Phase 6 for why the original
    exemption was wrong.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    from install import create_settings_json

    project_root = tmp_path
    (project_root / ".claude").mkdir()
    create_settings_json(project_root, force=True)

    with open(project_root / ".claude" / "settings.json") as f:
        settings = json.load(f)

    for event_name, hook_configs in settings["hooks"].items():
        for hook_config in hook_configs:
            for hook in hook_config["hooks"]:
                if hook["type"] != "command":
                    continue
                cmd = hook["command"]
                assert cmd.startswith("bash "), (
                    f"{event_name} hook command must invoke wrapper via `bash` "
                    f"so the exec bit is irrelevant — got: {cmd!r}"
                )
                assert "/.claude/hooks/" in cmd, (
                    f"{event_name} hook command must still reference "
                    f".claude/hooks/, got: {cmd!r}"
                )


def test_create_settings_json_invokes_status_line_via_bash(tmp_path):
    """The status line is a shell command too, so it gets the same treatment.

    Plan 00102 Phase 6. Phase 1 left this one command bare and recorded the
    omission as deliberate — "exempt by Claude Code design". That rationale is
    absent from the plan's TRIAGE.md and all four brainstorm reports, and it
    is wrong: Claude Code documents `statusLine` as running "any shell script
    you configure", `type: "command"` as meaning "run this shell command", and
    its own Windows example uses the same interpreter-plus-path shape
    (`powershell -NoProfile -File <path>`).

    The decisive evidence is local. The command Phase 1 left in place is
    `"$CLAUDE_PROJECT_DIR"/.claude/hooks/status-line`, which names no file on
    disk — the quotes and the variable are literal bytes — so a direct
    `execve` would fail with ENOENT. It works, therefore a shell expands it,
    therefore `bash <path>` works too and the exec bit need not be honoured.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    from install import create_settings_json

    project_root = tmp_path
    (project_root / ".claude").mkdir()
    create_settings_json(project_root, force=True)

    with open(project_root / ".claude" / "settings.json") as f:
        settings = json.load(f)

    command = settings["statusLine"]["command"]
    assert command.startswith("bash "), (
        "statusLine command must invoke the wrapper via `bash` so the exec "
        f"bit is irrelevant — got: {command!r}"
    )
    assert command.endswith(
        "/.claude/hooks/status-line"
    ), f"statusLine command must still reference the wrapper, got: {command!r}"


def test_status_line_command_matches_the_hook_command_template(tmp_path):
    """statusLine and the event hooks must render through the SAME helper.

    Asserting only "starts with bash" would let the two drift again — a
    hand-written statusLine string that happens to start with `bash ` passes
    that check while diverging in quoting or path form. Comparing against the
    installer's own `_hook_cmd` output pins them to one implementation.
    """
    import sys

    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
    from install import create_settings_json

    project_root = tmp_path
    (project_root / ".claude").mkdir()
    create_settings_json(project_root, force=True)

    with open(project_root / ".claude" / "settings.json") as f:
        settings = json.load(f)

    a_hook_command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    expected = a_hook_command.replace("/pre-tool-use", "/status-line")
    assert settings["statusLine"]["command"] == expected
