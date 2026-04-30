"""Plan 00103 Phase 1 Task 1.2 — ``paths.py resolve-venv`` must work under any Python 3.x.

The v3.9.0 regression breaks every diagnostic helper script (``health-check.sh``,
``daemon-cli.sh status``, etc.) on hosts where ``python3`` resolves to <3.11.
Bash wrappers shell out to ``python3 paths.py resolve-venv ...``; module-load
crashes on ``import tomllib`` and the ``2>/dev/null`` redirect at the call site
silently masks the ``ModuleNotFoundError``.

This test invokes the ``resolve-venv`` subcommand as a subprocess under an
interpreter where ``tomllib`` has been pre-emptively shadowed with ``None`` via
``sitecustomize`` (loaded automatically during interpreter startup before any
user code runs). The subprocess uses ``sys.executable`` (typically Python 3.13
in this CI) — what we are simulating is "an interpreter that does not provide
``tomllib``", which is the field-bug topology.

Pre-fix: subprocess fails at module-load with ``ModuleNotFoundError`` on
``import tomllib`` (return code != 0, stderr contains the import error).
Post-Phase-2-fix: subprocess runs cleanly, prints the resolved bin/python path,
returns 0.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PATHS_PY = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"


def _make_tomllib_unavailable_site(tmp_path: Path) -> Path:
    """Write a ``sitecustomize.py`` that shadows ``tomllib`` with ``None``.

    Python loads ``sitecustomize`` automatically during interpreter startup
    (before user-supplied script imports run), so this is a robust way to
    simulate "tomllib is not available on this interpreter" without actually
    needing a Python 3.10 binary in CI.
    """
    site_dir = tmp_path / "no_tomllib_site"
    site_dir.mkdir()
    (site_dir / "sitecustomize.py").write_text(
        "import sys\n" "sys.modules['tomllib'] = None\n",
        encoding="utf-8",
    )
    return site_dir


def _make_fingerprint_venv(daemon_dir: Path) -> Path:
    """Create a venv-keyed bin/python fixture under ``daemon_dir/untracked/``."""
    venv = daemon_dir / "untracked" / "venv-py999-fixturet"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").symlink_to(sys.executable)
    return venv


def _run_paths_subprocess(
    args: list[str], site_dir: Path, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    pythonpath_parts = [str(site_dir)]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath_parts.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    # Ensure sitecustomize is honoured even when running an isolated script.
    env.pop("PYTHONNOUSERSITE", None)
    return subprocess.run(
        [sys.executable, str(PATHS_PY), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else None,
        check=False,
    )


def test_resolve_venv_works_when_tomllib_unavailable(tmp_path: Path) -> None:
    """``resolve-venv`` must not require ``tomllib`` at any point in its path.

    Pre-fix: subprocess crashes with ``ModuleNotFoundError`` because line 22 of
    ``paths.py`` is ``import tomllib`` at module top. The fixture's stdout will
    be empty and stderr will contain "ModuleNotFoundError: No module named
    'tomllib'".

    Post-fix: subprocess succeeds; stdout is the venv's bin/python path.
    """
    daemon_dir = tmp_path / "daemon"
    daemon_dir.mkdir()
    venv = _make_fingerprint_venv(daemon_dir)
    site_dir = _make_tomllib_unavailable_site(tmp_path)

    result = _run_paths_subprocess(
        ["resolve-venv", "--daemon-dir", str(daemon_dir)], site_dir=site_dir
    )

    assert result.returncode == 0, (
        f"resolve-venv must exit 0 under any Python 3.x. "
        f"Got returncode={result.returncode}, stderr=\n{result.stderr}"
    )
    assert result.stdout.strip() == f"{venv}/bin/python", (
        f"resolve-venv stdout must be the venv bin/python. "
        f"Got stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
    assert (
        "ModuleNotFoundError" not in result.stderr
    ), f"resolve-venv must not surface ModuleNotFoundError. stderr=\n{result.stderr}"
    assert (
        "tomllib" not in result.stderr
    ), f"resolve-venv must not mention tomllib in stderr. stderr=\n{result.stderr}"


def test_resolve_venv_with_fallback_target_works_when_tomllib_unavailable(
    tmp_path: Path,
) -> None:
    """``--fallback-target`` (used by venv-include.bash) must also work without tomllib.

    On a fresh project, no venv exists yet. The wrapper passes
    ``--fallback-target`` so it gets the creation-target path back instead of
    exit 1. This code path goes through ``python_venv_fingerprint(daemon_dir)``
    which has historically been pure stdlib but the deferred-tomllib fix must
    not regress it.
    """
    daemon_dir = tmp_path / "daemon"
    daemon_dir.mkdir()
    site_dir = _make_tomllib_unavailable_site(tmp_path)

    result = _run_paths_subprocess(
        [
            "resolve-venv",
            "--daemon-dir",
            str(daemon_dir),
            "--fallback-target",
        ],
        site_dir=site_dir,
    )

    assert result.returncode == 0, (
        f"resolve-venv --fallback-target must exit 0. "
        f"Got returncode={result.returncode}, stderr=\n{result.stderr}"
    )
    out = result.stdout.strip()
    assert out.startswith(str(daemon_dir / "untracked" / "venv-")), (
        f"resolve-venv --fallback-target stdout must be a venv-* creation target. "
        f"Got stdout={out!r}"
    )
    assert out.endswith("/bin/python"), (
        f"resolve-venv --fallback-target stdout must end in /bin/python. " f"Got stdout={out!r}"
    )
