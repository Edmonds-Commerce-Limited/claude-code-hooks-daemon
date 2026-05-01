"""Plan 00104 Phase 7 Task 7.1 — multi-host NFS fail-fast (closed Phase 3 Task 3.4).

PLAN.md §8 Multi-host NFS hostname fail-fast: when ``HOSTNAME`` is unset
AND multiple hostname-suffixed venvs exist in ``$daemon_dir/untracked/``,
the canonical resolver MUST fail fast with a directive listing the
discovered hostnames so the operator can pick one explicitly.

Background (R22 from Plan 00103 review #3): on NFS-shared
``$daemon_dir/untracked`` deployments, each host gets its own venv keyed
by hostname (e.g. ``venv-py311-deadbeef-hostA`` vs
``venv-py311-deadbeef-hostB``). When a probe interpreter has no
``HOSTNAME`` env var (cron, container with ``--hostname=""``,
Kubernetes pod without DNS resolution), the resolver cannot
disambiguate and silently picking either venv corrupts the loser host's
state. The contract is: fail loudly, list both hostnames in stderr,
direct the operator to set ``HOSTNAME`` explicitly.

The check lives in ``paths.py::_cli_resolve_venv`` (the SSOT CLI that
bash callers delegate to via ``scripts/lib/resolve_venv.sh``), so every
caller — daemon CLI, install scripts, status-line probes — gets the
same fail-fast behaviour. The fixture mirrors a multi-host NFS layout
exactly: two hostname-suffixed venvs with the same fingerprint, no
``HOSTNAME`` env var.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PATHS_PY = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"

HOSTNAME_A = "hostalpha"
HOSTNAME_B = "hostbravo"


def _make_venv_skeleton(venv_dir: Path) -> None:
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").symlink_to(sys.executable)


def _build_multi_host_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Plant two hostname-suffixed venvs sharing a single fingerprint.

    Returns ``(daemon_dir, venv_a, venv_b)``. The fingerprint slug is
    arbitrary — the canonical resolver only cares about disambiguating
    on the trailing hostname segment.
    """
    daemon_dir = tmp_path / "daemon"
    daemon_dir.mkdir()

    untracked = daemon_dir / "untracked"
    untracked.mkdir()

    fp_slug = "py311-deadbeef"
    venv_a = untracked / f"venv-{fp_slug}-{HOSTNAME_A}"
    venv_b = untracked / f"venv-{fp_slug}-{HOSTNAME_B}"
    _make_venv_skeleton(venv_a)
    _make_venv_skeleton(venv_b)

    return daemon_dir, venv_a, venv_b


def _run_paths_py_resolve(daemon_dir: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the SSOT CLI with HOSTNAME unset, capture rc + stderr."""
    env = os.environ.copy()
    env.pop("HOSTNAME", None)
    env.pop("HOOKS_DAEMON_VENV_PATH", None)
    env.pop("HOOKS_DAEMON_PYTHON", None)
    return subprocess.run(
        [sys.executable, str(PATHS_PY), "resolve-venv", "--daemon-dir", str(daemon_dir)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_multi_host_fixture_plants_both_venvs(tmp_path: Path) -> None:
    """Smoke: the fixture lays out exactly the multi-host NFS shape.

    Pins the convention used by the fail-fast assertion: two
    hostname-suffixed sibling venvs under ``daemon_dir/untracked/``
    sharing a fingerprint slug, each with a usable ``bin/python``.
    """
    daemon_dir, venv_a, venv_b = _build_multi_host_fixture(tmp_path)
    assert venv_a.is_dir() and venv_b.is_dir()
    assert (venv_a / "bin" / "python").exists()
    assert (venv_b / "bin" / "python").exists()
    siblings = sorted(p.name for p in (daemon_dir / "untracked").iterdir())
    assert siblings == [
        f"venv-py311-deadbeef-{HOSTNAME_A}",
        f"venv-py311-deadbeef-{HOSTNAME_B}",
    ]


def test_resolve_venv_fails_fast_with_hostname_directive_when_hostname_unset(
    tmp_path: Path,
) -> None:
    """Multi-host NFS, no ``HOSTNAME``, two hostname-suffixed venvs:
    resolver MUST exit non-zero AND list both hostnames in stderr."""
    daemon_dir, _venv_a, _venv_b = _build_multi_host_fixture(tmp_path)

    result = _run_paths_py_resolve(daemon_dir)

    assert result.returncode != 0, (
        f"Resolver must fail non-zero with HOSTNAME unset and "
        f"hostname-suffixed venvs present.\n"
        f"returncode={result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert HOSTNAME_A in result.stderr and HOSTNAME_B in result.stderr, (
        "stderr must list both discovered hostnames so the operator can "
        "pick one explicitly via HOSTNAME=...\n"
        f"stderr=\n{result.stderr}"
    )
    assert "HOSTNAME" in result.stderr, (
        "stderr must direct the operator to set HOSTNAME explicitly.\n" f"stderr=\n{result.stderr}"
    )
