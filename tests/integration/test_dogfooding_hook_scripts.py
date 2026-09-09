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

import difflib
import tempfile
from pathlib import Path

import pytest

from claude_code_hooks_daemon.install.forwarder_generator import (
    recorded_project_root,
    recorded_untracked_dir,
    unexpected_absolute_paths,
)


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
    # Generate for the roots the DEPLOYED forwarders record, not this
    # checkout's. Comparing against a regeneration at the current root
    # additionally asserts "this checkout sits where the committed file's did"
    # — false on every machine but the one that generated them (Plan 00250
    # Task 2.4c), and false in every worktree of it.
    installed = get_installed_hook_scripts()
    untracked_dir = recorded_untracked_dir(installed) or (
        get_event_socket_dir(project_root).parent
    )
    # The guard bakes the checkout too (Plan 00364 Task 5.1), so it is read
    # back for the same reason and from the same artefact.
    guard_root = recorded_project_root(installed) or project_root

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
                plain_content, hook_name, transport, untracked_dir, guard_root
            )

        # Generate status-line script. regenerate_deployed_hooks transforms
        # EVERY file under .claude/hooks/ (it iterates the directory, not the
        # wired-event map), so status-line gets the same transport transform
        # as every other forwarder.
        create_status_line_script(tmp_hooks_dir)
        plain_status_line = (tmp_hooks_dir / "status-line").read_text()
        scripts["status-line"] = generate_forwarder_content(
            plain_status_line, "status-line", transport, untracked_dir, guard_root
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

        The comparison is EXACT, and stays exact by generating for the root the
        deployed forwarders record rather than for this checkout's. The
        forwarders bake that root as a literal on purpose — the relay guard is a
        zero-spawn hot path that must not compute a path at hook-run time — so
        comparing against a regeneration at the CURRENT root additionally
        asserted "this checkout sits where the committed file's did". True on
        one box, false on every CI runner, and none of the three properties
        above (Plan 00250 Task 2.4c). See `recorded_untracked_dir`, which
        refuses to pick a root when the forwarders disagree about it.
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

            # A mismatch that only names the file leaves regenerating blindly as
            # the cheapest response — which is the drift this test exists to
            # catch. Show which lines differ.
            for script_name in mismatches:
                error_msg.append(f"\n  {script_name}:")
                diff = difflib.unified_diff(
                    installed[script_name].splitlines(),
                    fresh[script_name].splitlines(),
                    fromfile=f"installed/{script_name}",
                    tofile=f"installer-output/{script_name}",
                    lineterm="",
                    n=1,
                )
                for line in list(diff)[:40]:
                    error_msg.append(f"\n    {line}")

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

    def test_no_other_machine_specific_path_survives(self):
        """The comparison above must not hide a SECOND baked path.

        The forwarders bake one machine-specific thing on purpose: the
        untracked directory the relay guard needs. If a future change bakes
        another absolute path, the comparison would treat it as template — so
        it is asserted here instead, over the tracked files themselves.

        The roots are DECLARED rather than assumed to be this checkout's. The
        artefact records where it was generated, which is only the live
        checkout on the machine that generated it — judging against the live
        root alone reported every legitimately baked path as an offender on
        every CI runner, which is the same defect Task 2.4c fixed in the
        comparison this guards.
        """
        installed = get_installed_hook_scripts()
        baked_roots = [str(get_project_root())]
        for recorded in (recorded_untracked_dir(installed), recorded_project_root(installed)):
            if recorded is not None:
                baked_roots.append(str(recorded))

        offenders = {
            name: unexpected
            for name, content in installed.items()
            if (unexpected := unexpected_absolute_paths(content, baked_roots))
        }

        assert not offenders, (
            "a tracked hook script names an absolute path that is neither a "
            f"baked root ({baked_roots}) nor a portable system path, so it is "
            "machine-specific content the dogfooding comparison would compare "
            f"away rather than catch:\n{offenders}"
        )

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
