"""Plan 00104 Phase 3 Task 3.1 — venv resolver parity matrix.

Asserts that every venv-resolution site in the codebase returns the same
``bin/python`` path for the same daemon-dir input. This is the failing
test that drives Phase 4 (canonical library) and Phase 5 (shim collapse).

Sites probed:

  1. ``src/.../daemon/paths.py resolve-venv`` — the Python SSOT
  2. ``scripts/install/venv_resolver.sh::resolve_existing_venv_python``
  3. ``src/.../skills/hooks-daemon/scripts/_resolve-venv.sh``
  4. ``scripts/venv-include.bash``
  5. ``init.sh::_resolve_python_cmd``

Sites 2-4 already shell out to the SSOT, so they inherit its precedence.
Site 5 (init.sh) has its OWN bash resolver — fingerprint match plus a
scan-fallback — and does NOT consult ``.daemon-metadata.json``. That is
the drift this test pins down.

The fixture plants two venvs in ``$daemon_dir/untracked/``:

  * ``venv-aaa-fake/`` — alphabetically first, no metadata.
  * ``venv-zzz-real/`` — has a ``.daemon-metadata.json`` whose
    ``lock_hash`` matches the project's current
    ``sha256(pyproject.toml + uv.lock)``.

The SSOT prefers ``venv-zzz-real`` via the metadata-authoritative
precedence step (Plan 00100 Task 3.5). Sites that delegate to it agree.
``init.sh`` has no such step — its scan-fallback returns the
alphabetically-first ``venv-aaa-fake``. The parity assertion fails.

Marked ``xfail(strict=True)`` because the divergence is real and
intentional in the v3.9.x codebase. Phase 4 introduces a canonical
library that every site delegates to; once init.sh sources it, the
parity assertion passes and the strict marker forces removal of the
xfail at that point — exactly the TDD signal Phase 4 needs.

NOTE: ``test_all_sites_return_a_path_with_single_venv`` is the smoke
test proving the harness works — every site CAN be invoked from a
fixture daemon dir and returns a usable answer. It is NOT marked xfail.
The xfail only applies to the metadata-authoritative parity assertion
that exposes the init.sh divergence.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SH = REPO_ROOT / "init.sh"
VENV_RESOLVER_SH = REPO_ROOT / "scripts" / "install" / "venv_resolver.sh"
FINGERPRINT_HELPER = REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"
VENV_INCLUDE_BASH = REPO_ROOT / "scripts" / "venv-include.bash"
SKILL_RESOLVE_VENV_SH = (
    REPO_ROOT
    / "src"
    / "claude_code_hooks_daemon"
    / "skills"
    / "hooks-daemon"
    / "scripts"
    / "_resolve-venv.sh"
)
PATHS_PY = REPO_ROOT / "src" / "claude_code_hooks_daemon" / "daemon" / "paths.py"
PYPROJECT_TOML = REPO_ROOT / "pyproject.toml"
UV_LOCK = REPO_ROOT / "uv.lock"

# Plan 00100 metadata sentinel for missing uv.lock — must mirror
# ``paths._UV_LOCK_ABSENT_MARKER`` exactly. Kept inline to avoid coupling
# the test to an internal symbol.
UV_LOCK_ABSENT_MARKER = b"<no-uv.lock-present>"


def _compute_lock_hash(project_root: Path) -> str:
    """Recompute ``sha256(pyproject.toml + uv.lock)`` the same way paths.py does.

    Mirrors :func:`claude_code_hooks_daemon.daemon.paths._compute_project_lock_hash_stdlib`
    byte-for-byte so the fixture's metadata-authoritative venv produces
    the same digest the SSOT will read at resolve time.
    """
    hasher = hashlib.sha256()
    hasher.update((project_root / "pyproject.toml").read_bytes())
    uv_lock = project_root / "uv.lock"
    if uv_lock.is_file():
        hasher.update(uv_lock.read_bytes())
    else:
        hasher.update(UV_LOCK_ABSENT_MARKER)
    return f"sha256:{hasher.hexdigest()}"


def _make_venv_skeleton(venv_dir: Path) -> None:
    """Plant a fake venv whose ``bin/python`` is a real, executable interpreter.

    The SSOT and every bash site check executability via ``os.access(X_OK)``
    or shell ``-x``. Symlinking to ``sys.executable`` satisfies both with
    no need to ``python3 -m venv``.
    """
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").symlink_to(sys.executable)


def _build_fixture_daemon_dir(tmp_path: Path) -> tuple[Path, Path]:
    """Build a self-contained daemon dir with two venvs.

    Returns ``(daemon_dir, real_venv)``. ``real_venv`` carries a
    metadata-authoritative ``.daemon-metadata.json`` whose ``lock_hash``
    matches the daemon dir's own ``pyproject.toml`` + ``uv.lock``. The
    alphabetically-first ``venv-aaa-fake`` (no metadata) is also planted
    so the bash scan-fallback picks the wrong venv when no
    metadata-authoritative step is consulted.
    """
    daemon_dir = tmp_path / "daemon"
    daemon_dir.mkdir()

    # Walk-up sentinel for init.sh.
    (daemon_dir / ".claude").mkdir()

    # Real pyproject + uv.lock so lock_hash computation is reproducible.
    shutil.copy2(PYPROJECT_TOML, daemon_dir / "pyproject.toml")
    shutil.copy2(UV_LOCK, daemon_dir / "uv.lock")

    # paths.py SSOT must be reachable at $daemon_dir/src/.../paths.py for
    # the skill-bundle resolver. Symlink the entire src/ subtree.
    (daemon_dir / "src").symlink_to(REPO_ROOT / "src")

    # python_fingerprint.sh must live at $daemon_dir/scripts/install/ so
    # init.sh::_resolve_python_cmd can source it. Symlink only that subtree.
    install_dir = daemon_dir / "scripts" / "install"
    install_dir.mkdir(parents=True)
    (install_dir / "python_fingerprint.sh").symlink_to(FINGERPRINT_HELPER)

    # Plan 00104 Phase 4: init.sh and venv-include.bash now source
    # scripts/lib/resolve_venv.sh — the canonical library — so the fixture
    # must expose it at the same relative path the production tree does.
    lib_dir = daemon_dir / "scripts" / "lib"
    lib_dir.mkdir(parents=True)
    (lib_dir / "resolve_venv.sh").symlink_to(REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh")

    # venv-include.bash derives PROJECT_ROOT from its own BASH_SOURCE.
    # Copy (don't symlink) so it sees the fixture daemon_dir as its root.
    shutil.copy2(VENV_INCLUDE_BASH, daemon_dir / "scripts" / "venv-include.bash")

    untracked = daemon_dir / "untracked"
    untracked.mkdir()

    _make_venv_skeleton(untracked / "venv-aaa-fake")

    real_venv = untracked / "venv-zzz-real"
    _make_venv_skeleton(real_venv)
    metadata = {
        "lock_hash": _compute_lock_hash(daemon_dir),
        "python_path": str(real_venv / "bin" / "python"),
        "fingerprint": "py311-zzzreal0",
        "schema_version": 1,
    }
    (real_venv / ".daemon-metadata.json").write_text(json.dumps(metadata))

    return daemon_dir, real_venv


def _clean_env() -> dict[str, str]:
    """Environment with venv overrides stripped so precedence step 1 misses."""
    env = os.environ.copy()
    env.pop("HOOKS_DAEMON_VENV_PATH", None)
    env.pop("HOOKS_DAEMON_PYTHON", None)
    return env


def _resolve_via_paths_py_cli(daemon_dir: Path) -> Path:
    """Site 1: invoke ``paths.py resolve-venv --daemon-dir`` directly."""
    result = subprocess.run(
        [sys.executable, str(PATHS_PY), "resolve-venv", "--daemon-dir", str(daemon_dir)],
        capture_output=True,
        text=True,
        env=_clean_env(),
        check=True,
    )
    return Path(result.stdout.strip().splitlines()[-1])


def _resolve_via_install_venv_resolver(daemon_dir: Path) -> Path:
    """Site 2: source ``scripts/install/venv_resolver.sh`` and call its function."""
    harness = (
        "set -euo pipefail\n"
        f'source "{VENV_RESOLVER_SH}"\n'
        f'resolve_existing_venv_python "{daemon_dir}"\n'
    )
    result = subprocess.run(
        ["bash", "-c", harness],
        capture_output=True,
        text=True,
        env=_clean_env(),
        check=True,
    )
    return Path(result.stdout.strip().splitlines()[-1])


def _resolve_via_skill_resolver(daemon_dir: Path) -> Path:
    """Site 3: source ``_resolve-venv.sh`` with DAEMON_DIR set."""
    harness = (
        "set -euo pipefail\n"
        f'export DAEMON_DIR="{daemon_dir}"\n'
        f'source "{SKILL_RESOLVE_VENV_SH}"\n'
        'echo "$PYTHON"\n'
    )
    result = subprocess.run(
        ["bash", "-c", harness],
        capture_output=True,
        text=True,
        env=_clean_env(),
        check=True,
    )
    return Path(result.stdout.strip().splitlines()[-1])


def _resolve_via_venv_include(daemon_dir: Path) -> Path:
    """Site 4: source the COPY of ``venv-include.bash`` from fixture root.

    The script derives ``PROJECT_ROOT`` from its own ``BASH_SOURCE``, so
    sourcing the fixture copy makes ``PROJECT_ROOT == daemon_dir``.
    """
    fixture_include = daemon_dir / "scripts" / "venv-include.bash"
    harness = "set -euo pipefail\n" f'source "{fixture_include}"\n' 'echo "$VENV_PYTHON"\n'
    result = subprocess.run(
        ["bash", "-c", harness],
        capture_output=True,
        text=True,
        env=_clean_env(),
        check=True,
    )
    return Path(result.stdout.strip().splitlines()[-1])


def _extract_init_sh_resolver(tmp_path: Path) -> Path:
    """Carve ``_resolve_python_cmd`` out of ``init.sh`` for isolated sourcing.

    Sourcing ``init.sh`` whole pulls in socket-path computation, env-file
    loading, and ``set -euo pipefail`` side effects we don't want.
    """
    text = INIT_SH.read_text()
    start = text.index("_resolve_python_cmd() {")
    depth = 0
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end == -1:
        raise RuntimeError("could not find matching brace for _resolve_python_cmd")
    helper = tmp_path / "init_resolver.sh"
    helper.write_text(
        "#!/bin/bash\n"
        'PYTHON_CMD=""\n'
        'HOOKS_DAEMON_ROOT_DIR="${HOOKS_DAEMON_ROOT_DIR:-}"\n'
        'PROJECT_PATH="${PROJECT_PATH:-$HOOKS_DAEMON_ROOT_DIR}"\n' + text[start:end] + "\n"
    )
    return helper


def _resolve_via_init_sh(daemon_dir: Path, tmp_path: Path) -> Path:
    """Site 5: invoke init.sh's ``_resolve_python_cmd`` against ``daemon_dir``."""
    helper = _extract_init_sh_resolver(tmp_path)
    env = _clean_env()
    env["HOOKS_DAEMON_ROOT_DIR"] = str(daemon_dir)
    env["PROJECT_PATH"] = str(daemon_dir)
    result = subprocess.run(
        ["bash", "-c", f'source "{helper}" && _resolve_python_cmd && echo "$PYTHON_CMD"'],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return Path(result.stdout.strip().splitlines()[-1])


def _normalise(python_path: Path) -> Path:
    """Reduce ``.../venv-X/bin/python(3)`` to ``.../venv-X`` for parity comparison.

    Some sites print ``bin/python`` and others print ``bin/python3``. Both
    point at the same venv; comparing on the venv directory keeps the
    parity assertion focused on selection, not naming convention.
    """
    return python_path.parent.parent


def test_all_sites_return_a_path_with_single_venv(tmp_path: Path) -> None:
    """Smoke test: every site is invokable and returns a usable path.

    Plants exactly ONE venv (with metadata-authoritative match) and asserts
    all 5 sites resolve to it. Proves the harness works before the
    parity-divergence assertion fires.
    """
    daemon_dir = tmp_path / "daemon"
    daemon_dir.mkdir()
    (daemon_dir / ".claude").mkdir()
    shutil.copy2(PYPROJECT_TOML, daemon_dir / "pyproject.toml")
    shutil.copy2(UV_LOCK, daemon_dir / "uv.lock")
    (daemon_dir / "src").symlink_to(REPO_ROOT / "src")
    install_dir = daemon_dir / "scripts" / "install"
    install_dir.mkdir(parents=True)
    (install_dir / "python_fingerprint.sh").symlink_to(FINGERPRINT_HELPER)
    lib_dir = daemon_dir / "scripts" / "lib"
    lib_dir.mkdir(parents=True)
    (lib_dir / "resolve_venv.sh").symlink_to(REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh")
    shutil.copy2(VENV_INCLUDE_BASH, daemon_dir / "scripts" / "venv-include.bash")

    untracked = daemon_dir / "untracked"
    untracked.mkdir()
    only_venv = untracked / "venv-onlyone"
    _make_venv_skeleton(only_venv)
    metadata = {
        "lock_hash": _compute_lock_hash(daemon_dir),
        "python_path": str(only_venv / "bin" / "python"),
        "fingerprint": "py311-onlyone0",
        "schema_version": 1,
    }
    (only_venv / ".daemon-metadata.json").write_text(json.dumps(metadata))

    results = {
        "paths_py_cli": _resolve_via_paths_py_cli(daemon_dir),
        "venv_resolver_sh": _resolve_via_install_venv_resolver(daemon_dir),
        "skill_resolve_venv_sh": _resolve_via_skill_resolver(daemon_dir),
        "venv_include_bash": _resolve_via_venv_include(daemon_dir),
        "init_sh_resolver": _resolve_via_init_sh(daemon_dir, tmp_path),
    }
    venv_dirs = {site: _normalise(p) for site, p in results.items()}
    assert set(venv_dirs.values()) == {only_venv}, (
        "Single-venv smoke test: every site must return the only available venv. "
        f"Got: {venv_dirs}"
    )


def test_all_sites_agree_on_metadata_authoritative_venv(tmp_path: Path) -> None:
    """All 5 sites must converge on the metadata-authoritative venv.

    Two venvs exist: ``venv-aaa-fake`` (no metadata, alphabetically first)
    and ``venv-zzz-real`` (lock-hash-matching metadata). The SSOT picks
    ``venv-zzz-real`` via Plan 00100 Task 3.5 step 2.

    Plan 00104 Phase 4 contract: every site delegates to the canonical
    library at ``scripts/lib/resolve_venv.sh``, which calls the SSOT.
    ``init.sh::_resolve_python_cmd`` was the historical drift site —
    its old scan-fallback picked ``venv-aaa-fake`` because the bash
    resolver had no metadata-authoritative step. Phase 4 wired init.sh
    through the canonical library; this test pins the convergence.
    """
    daemon_dir, real_venv = _build_fixture_daemon_dir(tmp_path)

    results = {
        "paths_py_cli": _resolve_via_paths_py_cli(daemon_dir),
        "venv_resolver_sh": _resolve_via_install_venv_resolver(daemon_dir),
        "skill_resolve_venv_sh": _resolve_via_skill_resolver(daemon_dir),
        "venv_include_bash": _resolve_via_venv_include(daemon_dir),
        "init_sh_resolver": _resolve_via_init_sh(daemon_dir, tmp_path),
    }
    venv_dirs = {site: _normalise(p) for site, p in results.items()}

    unique = set(venv_dirs.values())
    assert unique == {real_venv}, (
        "Parity matrix violation: not every site picked the metadata-authoritative "
        f"venv {real_venv}. Per-site picks: {venv_dirs}. "
        f"Expected all sites to agree on {real_venv}; sites that disagree are "
        "missing the Plan 00100 Task 3.5 metadata-authoritative precedence step."
    )
