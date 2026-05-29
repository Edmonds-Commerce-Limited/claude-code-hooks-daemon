r"""Plan 00114 Phase 2 (F2) — Layer 1 self-fetches python_discovery.sh for /tmp.

Field report ``untracked/hooks-daemon-upgrade-broken.md`` (2026-05-29): the
documented manual upgrade flow is

    curl -fsSL .../scripts/upgrade.sh -o /tmp/upgrade.sh
    less /tmp/upgrade.sh
    bash /tmp/upgrade.sh --project-root /path

But Layer 1 sources ``scripts/lib/python_discovery.sh`` via
``_resolve_python_discovery_lib`` which only looks in two places:

  1. ``$daemon_dir/scripts/lib/python_discovery.sh`` — absent on a client
     whose *installed* daemon predates the helper (e.g. v3.13.0).
  2. The script's own sibling ``lib/python_discovery.sh`` — absent because
     the curl-to-/tmp flow fetches ONE file with no ``lib/`` directory.

So the documented flow aborts with
``ERR Canonical python discovery helper missing``. F2 adds a THIRD fallback:
self-fetch the helper from
``${HOOKS_DAEMON_UPGRADE_BASE_URL}/${HOOKS_DAEMON_UPGRADE_REF}/scripts/lib/python_discovery.sh``
to a temp file (cleaned via EXIT trap) when both local lookups miss.

This test pins F2: run Layer 1 from a /tmp-style dir with NO sibling ``lib/``
AND a daemon dir lacking ``python_discovery.sh``, with the base-URL pointed at
a local ``file://`` fixture serving the real helper. Layer 1 must resolve a
Python (the "Compatible Python found" OK line) and proceed PAST discovery —
never aborting with "Canonical python discovery helper missing".

Behavioural test — invokes a copied-to-/tmp ``scripts/upgrade.sh`` as a
subprocess.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LAYER1_UPGRADE_SH = REPO_ROOT / "scripts" / "upgrade.sh"
REAL_DISCOVERY_LIB = REPO_ROOT / "scripts" / "lib" / "python_discovery.sh"
BASH = shutil.which("bash") or "/bin/bash"

_MISSING_HELPER_MARKER = "Canonical python discovery helper missing"
_PYTHON_FOUND_MARKER = "Compatible Python found"
_TIMEOUT_SECONDS = 60


def _build_tmp_layer1(tmp_path: Path) -> Path:
    """Copy ONLY upgrade.sh into a /tmp-style dir (no sibling lib/)."""
    tmp_run_dir = tmp_path / "tmp-run"
    tmp_run_dir.mkdir()
    tmp_script = tmp_run_dir / "upgrade.sh"
    shutil.copy2(LAYER1_UPGRADE_SH, tmp_script)
    tmp_script.chmod(tmp_script.stat().st_mode | 0o755)
    return tmp_script


def _build_fixture_base(tmp_path: Path) -> Path:
    """Serve the real python_discovery.sh from <base>/main/scripts/lib/."""
    base_dir = tmp_path / "fixture-base"
    lib_dir = base_dir / "main" / "scripts" / "lib"
    lib_dir.mkdir(parents=True)
    shutil.copy2(REAL_DISCOVERY_LIB, lib_dir / "python_discovery.sh")
    return base_dir


def _make_project_root(tmp_path: Path) -> Path:
    """A project root that passes the initial -d check but has no daemon git.

    Layer 1 validates project-root early, then runs python discovery, then
    checks the daemon dir is a git repo. We want discovery to RUN (and succeed
    via the self-fetch), then fail LATER at the git check — proving discovery
    was reached and passed without the missing-helper abort.
    """
    project_root = tmp_path / "client-project"
    project_root.mkdir()
    (project_root / ".claude").mkdir()
    return project_root


def test_layer1_self_fetches_discovery_lib_for_tmp(tmp_path: Path) -> None:
    """Layer 1 in /tmp with a helper-less daemon dir must self-fetch the helper."""
    if not REAL_DISCOVERY_LIB.is_file():
        raise AssertionError(f"Fixture source missing: {REAL_DISCOVERY_LIB}")

    tmp_script = _build_tmp_layer1(tmp_path)
    base_dir = _build_fixture_base(tmp_path)
    project_root = _make_project_root(tmp_path)

    env = os.environ.copy()
    env["HOOKS_DAEMON_UPGRADE_BASE_URL"] = f"file://{base_dir}"
    env["HOOKS_DAEMON_UPGRADE_REF"] = "main"
    env["NO_COLOR"] = "1"

    result = subprocess.run(
        [BASH, str(tmp_script), "--project-root", str(project_root)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )

    combined = result.stdout + result.stderr
    assert _MISSING_HELPER_MARKER not in combined, (
        "Layer 1 still aborts with 'Canonical python discovery helper missing' "
        "when run from /tmp with a helper-less daemon dir — F2 self-fetch not "
        "wired.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    assert _PYTHON_FOUND_MARKER in combined, (
        "Layer 1 must resolve a Python via the self-fetched helper (expected the "
        "'Compatible Python found' line) before failing later at the git check.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_layer1_self_fetch_failure_is_loud(tmp_path: Path) -> None:
    """When the self-fetch ALSO fails (offline), Layer 1 must fail loudly.

    Points the base-URL at a non-existent file:// tree so the curl self-fetch
    fails. Layer 1 must still abort (no Python resolvable) — surfaced as a
    non-zero exit. The F4 hint work (Phase 4) makes the message actionable.
    """
    tmp_script = _build_tmp_layer1(tmp_path)
    project_root = _make_project_root(tmp_path)
    missing_base = tmp_path / "no-such-base"  # never created

    env = os.environ.copy()
    env["HOOKS_DAEMON_UPGRADE_BASE_URL"] = f"file://{missing_base}"
    env["HOOKS_DAEMON_UPGRADE_REF"] = "main"
    env["NO_COLOR"] = "1"

    result = subprocess.run(
        [BASH, str(tmp_script), "--project-root", str(project_root)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )

    assert result.returncode != 0, (
        "Layer 1 must fail (non-zero) when neither a local helper NOR the "
        "self-fetch can provide python_discovery.sh.\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
