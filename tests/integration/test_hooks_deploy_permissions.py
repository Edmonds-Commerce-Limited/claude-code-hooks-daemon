"""Integration tests for ``set_hook_permissions`` (Issue #29).

Contract: ``set_hook_permissions`` must:

- Set every hook file to 0o755 regardless of its previous mode
- Return non-zero if any chmod call fails (no silent error-suppression)
- Succeed when all files are writeable

Also verifies that ``deploy_all_hooks`` invokes ``set_hook_permissions`` in
self-install mode, not just normal mode — a fresh self-install upgrade that
rewrites wrappers must still end with executable files.

See GitHub issue #29 for the original symptom: all 11 wrappers bulk-rewritten
with lost exec bit after an installer/upgrade run.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DEPLOY_SH = REPO_ROOT / "scripts" / "install" / "hooks_deploy.sh"


#: A deliberately restrictive umask, applied so the deployed mode is asserted
#: against a HOSTILE environment rather than against whatever the developer or
#: CI runner happens to have. Under `chmod +x` this mask is what turned 0755
#: into 0744; under an explicit mode it must have no effect at all.
_HOSTILE_UMASK = "077"


def _run_bash(script: str, umask: str | None = None) -> subprocess.CompletedProcess[str]:
    umask_line = f"umask {umask}" if umask else ""
    wrapper = f"""
set -euo pipefail
{umask_line}
source "{HOOKS_DEPLOY_SH}"
{script}
"""
    return subprocess.run(
        ["bash", "-c", wrapper],
        capture_output=True,
        text=True,
    )


def _seed_non_executable_wrapper(hooks_dir: Path, name: str) -> Path:
    hooks_dir.mkdir(parents=True, exist_ok=True)
    wrapper = hooks_dir / name
    wrapper.write_text("#!/bin/bash\necho hi\n")
    wrapper.chmod(0o644)
    return wrapper


class TestSetHookPermissionsRestoresExecBit:
    """Positive case: set_hook_permissions must make wrappers executable."""

    def test_non_executable_wrapper_becomes_executable(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        hooks_dir = project_root / ".claude" / "hooks"
        wrapper = _seed_non_executable_wrapper(hooks_dir, "pre-tool-use")

        result = _run_bash(f'set_hook_permissions "{project_root}"')

        assert result.returncode == 0, f"stderr={result.stderr!r}"
        mode = wrapper.stat().st_mode & 0o777
        assert mode == 0o755, f"expected 0o755, got {oct(mode)}"

    def test_mode_is_0755_even_under_a_restrictive_umask(self, tmp_path: Path) -> None:
        """The deployed mode belongs to the installer, not to the caller.

        Without this, the suite only caught the umask bug on machines that
        happened to have a restrictive umask -- so it passed on the common
        022 desktop and failed in hardened images and many containers, which
        reads as a broken test rather than a broken installer.

        The consequence is real once the installing user is not the user
        running Claude Code (root installs, user runs; a host/container pair
        over a bind mount): at 0744 the wrappers are silently non-executable
        and hooks stop firing with no error.
        """
        project_root = tmp_path / "project"
        hooks_dir = project_root / ".claude" / "hooks"
        wrapper = _seed_non_executable_wrapper(hooks_dir, "pre-tool-use")

        result = _run_bash(f'set_hook_permissions "{project_root}"', umask=_HOSTILE_UMASK)

        assert result.returncode == 0, f"stderr={result.stderr!r}"
        mode = wrapper.stat().st_mode & 0o777
        assert mode == 0o755, (
            f"expected 0o755 under umask {_HOSTILE_UMASK}, got {oct(mode)} — "
            f"the chmod is being masked by the caller's umask"
        )


class TestSetHookPermissionsFailsLoudly:
    """A genuine chmod failure must NOT be silenced.

    We simulate a chmod failure by pointing the function at a read-only
    hooks directory owned by another user. If run as root we can still
    chmod, so we skip that scenario — the assertion instead targets the
    less extreme but sufficient contract: the function must not contain
    ``2>/dev/null || true`` style silent suppression.
    """

    def test_source_does_not_silence_chmod(self) -> None:
        source = HOOKS_DEPLOY_SH.read_text()
        # Grab the body of set_hook_permissions by crude lexical split —
        # the function ends at the next top-level `}` followed by blank+`#`.
        start = source.index("set_hook_permissions()")
        rest = source[start:]
        body_end = rest.index("\n}\n")
        body = rest[: body_end + 2]

        chmod_lines = [line for line in body.splitlines() if "chmod " in line]
        assert chmod_lines, "precondition: function still calls chmod"

        # Assert on the PROPERTY, not on one spelling of the call. This block
        # previously pinned the literal `chmod +x`, so it failed the moment the
        # call was corrected to an explicit mode -- a guard that breaks when
        # unrelated wording changes trains people to loosen it.
        for line in chmod_lines:
            assert (
                "2>/dev/null" not in line
            ), f"chmod stderr must not be redirected to /dev/null: {line.strip()}"
            assert (
                "|| true" not in line
            ), f"chmod failures must not be swallowed -- see issue #29: {line.strip()}"

        # Deliberately NOT asserting the absence of a `chmod +x` spelling here.
        # That was tried and immediately fired on the source COMMENT explaining
        # why the spelling was wrong -- a lexical guard cannot tell code from
        # the prose describing it. The umask property is covered behaviourally
        # by test_mode_is_0755_even_under_a_restrictive_umask, which cannot be
        # fooled that way.


class TestDeployAllHooksSetsPermsInSelfInstall:
    """deploy_all_hooks must run set_hook_permissions in BOTH modes.

    Before the fix, self-install mode skipped permission setup entirely,
    so any path that rewrote wrappers (e.g. git checkout in upgrade.sh)
    could leave them non-executable with no remediation.
    """

    def test_self_install_mode_still_sets_permissions(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        daemon_dir = project_root  # self-install: daemon_dir == project_root
        hooks_dir = project_root / ".claude" / "hooks"
        wrapper = _seed_non_executable_wrapper(hooks_dir, "pre-tool-use")

        # Also seed an init.sh so deploy_init_script succeeds trivially.
        init_src = project_root / "init.sh"
        init_src.write_text("#!/bin/bash\n")
        init_src.chmod(0o755)

        script = textwrap.dedent(f"""\
            deploy_all_hooks "{project_root}" "{daemon_dir}" "self-install" \
                >/tmp/deploy_all_hooks_out.txt 2>&1 || true
            # Regardless of downstream steps, after the call the wrapper
            # should be executable if set_hook_permissions ran.
            """)
        result = _run_bash(script)
        assert result.returncode == 0, f"stderr={result.stderr!r}"

        mode = wrapper.stat().st_mode & 0o777
        assert mode == 0o755, (
            f"expected self-install deploy_all_hooks to chmod wrapper to 0o755; " f"got {oct(mode)}"
        )


class TestEnsureEchdCaptureExecutable:
    """Dogfooding bug fix: the echd-capture helper recommended by pipe_blocker
    must be made executable during install/upgrade regardless of how the
    exec bit travelled (e.g. a client checkout with core.fileMode=false).
    """

    def _seed_helper(self, daemon_dir: Path, executable: bool) -> Path:
        helper_dir = daemon_dir / "scripts"
        helper_dir.mkdir(parents=True, exist_ok=True)
        helper = helper_dir / "echd-capture"
        helper.write_text("#!/bin/bash\necho fake\n")
        helper.chmod(0o755 if executable else 0o644)
        return helper

    def test_makes_non_executable_helper_executable(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        helper = self._seed_helper(daemon_dir, executable=False)

        result = _run_bash(f'ensure_echd_capture_executable "{daemon_dir}"')

        assert result.returncode == 0, f"stderr={result.stderr!r}"
        mode = helper.stat().st_mode & 0o777
        assert mode == 0o755, f"expected 0o755, got {oct(mode)}"

    def test_missing_helper_is_non_fatal(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon-without-helper"
        daemon_dir.mkdir(parents=True)

        result = _run_bash(f'ensure_echd_capture_executable "{daemon_dir}"')

        assert result.returncode == 0, f"stderr={result.stderr!r}"

    def test_deploy_all_hooks_ensures_echd_capture_executable(self, tmp_path: Path) -> None:
        """deploy_all_hooks must invoke ensure_echd_capture_executable so the
        helper is fixed up as part of the standard install/upgrade path."""
        project_root = tmp_path / "project"
        daemon_dir = project_root  # self-install: daemon_dir == project_root
        hooks_dir = project_root / ".claude" / "hooks"
        wrapper = hooks_dir / "pre-tool-use"
        hooks_dir.mkdir(parents=True)
        wrapper.write_text("#!/bin/bash\necho hi\n")
        wrapper.chmod(0o644)

        init_src = project_root / "init.sh"
        init_src.write_text("#!/bin/bash\n")
        init_src.chmod(0o755)

        helper = self._seed_helper(daemon_dir, executable=False)

        script = textwrap.dedent(f"""\
            deploy_all_hooks "{project_root}" "{daemon_dir}" "self-install" \
                >/tmp/deploy_all_hooks_echd_out.txt 2>&1 || true
            """)
        result = _run_bash(script)
        assert result.returncode == 0, f"stderr={result.stderr!r}"

        mode = helper.stat().st_mode & 0o777
        assert mode == 0o755, f"expected deploy_all_hooks to chmod helper to 0o755; got {oct(mode)}"


class TestGitIndexForceExecutableNoRegression:
    """Positive smoke test: git_force_executable still runs silently outside a repo.

    Covers the case where a user runs the installer in a non-git working
    directory — it must not error out.
    """

    def test_silent_noop_outside_git_repo(self, tmp_path: Path) -> None:
        project_root = tmp_path / "not-a-repo"
        project_root.mkdir()
        result = _run_bash(f'git_force_executable "{project_root}"')
        assert result.returncode == 0, f"stderr={result.stderr!r}"


class TestSetHookPermissionsSkipsNonHookFiles:
    """Issue #4: the installer must only chmod its own hook entrypoints, not
    pre-existing non-hook files (docs, another project's hooks) that happen to
    sit in .claude/hooks/. Marking docs executable is cosmetic git noise that
    re-fires on every reinstall/upgrade.
    """

    def test_does_not_chmod_markdown_docs(self, tmp_path: Path) -> None:
        project_root = tmp_path / "project"
        hooks_dir = project_root / ".claude" / "hooks"
        # A canonical hook the installer owns
        wrapper = _seed_non_executable_wrapper(hooks_dir, "pre-tool-use")
        # Pre-existing non-hook docs from an unrelated deployment
        doc = hooks_dir / "CLAUDE.md"
        doc.write_text("# not a script\n")
        doc.chmod(0o644)
        readme = hooks_dir / "README.md"
        readme.write_text("# readme\n")
        readme.chmod(0o644)

        result = _run_bash(f'set_hook_permissions "{project_root}"')
        assert result.returncode == 0, f"stderr={result.stderr!r}"

        # The real hook became executable ...
        assert (wrapper.stat().st_mode & 0o777) == 0o755
        # ... but the docs were left untouched.
        assert (doc.stat().st_mode & 0o777) == 0o644, "CLAUDE.md must not be chmod +x"
        assert (readme.stat().st_mode & 0o777) == 0o644, "README.md must not be chmod +x"


class TestGitForceExecutableSkipsNonHookFiles:
    """Issue #4: git_force_executable must only force the exec bit on its own
    hook entrypoints in the git index, not pre-existing docs sitting alongside.
    """

    def test_does_not_force_executable_on_markdown(self, tmp_path: Path) -> None:
        project_root = tmp_path / "repo"
        hooks_dir = project_root / ".claude" / "hooks"
        hooks_dir.mkdir(parents=True)
        wrapper = hooks_dir / "pre-tool-use"
        wrapper.write_text("#!/bin/bash\necho hi\n")
        wrapper.chmod(0o644)
        doc = hooks_dir / "CLAUDE.md"
        doc.write_text("# doc\n")
        doc.chmod(0o644)

        subprocess.run(["git", "init", "-q", str(project_root)], check=True)
        subprocess.run(["git", "-C", str(project_root), "add", "-A"], check=True)

        result = _run_bash(f'git_force_executable "{project_root}"')
        assert result.returncode == 0, f"stderr={result.stderr!r}"

        ls = subprocess.run(
            [
                "git",
                "-C",
                str(project_root),
                "ls-files",
                "-s",
                ".claude/hooks/pre-tool-use",
                ".claude/hooks/CLAUDE.md",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        modes = {line.split("\t")[1]: line.split()[0] for line in ls.stdout.splitlines()}
        assert modes[".claude/hooks/pre-tool-use"] == "100755", "hook must be forced executable"
        assert modes[".claude/hooks/CLAUDE.md"] == "100644", "doc must NOT be forced executable"
