"""Integration tests for scripts/venv-include.bash's `_resolve_venv_dir()`.

Plan 00099 Phase 3 laid out the precedence; Plan 00100 Phase 2 collapsed it
into a single Python SSOT at src/claude_code_hooks_daemon/daemon/paths.py.
venv-include.bash is now a thin wrapper that shells out to that SSOT; the
tests below exercise the combined behaviour:

  1. $HOOKS_DAEMON_VENV_PATH        — explicit override
  2. untracked/venv-{fingerprint}/  — fingerprint-keyed (when present)
  3. untracked/venv-*/              — scan for any existing venv
  4. untracked/venv/                — legacy fallback (pre-v3.7.0)

Tests source the file in an isolated PROJECT_ROOT so we can control which
paths exist.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VENV_INCLUDE = REPO_ROOT / "scripts" / "venv-include.bash"
PATHS_SSOT = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"
CANONICAL_LIB = REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh"
PYTHON_DISCOVERY_LIB = REPO_ROOT / "scripts" / "lib" / "python_discovery.sh"
FINGERPRINT_HELPER = REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"


def _run(project_root: Path, env_overrides: dict[str, str] | None = None) -> str:
    """Source venv-include.bash from a fake project root and print VENV_DIR.

    ``HOOKS_DAEMON_PYTHON`` is pinned to the running interpreter (the
    resolver's own first-precedence override, resolve_venv.sh step 1). The
    fingerprint assertions below compare the resolver's answer against
    ``python_venv_fingerprint()`` computed IN THIS PROCESS, so both sides have
    to be talking about the same interpreter. Left unset, the resolver runs
    glob-and-sort discovery and picks the newest ``python3.X`` on the box —
    which on a CI runner with Python 3.11 from the tool cache and 3.12 in
    ``/usr`` is a DIFFERENT interpreter, and the comparison then fails on a
    fingerprint that was correct for the interpreter it described (Plan 00245).

    Callers can still override it: ``env_overrides`` is applied afterwards.
    """
    fake_script = project_root / "scripts" / "venv-include.bash"
    env = os.environ.copy()
    env["HOOKS_DAEMON_PYTHON"] = sys.executable
    if env_overrides:
        env.update(env_overrides)
    if not env_overrides or "HOOKS_DAEMON_VENV_PATH" not in env_overrides:
        env.pop("HOOKS_DAEMON_VENV_PATH", None)
    result = subprocess.run(
        ["bash", "-c", f'source "{fake_script}" > /dev/null 2>&1 && echo "$VENV_DIR"'],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


def _setup_fake_project(tmp_path: Path, include_fp_helper: bool = True) -> Path:
    """Create a minimal project directory layout that venv-include.bash expects.

    Plan 00100 Phase 2: ``include_fp_helper`` now controls whether the Python
    SSOT (paths.py) is linked. The name is kept for test-history continuity;
    the concept has moved from a bash helper to the SSOT script.
    """
    project = tmp_path / "project"
    (project / "scripts" / "install").mkdir(parents=True)
    # venv-include.bash computes PROJECT_ROOT as parent of its own directory,
    # so the sourced script must live at {project}/scripts/venv-include.bash
    (project / "scripts" / "venv-include.bash").symlink_to(VENV_INCLUDE)
    # Plan 00104 Phase 5 Task 5.5: venv-include.bash now sources the
    # canonical bash library at scripts/lib/resolve_venv.sh.
    lib_dir = project / "scripts" / "lib"
    lib_dir.mkdir(parents=True)
    (lib_dir / "resolve_venv.sh").symlink_to(CANONICAL_LIB)
    # Plan 00110 Phase 4: resolve_venv.sh sources scripts/lib/python_discovery.sh
    # at runtime to drive glob-and-sort interpreter discovery. The helper is
    # part of the installed surface and must be linked into every fake project.
    (lib_dir / "python_discovery.sh").symlink_to(PYTHON_DISCOVERY_LIB)
    if include_fp_helper:
        ssot_parent = project / "src" / "claude_code_hooks_daemon" / "daemon"
        ssot_parent.mkdir(parents=True)
        (ssot_parent / "paths.py").symlink_to(PATHS_SSOT)
    return project


def _fake_venv(path: Path) -> None:
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python3").symlink_to(sys.executable)


class TestExplicitOverride:
    def test_explicit_override_wins_over_everything(self, tmp_path: Path) -> None:
        project = _setup_fake_project(tmp_path)
        override = tmp_path / "explicit-venv"
        _fake_venv(override)
        # Also create legacy + keyed venvs — override must still win
        _fake_venv(project / "untracked" / "venv")

        result = _run(project, env_overrides={"HOOKS_DAEMON_VENV_PATH": str(override)})
        assert result == str(override)


class TestFingerprintKeyed:
    def test_fingerprint_keyed_wins_over_legacy(self, tmp_path: Path) -> None:
        project = _setup_fake_project(tmp_path)
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        fp = python_venv_fingerprint()
        keyed = project / "untracked" / f"venv-{fp}"
        _fake_venv(keyed)
        # Legacy venv also present — must NOT be chosen
        _fake_venv(project / "untracked" / "venv")

        result = _run(project)
        assert result == str(keyed)

    def test_fingerprint_keyed_preferred_for_creation_when_no_legacy(self, tmp_path: Path) -> None:
        """If neither fingerprint nor legacy venv exists, prefer keyed path.

        ``python_venv_fingerprint(project)`` prepends the project-path slug
        (Task 3.0.5) so host-vs-container views of the same interpreter get
        distinct venv directories.
        """
        project = _setup_fake_project(tmp_path)
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        fp = python_venv_fingerprint(project)
        expected = project / "untracked" / f"venv-{fp}"

        result = _run(project)
        assert result == str(expected)

    def test_the_resolved_key_follows_the_pinned_interpreter(self, tmp_path: Path) -> None:
        """The keyed path is a function of the interpreter, not of discovery.

        Guard for the premise ``_run`` sets. The two assertions above compare
        the resolver against a fingerprint computed in THIS process, so they
        only mean something while the resolver is looking at this process's
        interpreter. Drop the ``HOOKS_DAEMON_PYTHON`` pin and they keep passing
        on any box with a single Python while failing on any box with two — the
        precise way this file was broken in CI and green locally for 25 pushes.

        Here the resolver is pointed at a NAMED interpreter and its answer must
        match the fingerprint that interpreter yields, so the pin cannot be
        removed without a local failure.
        """
        pinned = Path("/usr/bin/python3")
        if not pinned.exists():
            pytest.skip(f"{pinned} unavailable in this environment")

        project = _setup_fake_project(tmp_path)
        fingerprint = subprocess.run(
            [
                "bash",
                "-c",
                f'source "{FINGERPRINT_HELPER}" && '
                f'python_venv_fingerprint "{pinned}" "{project}"',
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

        result = _run(project, env_overrides={"HOOKS_DAEMON_PYTHON": str(pinned)})
        assert result == str(project / "untracked" / f"venv-{fingerprint}"), (
            f"resolver ignored HOOKS_DAEMON_PYTHON={pinned}: "
            f"expected key venv-{fingerprint}, got {result}"
        )


class TestLegacyFallback:
    def test_missing_paths_py_exits_nonzero_with_reinstall_directive(self, tmp_path: Path) -> None:
        """``paths.py`` SSOT missing → non-zero exit + clear stderr.

        Plan 00103 Decision 2: when the SSOT is unreachable the resolver
        must fail loudly. The previous behaviour silently fell back to the
        unversioned ``${PROJECT_ROOT}/untracked/venv`` path that v3.7.0
        retired, so callers got a confusing "venv not found" instead of
        the actionable "reinstall the daemon".
        """
        project = _setup_fake_project(tmp_path, include_fp_helper=False)
        fake_script = project / "scripts" / "venv-include.bash"

        env = os.environ.copy()
        env.pop("HOOKS_DAEMON_VENV_PATH", None)
        result = subprocess.run(
            ["bash", "-c", f'source "{fake_script}" && echo "$VENV_DIR"'],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        assert result.returncode != 0, (
            "venv-include.bash must exit non-zero when paths.py is missing. "
            f"returncode={result.returncode}, stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )
        assert (
            "paths.py" in result.stderr or "SSOT" in result.stderr
        ), f"stderr must reference the missing SSOT. Got stderr=\n{result.stderr}"
        # The unversioned legacy path must NEVER be emitted to stdout.
        assert f"{project}/untracked/venv\n" not in result.stdout, (
            "Resolver must not silently emit the unversioned legacy path. "
            f"Got stdout={result.stdout!r}"
        )

    def test_falls_back_to_legacy_when_legacy_exists_and_keyed_does_not(
        self, tmp_path: Path
    ) -> None:
        """Pre-v3.7.0 installs have untracked/venv/ but no keyed venv yet.

        This is the SSOT's own legacy precedence (paths.py is present and
        returns the legacy path because that is where a venv actually
        lives). It must keep working — Plan 00103 only forbids silent
        fallback when the SSOT itself can't be invoked.
        """
        project = _setup_fake_project(tmp_path)
        _fake_venv(project / "untracked" / "venv")

        result = _run(project)
        assert result == str(project / "untracked" / "venv")
