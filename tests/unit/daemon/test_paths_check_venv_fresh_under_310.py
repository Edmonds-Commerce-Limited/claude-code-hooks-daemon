"""Plan 00103 Phase 1 Task 1.3 — ``check-venv-fresh`` must not crash with ``ModuleNotFoundError`` under Python <3.11.

Plan 00103 Decision 1 narrative anticipated that ``check-venv-fresh`` might
"raise a clear error under <3.11". In the live code, ``_cli_check_venv_fresh``
only consumes ``_compute_project_lock_hash_stdlib`` (pure stdlib, hash-only) and
``_read_venv_metadata_stdlib`` (pure stdlib, JSON). Neither path needs
``tomllib``. So after the deferred-import fix, ``check-venv-fresh`` actually
*succeeds* under Python 3.10 — that is the desired post-fix behaviour.

The load-bearing assertion is therefore:

    Under Python <3.11 (simulated by sitecustomize-shadowed ``tomllib``),
    ``paths.py check-venv-fresh`` must NOT crash with ``ModuleNotFoundError``.
    It must return either 0 (lock_hash matches) or 1 (lock_hash differs /
    metadata absent) with a clear stderr message — never a module-load
    ``ModuleNotFoundError`` traceback.

Pre-fix: subprocess crashes at module-load on ``import tomllib``. Stderr
contains ``ModuleNotFoundError`` and returncode is non-zero. RED.

Post-fix: subprocess loads paths.py cleanly, runs the freshness check using
stdlib-only helpers, and returns the expected exit code.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PHASE2_REASON = (
    "Plan 00103 Phase 2 not yet landed — paths.py still has top-level "
    "`import tomllib` (line 22). Marker is removed as part of the Phase 2 "
    "deferred-import commit; strict=True forces the marker to be removed "
    "the moment the fix lands."
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PATHS_PY = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"


def _make_tomllib_unavailable_site(tmp_path: Path) -> Path:
    site_dir = tmp_path / "no_tomllib_site"
    site_dir.mkdir()
    (site_dir / "sitecustomize.py").write_text(
        "import sys\n" "sys.modules['tomllib'] = None\n",
        encoding="utf-8",
    )
    return site_dir


def _make_daemon_dir(tmp_path: Path) -> Path:
    daemon = tmp_path / "daemon"
    daemon.mkdir()
    (daemon / "pyproject.toml").write_text('[project]\nname = "fake"\n', encoding="utf-8")
    return daemon


def _make_venv_with_lock_hash(venv_dir: Path, lock_hash: str) -> None:
    venv_dir.mkdir(parents=True)
    payload = {
        "python_path": str(venv_dir / "bin" / "python"),
        "fingerprint": "abcd1234",
        "lock_hash": lock_hash,
        "daemon_version": "v1.0.0",
        "written_at": "2026-01-01T00:00:00Z",
    }
    (venv_dir / ".daemon-metadata.json").write_text(json.dumps(payload), encoding="utf-8")


def _run_paths_subprocess(args: list[str], site_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    pythonpath_parts = [str(site_dir)]
    if existing := env.get("PYTHONPATH"):
        pythonpath_parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    env.pop("PYTHONNOUSERSITE", None)
    return subprocess.run(
        [sys.executable, str(PATHS_PY), *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _compute_lock_hash_for(daemon_dir: Path) -> str:
    """Use the project's own _compute_project_lock_hash_stdlib helper.

    Imported lazily so the test module does not pull in paths.py at collection
    time (it would mask the regression we are trying to test).
    """
    from claude_code_hooks_daemon.daemon.paths import _compute_project_lock_hash_stdlib

    result = _compute_project_lock_hash_stdlib(daemon_dir)
    assert result is not None
    return result


@pytest.mark.xfail(strict=True, reason=_PHASE2_REASON)
def test_check_venv_fresh_does_not_crash_when_tomllib_unavailable(tmp_path: Path) -> None:
    """``check-venv-fresh`` must not surface ``ModuleNotFoundError`` under <3.11.

    With a venv whose ``.daemon-metadata.json`` matches the current
    ``_compute_project_lock_hash_stdlib`` output, post-fix invocation should
    return 0 cleanly.
    """
    daemon = _make_daemon_dir(tmp_path)
    venv = tmp_path / "venv"
    _make_venv_with_lock_hash(venv, _compute_lock_hash_for(daemon))
    site_dir = _make_tomllib_unavailable_site(tmp_path)

    result = _run_paths_subprocess(
        [
            "check-venv-fresh",
            "--venv-path",
            str(venv),
            "--daemon-dir",
            str(daemon),
        ],
        site_dir=site_dir,
    )

    assert "ModuleNotFoundError" not in result.stderr, (
        f"check-venv-fresh must not surface ModuleNotFoundError when tomllib "
        f"is unavailable. stderr=\n{result.stderr}"
    )
    assert "No module named 'tomllib'" not in result.stderr, (
        f"check-venv-fresh must not surface module-load tomllib failure. "
        f"stderr=\n{result.stderr}"
    )
    assert result.returncode == 0, (
        f"check-venv-fresh with matching lock_hash must exit 0 even under "
        f"<3.11 (it does not actually need tomllib). "
        f"Got returncode={result.returncode}, stderr=\n{result.stderr}"
    )


@pytest.mark.xfail(strict=True, reason=_PHASE2_REASON)
def test_check_venv_fresh_returns_1_on_mismatch_when_tomllib_unavailable(
    tmp_path: Path,
) -> None:
    """Mismatch path: still exits 1 cleanly (no tomllib crash)."""
    daemon = _make_daemon_dir(tmp_path)
    venv = tmp_path / "venv"
    _make_venv_with_lock_hash(venv, lock_hash="sha256:" + "0" * 64)
    site_dir = _make_tomllib_unavailable_site(tmp_path)

    result = _run_paths_subprocess(
        [
            "check-venv-fresh",
            "--venv-path",
            str(venv),
            "--daemon-dir",
            str(daemon),
        ],
        site_dir=site_dir,
    )

    assert "ModuleNotFoundError" not in result.stderr, (
        f"check-venv-fresh must not surface ModuleNotFoundError. " f"stderr=\n{result.stderr}"
    )
    assert result.returncode == 1, (
        f"check-venv-fresh with non-matching lock_hash must exit 1. "
        f"Got returncode={result.returncode}, stderr=\n{result.stderr}"
    )
