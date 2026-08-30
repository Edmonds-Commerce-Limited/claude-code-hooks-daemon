"""Integration test for dogfooding: Ensure hook scripts match installer output.

This test verifies that the .claude/hooks/* scripts in the project are EXACTLY
as they would be if freshly created by the installer. This ensures:
1. The installer creates correct scripts
2. Manual edits to scripts are detected
3. Script updates are propagated to the installer

CRITICAL: If this test fails, either:
- The installer needs updating (install.py)
- Or the hook scripts need regenerating
"""

import tempfile
from pathlib import Path

import pytest


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent.parent


def get_installed_hook_scripts() -> dict[str, str]:
    """Get current hook scripts from .claude/hooks/.

    Returns:
        Dict mapping hook filename to file content
    """
    hooks_dir = get_project_root() / ".claude" / "hooks"
    scripts = {}

    # All hook script files (not directories)
    for hook_file in hooks_dir.iterdir():
        if hook_file.is_file() and not hook_file.name.endswith(".bak"):
            scripts[hook_file.name] = hook_file.read_text()

    return scripts


def generate_fresh_hook_scripts() -> dict[str, str]:
    """Generate fresh hook scripts using installer logic.

    Plan 00290: the installer's ``create_forwarder_script`` only ever writes
    the plain (relay-disabled) template — the relay/nc rungs are applied as a
    SEPARATE post-deploy rewrite step (``forwarder_generator.regenerate_deployed_hooks``,
    invoked by ``scripts/install/hooks_deploy.sh`` after the plain copy). A
    project whose OWN ``daemon.transport`` config has opted into either rung
    (this repo dogfoods ``relay_enabled: true``) legitimately deploys forwarders
    that differ from the bare template by exactly that generated transform, so
    the comparison must apply the SAME transform this project's real deploy
    step would apply, using this project's actual resolved config — not the
    installer defaults.

    Returns:
        Dict mapping hook filename to expected content
    """
    # Import installer functions
    from install import create_forwarder_script, create_status_line_script

    from claude_code_hooks_daemon.daemon.paths import get_event_socket_dir
    from claude_code_hooks_daemon.install.forwarder_generator import (
        generate_forwarder_content,
        load_transport_config,
    )

    project_root = get_project_root()
    transport = load_transport_config(project_root)
    untracked_dir = get_event_socket_dir(project_root).parent

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_hooks_dir = Path(tmpdir) / "hooks"
        tmp_hooks_dir.mkdir()

        # Create all standard forwarder scripts. Derived from the wired-event
        # settings map (bash_key <- json_key) so this dogfooding check auto-covers
        # every event the daemon wires — including Plan 00170 events wired with no
        # built-in handler. StatusLine is excluded here (custom status-line script,
        # generated separately below).
        from claude_code_hooks_daemon.utils.hook_registration import HOOK_EVENTS_IN_SETTINGS

        daemon_hooks = {
            bash_key: json_key for json_key, bash_key in HOOK_EVENTS_IN_SETTINGS.items()
        }

        scripts = {}

        # Generate forwarder scripts, then apply this project's real transport
        # transform on top — exactly what the actual deploy pipeline does.
        for hook_name, event_name in daemon_hooks.items():
            create_forwarder_script(tmp_hooks_dir, hook_name, event_name)
            plain_content = (tmp_hooks_dir / hook_name).read_text()
            scripts[hook_name] = generate_forwarder_content(
                plain_content, hook_name, transport, untracked_dir
            )

        # Generate status-line script. regenerate_deployed_hooks transforms
        # EVERY file under .claude/hooks/ (it iterates the directory, not the
        # wired-event map), so status-line gets the same transport transform
        # as every other forwarder.
        create_status_line_script(tmp_hooks_dir)
        plain_status_line = (tmp_hooks_dir / "status-line").read_text()
        scripts["status-line"] = generate_forwarder_content(
            plain_status_line, "status-line", transport, untracked_dir
        )

        return scripts


class TestDogfoodingHookScripts:
    """Test that hook scripts match installer output exactly."""

    def test_hook_scripts_match_installer(self):
        """DOGFOODING: Hook scripts must match installer output exactly.

        This ensures:
        - Installer creates correct scripts
        - No manual edits have drifted from installer
        - Script updates are propagated to installer code
        """
        installed = get_installed_hook_scripts()
        fresh = generate_fresh_hook_scripts()

        # Check for missing or extra scripts
        installed_names = set(installed.keys())
        fresh_names = set(fresh.keys())

        missing = fresh_names - installed_names
        extra = installed_names - fresh_names

        if missing:
            pytest.fail(
                f"\n❌ Missing hook scripts (expected from installer):\n"
                f"  {', '.join(sorted(missing))}\n\n"
                f"Run install.py to create missing scripts."
            )

        if extra:
            pytest.fail(
                f"\n❌ Extra hook scripts (not created by installer):\n"
                f"  {', '.join(sorted(extra))}\n\n"
                f"Either remove these scripts or update installer to create them."
            )

        # Check content matches for each script
        mismatches = []
        for script_name in sorted(fresh_names):
            installed_content = installed[script_name]
            fresh_content = fresh[script_name]

            if installed_content != fresh_content:
                mismatches.append(script_name)

        if mismatches:
            error_msg = [
                "\n❌ DOGFOODING FAILURE: Hook scripts don't match installer output!",
                "\nMismatched scripts:",
            ]

            for script_name in mismatches:
                error_msg.append(f"\n  {script_name}:")
                error_msg.append("    Installed version differs from installer output")

            error_msg.extend(
                [
                    "\n\n🔧 ACTION REQUIRED:",
                    "1. Review changes in .claude/hooks/ scripts",
                    "2. If changes are correct: Update installer (install.py)",
                    "3. If changes are incorrect: Regenerate with install.py",
                    "\nTo regenerate: python install.py --force",
                ]
            )

            pytest.fail("".join(error_msg))

    def test_all_hook_scripts_are_executable(self):
        """All hook scripts must have executable permissions."""
        hooks_dir = get_project_root() / ".claude" / "hooks"

        non_executable = []
        for hook_file in hooks_dir.iterdir():
            if hook_file.is_file() and not hook_file.name.endswith(".bak"):
                # Check executable bit (owner execute permission)
                if not hook_file.stat().st_mode & 0o100:
                    non_executable.append(hook_file.name)

        if non_executable:
            pytest.fail(
                f"\n❌ Non-executable hook scripts:\n"
                f"  {', '.join(sorted(non_executable))}\n\n"
                f"Make executable: chmod +x .claude/hooks/{'{' + ','.join(non_executable) + '}' if len(non_executable) > 1 else non_executable[0]}"
            )
