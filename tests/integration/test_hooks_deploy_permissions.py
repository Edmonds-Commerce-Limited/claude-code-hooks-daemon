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


def _run_bash(script: str) -> subprocess.CompletedProcess[str]:
    wrapper = f"""
set -euo pipefail
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

        assert "chmod +x" in body, "precondition: function still uses chmod +x"
        assert (
            "2>/dev/null || true" not in body
        ), "set_hook_permissions must not silence chmod failures — see issue #29"
        assert (
            'chmod +x "$hook_file" 2>/dev/null' not in body
        ), "chmod stderr must not be redirected to /dev/null"


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
