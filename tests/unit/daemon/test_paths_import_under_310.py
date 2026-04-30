"""Plan 00103 Phase 1 Task 1.1 — paths.py module-load must not require tomllib.

The v3.9.0 regression: ``import tomllib`` at the module top of
``daemon/paths.py`` crashes on Python <3.11 (RHEL/CentOS-default 3.9, etc.).
Every wrapper that invokes ``python3 paths.py resolve-venv ...`` against the
system default ``python3`` then dies at module load with
``ModuleNotFoundError: No module named 'tomllib'``.

Plan 00103 Decision 1 fix: defer the ``import tomllib`` into the helper
function(s) that genuinely need it (only ``can_inline_bootstrap`` does, via a
``_load_toml_or_raise`` helper). After the fix, ``paths.py`` imports under any
Python 3.x and ``_cli_resolve_venv`` / ``_cli_check_venv_fresh`` remain
callable.

These tests use ``subprocess`` rather than ``importlib.reload`` so that the
in-process module table is never disturbed — reloading ``paths`` mid-suite
silently breaks unrelated tests that hold bound references to its functions
(``test_paths_resolve_venv_diagnostics`` monkeypatches module attributes,
``test_paths_stale_cleanup`` calls module functions through their original
import). Subprocess isolation keeps Phase 1 RED tests honest without
polluting the rest of the suite.
"""

from __future__ import annotations

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


_PATHS_MODULE = "claude_code_hooks_daemon.daemon.paths"
REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = REPO_ROOT / "src"


def _make_tomllib_unavailable_site(tmp_path: Path) -> Path:
    site_dir = tmp_path / "no_tomllib_site"
    site_dir.mkdir()
    (site_dir / "sitecustomize.py").write_text(
        "import sys\nsys.modules['tomllib'] = None\n",
        encoding="utf-8",
    )
    return site_dir


def _run_python(code: str, site_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    pythonpath_parts = [str(SRC_DIR)]
    if site_dir is not None:
        pythonpath_parts.insert(0, str(site_dir))
    if existing := env.get("PYTHONPATH"):
        pythonpath_parts.append(existing)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    env.pop("PYTHONNOUSERSITE", None)
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.xfail(strict=True, reason=_PHASE2_REASON)
def test_paths_imports_when_tomllib_unavailable(tmp_path: Path) -> None:
    """``paths.py`` must not import ``tomllib`` at module top.

    Shadowing ``sys.modules['tomllib']`` with ``None`` via ``sitecustomize``
    simulates a Python <3.11 host. Pre-fix: paths.py module body crashes at
    ``import tomllib`` and the subprocess exits non-zero with
    ``ModuleNotFoundError`` in stderr. Post-fix: module body imports cleanly
    and the CLI helper symbols are callable; the subprocess prints ``OK``
    and exits 0.
    """
    site_dir = _make_tomllib_unavailable_site(tmp_path)
    code = (
        f"import importlib\n"
        f"paths = importlib.import_module({_PATHS_MODULE!r})\n"
        f"assert callable(paths._cli_resolve_venv), '_cli_resolve_venv missing'\n"
        f"assert callable(paths._cli_check_venv_fresh), '_cli_check_venv_fresh missing'\n"
        f"print('OK')\n"
    )

    result = _run_python(code, site_dir=site_dir)

    assert "ModuleNotFoundError" not in result.stderr, (
        f"paths.py module-load must not surface ModuleNotFoundError when "
        f"tomllib is unavailable. stderr=\n{result.stderr}"
    )
    assert result.returncode == 0, (
        f"paths.py must import cleanly under any Python 3.x. "
        f"returncode={result.returncode}, stdout={result.stdout!r}, "
        f"stderr={result.stderr!r}"
    )
    assert "OK" in result.stdout, (
        f"Expected 'OK' marker confirming both CLI symbols are callable. "
        f"stdout={result.stdout!r}"
    )


@pytest.mark.xfail(strict=True, reason=_PHASE2_REASON)
def test_paths_module_does_not_have_top_level_tomllib_attribute() -> None:
    """After deferred-import, ``paths.tomllib`` must not be a module attribute.

    A grep-style structural assertion that backstops the runtime check above.
    The fix moves ``tomllib`` into a function-local import; if a future change
    reintroduces a top-level ``import tomllib`` (or ``from tomllib import ...``),
    this test fires immediately rather than waiting for a Python 3.10 host.

    Subprocess-isolated so the in-process module remains untouched.
    """
    code = (
        f"import importlib\n"
        f"paths = importlib.import_module({_PATHS_MODULE!r})\n"
        f"if hasattr(paths, 'tomllib'):\n"
        f"    raise SystemExit('FAIL: paths.tomllib is a module-level attribute')\n"
        f"print('OK')\n"
    )

    result = _run_python(code)

    assert result.returncode == 0, (
        f"paths.py must not have a module-level `tomllib` attribute. "
        f"Deferred-import (Plan 00103 Decision 1) requires `import tomllib` "
        f"to live inside a helper function, not at module top. "
        f"stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
