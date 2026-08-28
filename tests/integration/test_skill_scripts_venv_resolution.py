"""Integration tests for hooks-daemon skill script venv resolution.

Bug: v3.7.0 introduced fingerprint-keyed venvs (`untracked/venv-{fingerprint}/`)
but the three skill wrapper scripts in
`src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/` still hardcoded the
legacy `$DAEMON_DIR/untracked/venv/bin/python` path. On fresh v3.7.0+ installs
the legacy dir does not exist so every skill invocation (/hooks-daemon
status/health/etc.) died with 'Python venv not found'.

Fix: introduce a shared `_resolve-venv.sh` helper next to the wrappers that
implements the same precedence as init.sh's `_resolve_python_cmd()`:

  1. $HOOKS_DAEMON_VENV_PATH       — explicit override
  2. $DAEMON_DIR/untracked/venv-{fingerprint}/bin/python
  3. $DAEMON_DIR/untracked/venv/bin/python   — legacy fallback (pre-v3.7.0)

and have daemon-cli.sh, health-check.sh, init-handlers.sh source it instead of
hardcoding the legacy path.

Plan 00100 Phase 2: the resolver is now a thin wrapper around the Python
SSOT at $DAEMON_DIR/src/claude_code_hooks_daemon/daemon/paths.py. Tests
that previously linked python_fingerprint.sh now link paths.py — same
dependency-injection shape, different underlying helper.

These tests exercise the helper directly and also assert the three wrappers
actually source it (no hardcoded legacy path remains).
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_SCRIPTS_DIR = (
    REPO_ROOT / "src" / "claude_code_hooks_daemon" / "skills" / "hooks-daemon" / "scripts"
)
RESOLVER = SKILL_SCRIPTS_DIR / "_resolve-venv.sh"

WRAPPER_SCRIPTS = ("daemon-cli.sh", "health-check.sh", "init-handlers.sh")

RESOLVER_HARNESS = "set -euo pipefail\n" 'DAEMON_DIR="$1"\n' 'source "$2"\n' 'echo "$PYTHON"\n'


def _make_venv_skeleton(path: Path) -> None:
    """Create a fake venv that looks healthy enough (bin/python symlinks sys.executable)."""
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").symlink_to(sys.executable)


def _link_fingerprint_helper(daemon_dir: Path) -> None:
    """Symlink the Python SSOT (paths.py) into a fake DAEMON_DIR.

    The skill resolver now delegates to
    ``$DAEMON_DIR/src/claude_code_hooks_daemon/daemon/paths.py`` rather than
    re-implementing the precedence in bash. The name of this helper is kept
    for continuity with prior test history (the fingerprint logic now lives
    inside the Python SSOT, which we link here).
    """
    paths_parent = daemon_dir / "src" / "claude_code_hooks_daemon" / "daemon"
    paths_parent.mkdir(parents=True)
    (paths_parent / "paths.py").symlink_to(
        REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"
    )
    # Plan 00104 Phase 5 Task 5.4: skill _resolve-venv.sh now sources the
    # canonical library at $DAEMON_DIR/scripts/lib/resolve_venv.sh.
    lib_dir = daemon_dir / "scripts" / "lib"
    lib_dir.mkdir(parents=True)
    (lib_dir / "resolve_venv.sh").symlink_to(REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh")


def _run_resolver(daemon_dir: Path, env_overrides: dict[str, str] | None = None) -> str:
    env = os.environ.copy()
    env.pop("HOOKS_DAEMON_VENV_PATH", None)
    env["PATH"] = os.environ["PATH"]
    if env_overrides:
        env.update(env_overrides)
    result = subprocess.run(
        ["bash", "-c", RESOLVER_HARNESS, "_", str(daemon_dir), str(RESOLVER)],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


def _run_resolver_allow_fail(
    daemon_dir: Path, env_overrides: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Variant of _run_resolver that captures non-zero exits.

    Plan 00103 Decision 2 removes the silent legacy fallback. When resolution
    fails the script exits non-zero with a stderr directive instead of
    emitting a path. Tests that exercise the failure mode need to inspect
    returncode + stderr, not just stdout.
    """
    env = os.environ.copy()
    env.pop("HOOKS_DAEMON_VENV_PATH", None)
    env["PATH"] = os.environ["PATH"]
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["bash", "-c", RESOLVER_HARNESS, "_", str(daemon_dir), str(RESOLVER)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


class TestResolverExists:
    def test_resolver_script_is_shipped(self) -> None:
        assert RESOLVER.is_file(), (
            f"Expected shared resolver at {RESOLVER} so skill wrappers "
            "can share fingerprint-keyed venv resolution."
        )


class TestExplicitOverride:
    def test_hooks_daemon_venv_path_wins(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        _link_fingerprint_helper(daemon_dir)
        override = tmp_path / "explicit"
        _make_venv_skeleton(override)

        result = _run_resolver(daemon_dir, env_overrides={"HOOKS_DAEMON_VENV_PATH": str(override)})
        assert result == f"{override}/bin/python"


class TestFingerprintKeyed:
    def test_fingerprint_venv_wins_over_legacy(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        _link_fingerprint_helper(daemon_dir)

        fingerprint = python_venv_fingerprint()
        keyed_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"
        _make_venv_skeleton(keyed_venv)
        legacy_venv = daemon_dir / "untracked" / "venv"
        _make_venv_skeleton(legacy_venv)

        result = _run_resolver(daemon_dir)
        assert result == f"{keyed_venv}/bin/python"

    def test_fingerprint_venv_used_when_legacy_absent(self, tmp_path: Path) -> None:
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        _link_fingerprint_helper(daemon_dir)

        fingerprint = python_venv_fingerprint()
        keyed_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"
        _make_venv_skeleton(keyed_venv)

        result = _run_resolver(daemon_dir)
        assert result == f"{keyed_venv}/bin/python"


class TestNoVenvFailFast:
    """Plan 00103 Decision 2 — when resolution misses, the script must
    exit non-zero with a stderr directive. The previous behaviour silently
    fell back to the unversioned legacy ``$DAEMON_DIR/untracked/venv/bin/python``
    path (retired in v3.7.0), so callers got "venv not found" instead of the
    real "no venv exists, run /hooks-daemon install" directive.

    These tests replace the prior ``TestLegacyFallback`` class — the silent
    legacy fallback is the bug, not the contract.
    """

    def test_no_venv_exits_nonzero_with_install_directive(self, tmp_path: Path) -> None:
        """No venv at all → non-zero exit + clear "no usable venv found" stderr.

        Pre-fix: resolver silently emits ``$DAEMON_DIR/untracked/venv/bin/python``
        and exits 0. Post-fix: exit non-zero, stderr names the missing venv
        and points the operator at the install path.
        """
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        _link_fingerprint_helper(daemon_dir)

        result = _run_resolver_allow_fail(daemon_dir)

        assert result.returncode != 0, (
            "Resolver must exit non-zero when no venv exists. "
            f"Got returncode={result.returncode}, stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )
        assert (
            "no usable venv" in result.stderr.lower() or "no venv" in result.stderr.lower()
        ), f"stderr must contain a 'no venv' directive. Got stderr=\n{result.stderr}"
        # The unversioned legacy path must NEVER be emitted to stdout.
        assert f"{daemon_dir}/untracked/venv/bin/python" not in result.stdout, (
            "Resolver must not emit the unversioned legacy path. " f"Got stdout={result.stdout!r}"
        )

    def test_missing_paths_py_exits_nonzero_with_reinstall_directive(self, tmp_path: Path) -> None:
        """``paths.py`` SSOT missing → non-zero exit + clear stderr.

        Simulates a corrupt install (skill-bundle deploy that didn't copy
        paths.py). Pre-fix: silently fell back to legacy path. Post-fix:
        clear stderr indicating SSOT is missing — operator reinstalls.
        """
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        # Deliberately do NOT link paths.py — simulates the missing-SSOT case.

        result = _run_resolver_allow_fail(daemon_dir)

        assert result.returncode != 0, (
            "Resolver must exit non-zero when paths.py is missing. "
            f"Got returncode={result.returncode}, stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )
        # The unversioned legacy path must NEVER be emitted.
        assert f"{daemon_dir}/untracked/venv/bin/python" not in result.stdout, (
            "Resolver must not silently fall back to legacy path on missing "
            f"paths.py. Got stdout={result.stdout!r}"
        )

    def test_resolver_does_not_silence_python_errors(self, tmp_path: Path) -> None:
        """``python3 paths.py ...`` crashes (e.g. ModuleNotFoundError) → stderr surfaces.

        Plan 00103 Decision 2 removes ``2>/dev/null`` around the SSOT
        invocation. Simulate the crash by shadowing ``tomllib`` via
        ``sitecustomize`` so module-load fails — pre-fix paths.py crashes at
        line ``import tomllib``. The resolver MUST surface that crash to
        stderr instead of swallowing it.
        """
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        _link_fingerprint_helper(daemon_dir)

        # sitecustomize that makes tomllib unavailable on the python3 used by
        # the resolver — simulates a Python <3.11 host hitting the v3.9.0 bug.
        site_dir = tmp_path / "no_tomllib_site"
        site_dir.mkdir()
        (site_dir / "sitecustomize.py").write_text(
            "import sys\nsys.modules['tomllib'] = None\n",
            encoding="utf-8",
        )

        env_overrides = {
            "PYTHONPATH": str(site_dir),
            # Force a tomllib-unavailable interpreter for the SSOT call.
            "HOOKS_DAEMON_PYTHON": sys.executable,
        }

        result = _run_resolver_allow_fail(daemon_dir, env_overrides=env_overrides)

        # If paths.py still has top-level `import tomllib`, the SSOT crash
        # MUST be visible in stderr — silenced 2>/dev/null is the bug.
        # If paths.py has been deferred-imported (Phase 2), the SSOT runs
        # cleanly and the test path simply asserts the resolver does not
        # surface a crash. Both states are tested here:
        if "ModuleNotFoundError" in result.stderr or "tomllib" in result.stderr:
            # Pre-Phase-2: SSOT crashed. The resolver must NOT have hidden
            # the crash via 2>/dev/null and must NOT have emitted the legacy
            # fallback as if everything were fine.
            assert f"{daemon_dir}/untracked/venv/bin/python" not in result.stdout, (
                "When the SSOT python invocation crashes, resolver must not "
                "silently fall through to the legacy unversioned path. "
                f"stdout={result.stdout!r}, stderr={result.stderr!r}"
            )
            assert result.returncode != 0, (
                "When the SSOT crashes, resolver must propagate non-zero exit. "
                f"returncode={result.returncode}, stderr={result.stderr!r}"
            )
        # Post-Phase-2: SSOT runs cleanly without tomllib. Resolver still
        # exits non-zero (no venv exists in this fixture) — tested by the
        # other class methods.

    def test_resolver_never_emits_unversioned_legacy_path(self) -> None:
        """Structural guard: the resolver script must contain no literal
        unversioned legacy fallback assignment.

        Plan 00103 Decision 2 forbids the pattern
        ``PYTHON="$DAEMON_DIR/untracked/venv/bin/python"`` (the v3.7.0-retired
        unversioned legacy path) from appearing as a fallback in
        ``_resolve-venv.sh``. The fingerprint-keyed venv path
        (``untracked/venv-{fingerprint}/bin/python``) is fine — only the
        unversioned form is banned.
        """
        content = RESOLVER.read_text()
        forbidden = '"$DAEMON_DIR/untracked/venv/bin/python"'
        assert forbidden not in content, (
            f"_resolve-venv.sh must not contain the unversioned legacy "
            f"fallback assignment {forbidden!r}. The path was retired in "
            f"v3.7.0 and silently falling back to it hides real resolution "
            f"failures (Plan 00103 Decision 2)."
        )


class TestFingerprintMismatchFallback:
    """When the installer built the venv with one Python (e.g. /usr/bin/python3.13)
    but the agent's PATH resolves `python3` to a different Python (e.g. 3.9),
    the recomputed fingerprint won't match the venv directory name. The resolver
    MUST still find the existing venv-* by scanning, not fall through to the
    deleted legacy path.

    Regression test for v3.8.0 bug: /hooks-daemon skill broken on systems where
    system python3 != installer-chosen Python.
    """

    def test_scans_for_any_venv_when_fingerprint_does_not_match(self, tmp_path: Path) -> None:
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        _link_fingerprint_helper(daemon_dir)

        # Create a venv with a fingerprint that DOES NOT match what the
        # current python3 would compute — simulates installer having used a
        # different Python (e.g. installer used python3.13, resolver sees python3=3.9).
        foreign_venv = daemon_dir / "untracked" / "venv-py313-deadbeef"
        _make_venv_skeleton(foreign_venv)
        # No legacy venv — v3.7.0 upgrade deletes it.

        result = _run_resolver(daemon_dir)
        assert result == f"{foreign_venv}/bin/python", (
            "Resolver must scan for existing venv-* directories rather than "
            "relying solely on fingerprint recomputation. The installer's "
            "Python may differ from whatever `python3` resolves to when the "
            "skill wrapper fires."
        )

    def test_matching_fingerprint_still_preferred_over_foreign_venv(self, tmp_path: Path) -> None:
        """When both a matching-fingerprint venv AND a foreign venv exist, the
        matching one wins (correct multi-Python behaviour — container + host
        sharing the same project dir)."""
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        _link_fingerprint_helper(daemon_dir)

        fingerprint = python_venv_fingerprint()
        matching_venv = daemon_dir / "untracked" / f"venv-{fingerprint}"
        _make_venv_skeleton(matching_venv)

        foreign_venv = daemon_dir / "untracked" / "venv-py313-deadbeef"
        _make_venv_skeleton(foreign_venv)

        result = _run_resolver(daemon_dir)
        assert result == f"{matching_venv}/bin/python"

    def test_scan_fallback_skips_broken_venvs(self, tmp_path: Path) -> None:
        """A venv-* directory without a usable bin/python is skipped (e.g.
        partial install, cleanup-in-progress)."""
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        _link_fingerprint_helper(daemon_dir)

        broken_venv = daemon_dir / "untracked" / "venv-py313-broken00"
        (broken_venv / "bin").mkdir(parents=True)
        # No bin/python at all

        working_venv = daemon_dir / "untracked" / "venv-py313-working0"
        _make_venv_skeleton(working_venv)

        result = _run_resolver(daemon_dir)
        assert result == f"{working_venv}/bin/python"


class TestWrappersUseResolver:
    """The three skill wrapper scripts must source the shared resolver and
    not hardcode the legacy venv path."""

    @pytest.mark.parametrize("script_name", WRAPPER_SCRIPTS)
    def test_wrapper_does_not_hardcode_legacy_path(self, script_name: str) -> None:
        script = SKILL_SCRIPTS_DIR / script_name
        content = script.read_text()
        hardcoded = 'PYTHON="$DAEMON_DIR/untracked/venv/bin/python"'
        assert hardcoded not in content, (
            f"{script_name} still hardcodes the legacy venv path. "
            "It must source _resolve-venv.sh instead so fingerprint-keyed "
            "venvs from v3.7.0+ are discovered."
        )

    @pytest.mark.parametrize("script_name", WRAPPER_SCRIPTS)
    def test_wrapper_sources_canonical_resolver(self, script_name: str) -> None:
        """Plan 00285: wrappers source the canonical lib via DAEMON_DIR directly.

        Previously each wrapper sourced the co-located ``_resolve-venv.sh``
        shim via ``$(dirname "$0")``, which breaks after the self-bootstrap
        stanza's re-exec relocates ``$0`` to a mktemp file with no sibling
        shim on disk. The fix anchors resolution to ``DAEMON_DIR`` (a full
        checkout of the daemon repo, so ``scripts/lib/resolve_venv.sh``
        always exists there), which is re-exec-proof because it is derived
        from ``PROJECT_ROOT`` (walked up from ``$(pwd)``), not from ``$0``.
        """
        script = SKILL_SCRIPTS_DIR / script_name
        content = script.read_text()
        assert '$DAEMON_DIR/scripts/lib/resolve_venv.sh"' in content, (
            f"{script_name} must source the canonical resolve_venv.sh library "
            'via "$DAEMON_DIR/scripts/lib/resolve_venv.sh" — not a path relative '
            "to $0, which does not survive the self-bootstrap re-exec."
        )
        assert 'resolve_venv_python "$DAEMON_DIR"' in content, (
            f"{script_name} must call resolve_venv_python \"$DAEMON_DIR\" after "
            "sourcing the canonical library."
        )
        assert '$(dirname "$0")' not in content, (
            f"{script_name} must not resolve any path relative to $0 — that is "
            "exactly the pattern that breaks after the self-bootstrap re-exec "
            "relocates $0 to a mktemp file (Plan 00285)."
        )


class TestResolverShipsExecutableBit:
    """_resolve-venv.sh is sourced, not executed, but install.skills makes
    every *.sh in scripts/ executable. The file must be shellcheck-clean and
    have the shebang so that behaviour is safe."""

    def test_has_bash_shebang(self) -> None:
        assert RESOLVER.read_text().startswith("#!/bin/bash"), (
            "Resolver must start with #!/bin/bash so shellcheck treats it as bash "
            "and the install step chmod +x leaves a valid script on disk."
        )

    def test_is_readable(self) -> None:
        mode = RESOLVER.stat().st_mode
        assert mode & stat.S_IRUSR, "Resolver must be owner-readable"
