"""Integration tests for init.sh's `_resolve_python_cmd()` function.

Plan 00099 Phase 4: init.sh resolves PYTHON_CMD lazily using the
fingerprint-keyed venv when one exists, with a scan-fallback for
foreign-fingerprint venv directories.

Plan 00103 Decision 2: when none of the precedence steps resolve, the
resolver fails loudly with `return 5` + a stderr directive. The pre-v3.7.0
unversioned legacy `untracked/venv/bin/python` is no longer accepted as
a silent fallback because that hid the v3.9.0 field-bug regression where
operators saw "venv missing" while the real cause was a 3.9-vs-3.11
``import tomllib`` crash.

Precedence (highest first):
  1. $HOOKS_DAEMON_VENV_PATH       — explicit override
  2. venv-{fingerprint}/bin/python — fingerprint-keyed (recomputed)
  3. venv-*/bin/python             — any existing fingerprint venv (scan)
  4. fail loudly with return 5 + stderr directive

Tests invoke init.sh's resolver in an isolated subshell with a fake
$HOOKS_DAEMON_ROOT_DIR so we can control which paths exist.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SH = REPO_ROOT / "init.sh"


def _extract_resolver(tmp: Path) -> Path:
    """Extract _resolve_python_cmd from init.sh into a sourceable helper.

    init.sh has side effects on sourcing (socket path computation, env file
    loading) that we don't want in tests. We extract just the resolver.
    """
    text = INIT_SH.read_text()
    start = text.index("_resolve_python_cmd() {")
    # Find matching close brace (resolver ends with first standalone "}")
    depth = 0
    i = start
    end = -1
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
        i += 1
    if end == -1:
        raise RuntimeError("Could not find matching brace for _resolve_python_cmd")
    resolver = text[start:end]
    helper = tmp / "resolver.sh"
    helper.write_text(
        '#!/bin/bash\nPYTHON_CMD=""\nHOOKS_DAEMON_ROOT_DIR="${HOOKS_DAEMON_ROOT_DIR:-}"\n'
        'PROJECT_PATH="${PROJECT_PATH:-$HOOKS_DAEMON_ROOT_DIR}"\n' + resolver + "\n"
    )
    return helper


def _run_resolver(helper: Path, root_dir: Path, env_overrides: dict[str, str] | None = None) -> str:
    env = os.environ.copy()
    env["HOOKS_DAEMON_ROOT_DIR"] = str(root_dir)
    env["PROJECT_PATH"] = str(root_dir)
    env["PATH"] = os.environ["PATH"]
    if env_overrides:
        env.update(env_overrides)
    # Remove HOOKS_DAEMON_VENV_PATH unless explicitly set by override
    if not env_overrides or "HOOKS_DAEMON_VENV_PATH" not in env_overrides:
        env.pop("HOOKS_DAEMON_VENV_PATH", None)
    result = subprocess.run(
        ["bash", "-c", f'source "{helper}" && _resolve_python_cmd && echo "$PYTHON_CMD"'],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.strip().splitlines()[-1]


def _make_venv_skeleton(path: Path) -> None:
    """Create a fake venv directory structure that looks healthy enough."""
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").symlink_to(sys.executable)


class TestExplicitOverride:
    """HOOKS_DAEMON_VENV_PATH takes precedence over everything."""

    def test_explicit_override_wins(self, tmp_path: Path) -> None:
        helper = _extract_resolver(tmp_path)
        root = tmp_path / "project"
        root.mkdir()
        # Symlink the helper into project scripts/install so sourcing works
        (root / "scripts" / "install").mkdir(parents=True)
        (root / "scripts" / "install" / "python_fingerprint.sh").symlink_to(
            REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"
        )

        override_venv = tmp_path / "explicit"
        _make_venv_skeleton(override_venv)

        result = _run_resolver(
            helper,
            root_dir=root,
            env_overrides={"HOOKS_DAEMON_VENV_PATH": str(override_venv)},
        )
        assert result == f"{override_venv}/bin/python"


class TestFingerprintKeyed:
    """When no override and fingerprint venv exists, use it."""

    def test_fingerprint_keyed_venv_wins_over_legacy(self, tmp_path: Path) -> None:
        helper = _extract_resolver(tmp_path)
        root = tmp_path / "project"
        root.mkdir()
        (root / "scripts" / "install").mkdir(parents=True)
        (root / "scripts" / "install" / "python_fingerprint.sh").symlink_to(
            REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"
        )
        # Compute the current fingerprint
        from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

        fingerprint = python_venv_fingerprint()
        keyed_venv = root / "untracked" / f"venv-{fingerprint}"
        _make_venv_skeleton(keyed_venv)
        # Also create legacy venv — must NOT be chosen
        legacy_venv = root / "untracked" / "venv"
        _make_venv_skeleton(legacy_venv)

        result = _run_resolver(helper, root_dir=root)
        assert result == f"{keyed_venv}/bin/python"


class TestLegacyFallback:
    """Plan 00103 Decision 2: when no venv exists, the resolver MUST fail
    loudly with `return 5` + stderr directive. The pre-v3.7.0 silent fallback
    to ``$HOOKS_DAEMON_ROOT_DIR/untracked/venv/bin/python`` is gone because
    it hid real failures (ModuleNotFoundError, broken venvs) behind a
    generic "venv missing" message produced by validate_venv."""

    def _run_resolver_expecting_failure(
        self, helper: Path, root_dir: Path
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["HOOKS_DAEMON_ROOT_DIR"] = str(root_dir)
        env["PROJECT_PATH"] = str(root_dir)
        env["PATH"] = os.environ["PATH"]
        env.pop("HOOKS_DAEMON_VENV_PATH", None)
        env.pop("HOOKS_DAEMON_PYTHON", None)
        return subprocess.run(
            [
                "bash",
                "-c",
                f'source "{helper}" && _resolve_python_cmd && echo "$PYTHON_CMD"',
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def test_no_venv_exits_nonzero_with_install_directive(self, tmp_path: Path) -> None:
        helper = _extract_resolver(tmp_path)
        root = tmp_path / "project"
        root.mkdir()

        result = self._run_resolver_expecting_failure(helper, root)

        assert result.returncode != 0, (
            "Resolver must exit non-zero when no venv exists anywhere. "
            f"returncode={result.returncode}, stdout={result.stdout!r}, "
            f"stderr={result.stderr!r}"
        )
        assert "no usable venv" in result.stderr or "install" in result.stderr.lower(), (
            f"stderr must reference the missing venv and the install directive. "
            f"Got stderr=\n{result.stderr}"
        )
        assert f"{root}/untracked/venv/bin/python" not in result.stdout, (
            "Resolver must not silently emit the unversioned legacy path. "
            f"Got stdout={result.stdout!r}"
        )

    def test_no_venv_exits_nonzero_when_fingerprint_helper_missing(self, tmp_path: Path) -> None:
        """If the bash fingerprint helper isn't shipped, scan-fallback still
        runs; with no venv-*/ directories it must fail loudly rather than
        emit the legacy path."""
        helper = _extract_resolver(tmp_path)
        root = tmp_path / "project"
        root.mkdir()
        # Deliberately NO scripts/install/python_fingerprint.sh

        result = self._run_resolver_expecting_failure(helper, root)

        assert result.returncode != 0, (
            f"Resolver must exit non-zero when fingerprint helper is missing "
            f"AND no venv-*/ exists. returncode={result.returncode}, "
            f"stdout={result.stdout!r}, stderr={result.stderr!r}"
        )
        assert f"{root}/untracked/venv/bin/python" not in result.stdout


class TestScanFallback:
    """Plan 00103: when fingerprint computation fails or finds no match,
    the resolver scans `untracked/venv-*/bin/python` and uses any usable
    interpreter rather than falling through to legacy."""

    def test_foreign_fingerprint_venv_used_when_no_match(self, tmp_path: Path) -> None:
        helper = _extract_resolver(tmp_path)
        root = tmp_path / "project"
        root.mkdir()
        (root / "scripts" / "install").mkdir(parents=True)
        (root / "scripts" / "install" / "python_fingerprint.sh").symlink_to(
            REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"
        )

        foreign_venv = root / "untracked" / "venv-py313-deadbeef"
        _make_venv_skeleton(foreign_venv)

        result = _run_resolver(helper, root_dir=root)
        assert result == f"{foreign_venv}/bin/python", (
            "Resolver must scan existing venv-*/ dirs rather than falling "
            "through to legacy when the recomputed fingerprint does not match."
        )


class TestHookDaemonPythonOverride:
    """HOOKS_DAEMON_PYTHON lets the user pin a specific interpreter for fingerprinting."""

    def test_honors_hooks_daemon_python_when_fingerprinting(self, tmp_path: Path) -> None:
        helper = _extract_resolver(tmp_path)
        root = tmp_path / "project"
        root.mkdir()
        (root / "scripts" / "install").mkdir(parents=True)
        (root / "scripts" / "install" / "python_fingerprint.sh").symlink_to(
            REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"
        )

        # Since we specify HOOKS_DAEMON_PYTHON, the fingerprint is computed
        # from that interpreter. Create a matching keyed venv.
        import hashlib
        import platform

        # Replicate the fingerprint formula for the CURRENT interpreter
        parts = f"{sys.version}|{sys.base_prefix}|{platform.machine()}"
        digest = hashlib.md5(parts.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
        fingerprint = f"py{sys.version_info.major}{sys.version_info.minor}-{digest}"
        keyed_venv = root / "untracked" / f"venv-{fingerprint}"
        _make_venv_skeleton(keyed_venv)

        result = _run_resolver(
            helper,
            root_dir=root,
            env_overrides={"HOOKS_DAEMON_PYTHON": sys.executable},
        )
        assert result == f"{keyed_venv}/bin/python"
