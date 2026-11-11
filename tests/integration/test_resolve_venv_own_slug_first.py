"""GitHub #199: a venv slugged for THIS project path is probed before a sibling view's.

One checkout visible at two paths builds one venv per path, both with the same
``lock_hash``. The sibling view's venv ties at rank 0, can sort first, and used
to print a spurious ``failed to run`` warning when another Python built it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.paths import (
    _compute_project_lock_hash_stdlib,
    _scan_sort_key,
    project_path_slug,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVE_VENV_SH = REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh"
BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 30

_RUNNING = (sys.version_info.major, sys.version_info.minor)
_OTHER = (_RUNNING[0], _RUNNING[1] + 1 if _RUNNING[1] < 50 else _RUNNING[1] - 1)
_OTHER_VIEW_NAME = "venv-aaa_other_view-py313-00000003"


def _fake_venv(venv_dir: Path, cfg_version: tuple[int, int], lock_hash: str) -> Path:
    """A venv whose interpreter really runs and whose pyvenv.cfg records ``cfg_version``."""
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True)
    py = bin_dir / "python"
    py.symlink_to(os.path.realpath(sys.executable))
    home = Path(os.path.realpath(sys.executable)).parent
    (venv_dir / "pyvenv.cfg").write_text(
        f"home = {home}\nversion_info = {cfg_version[0]}.{cfg_version[1]}.5\n"
    )
    (venv_dir / ".daemon-metadata.json").write_text(
        json.dumps({"python_path": str(py), "lock_hash": lock_hash})
    )
    return py


def _project(root: Path) -> tuple[str, str]:
    """Write the lock-hash inputs; return (lock_hash, own venv directory name)."""
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    lock_hash = _compute_project_lock_hash_stdlib(root)
    assert lock_hash is not None
    return lock_hash, f"venv-{project_path_slug(root)}-py313-00000002"


def _bash_pick(daemon_dir: Path) -> subprocess.CompletedProcess[str]:
    harness = textwrap.dedent(f"""\
        unset HOOKS_DAEMON_PYTHON HOOKS_DAEMON_VENV_PATH
        . "{RESOLVE_VENV_SH}"
        _rv_pick_python "{daemon_dir}"
        """)
    return subprocess.run(
        [BASH, "-c", harness],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )


@pytest.fixture(autouse=True)
def _no_venv_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)


def test_other_views_drifted_venv_is_skipped_without_a_warning(tmp_path: Path) -> None:
    """The #199 reproduction: sibling venv sorts first, drifted, same lock_hash."""
    lock_hash, own_name = _project(tmp_path)
    untracked = tmp_path / "untracked"
    _fake_venv(untracked / _OTHER_VIEW_NAME, _OTHER, lock_hash)
    own = _fake_venv(untracked / own_name, _RUNNING, lock_hash)

    result = _bash_pick(tmp_path)

    assert result.stdout.strip() == str(own)
    assert result.stderr == ""


def test_own_slug_venv_is_probed_before_a_usable_sibling(tmp_path: Path) -> None:
    """Both usable and tied: the own-slug venv wins although the sibling sorts first."""
    lock_hash, own_name = _project(tmp_path)
    untracked = tmp_path / "untracked"
    _fake_venv(untracked / _OTHER_VIEW_NAME, _RUNNING, lock_hash)
    own = _fake_venv(untracked / own_name, _RUNNING, lock_hash)

    assert _bash_pick(tmp_path).stdout.strip() == str(own)


def test_broken_own_slug_venv_still_warns(tmp_path: Path) -> None:
    lock_hash, own_name = _project(tmp_path)
    untracked = tmp_path / "untracked"
    sibling = _fake_venv(untracked / _OTHER_VIEW_NAME, _RUNNING, lock_hash)
    _fake_venv(untracked / own_name, _OTHER, lock_hash)

    result = _bash_pick(tmp_path)

    assert result.stdout.strip() == str(sibling)
    assert "interpreter drift" in result.stderr
    assert own_name in result.stderr


def test_python_sort_key_puts_own_slug_first_among_equal_rank(tmp_path: Path) -> None:
    lock_hash, own_name = _project(tmp_path)
    untracked = tmp_path / "untracked"
    other = untracked / _OTHER_VIEW_NAME
    own = untracked / own_name
    _fake_venv(other, _RUNNING, lock_hash)
    _fake_venv(own, _RUNNING, lock_hash)
    slug = project_path_slug(tmp_path)

    ordered = sorted(sorted([other, own]), key=lambda d: _scan_sort_key(d, lock_hash, slug))

    assert ordered == [own, other]
