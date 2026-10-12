"""Plan 00474 N434: the bash scan ranks candidates like ``paths.py`` does.

After an interpreter patch update no venv matches the fingerprint, so
``_rv_pick_python`` falls to its scan. A legacy un-slugged venv sorts first
and carries stale metadata; the venv built for the current source must win.
The ranking is: metadata ``lock_hash`` equal to the current source, then other
slugged venvs, then legacy un-slugged venvs. The bash side computes the hash
with ``sha256sum``/``shasum`` and reads the JSON with ``grep``: no Python spawn.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.paths import (
    _compute_project_lock_hash_stdlib,
    project_path_slug,
    resolve_existing_venv_python,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVE_VENV_SH = REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh"
BASH = shutil.which("bash") or "/bin/bash"
_TIMEOUT_SECONDS = 30
_LEGACY = "venv-py311-00000001"
_SLUGGED = "venv-zslug-py313-00000002"


def _make_venv(venv_dir: Path, lock_hash: str | None) -> Path:
    """A runnable fake venv, optionally stamped with ``.daemon-metadata.json``."""
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True)
    py = bin_dir / "python"
    py.write_text("#!/bin/bash\nexit 0\n")
    py.chmod(0o755)
    if lock_hash is not None:
        (venv_dir / ".daemon-metadata.json").write_text(
            json.dumps({"python_path": str(py), "lock_hash": lock_hash})
        )
    return py


def _project_with_sources(root: Path, *, uv_lock: bool = False) -> str:
    """Write the lock-hash inputs under ``root`` and return the stdlib hash."""
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    if uv_lock:
        (root / "uv.lock").write_text("version = 1\n")
    lock_hash = _compute_project_lock_hash_stdlib(root)
    assert lock_hash is not None
    return lock_hash


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


@pytest.mark.parametrize("uv_lock", [False, True])
def test_bash_lock_hash_match_beats_lexically_first_legacy(tmp_path: Path, uv_lock: bool) -> None:
    """The issue's layout: legacy v1 venv sorts first, slugged v2 venv matches."""
    current = _project_with_sources(tmp_path, uv_lock=uv_lock)
    untracked = tmp_path / "untracked"
    _make_venv(untracked / _LEGACY, "sha256:stale")
    expected = _make_venv(untracked / _SLUGGED, current)

    result = _bash_pick(tmp_path)

    assert result.stdout.strip() == str(expected)


def test_bash_slugged_beats_legacy_when_no_lock_hash_matches(tmp_path: Path) -> None:
    _project_with_sources(tmp_path)
    untracked = tmp_path / "untracked"
    _make_venv(untracked / _LEGACY, "sha256:stale")
    expected = _make_venv(untracked / _SLUGGED, "sha256:also-stale")

    assert _bash_pick(tmp_path).stdout.strip() == str(expected)


def test_bash_slugged_beats_legacy_without_project_sources(tmp_path: Path) -> None:
    untracked = tmp_path / "untracked"
    _make_venv(untracked / _LEGACY, None)
    expected = _make_venv(untracked / _SLUGGED, None)

    assert _bash_pick(tmp_path).stdout.strip() == str(expected)


def test_bash_legacy_alone_is_still_returned(tmp_path: Path) -> None:
    _project_with_sources(tmp_path)
    expected = _make_venv(tmp_path / "untracked" / _LEGACY, "sha256:stale")

    assert _bash_pick(tmp_path).stdout.strip() == str(expected)


def test_bash_matching_venv_that_cannot_run_falls_through_to_the_next_rank(
    tmp_path: Path,
) -> None:
    """The run-probe still applies to the best-ranked candidate."""
    current = _project_with_sources(tmp_path)
    untracked = tmp_path / "untracked"
    broken = _make_venv(untracked / _SLUGGED, current)
    broken.write_text("#!/bin/bash\nexit 3\n")
    expected = _make_venv(untracked / _LEGACY, "sha256:stale")

    result = _bash_pick(tmp_path)

    assert result.stdout.strip() == str(expected)
    assert "failed to run" in result.stderr


def test_bash_and_python_resolvers_agree_on_the_issue_layout(tmp_path: Path) -> None:
    current = _project_with_sources(tmp_path)
    untracked = tmp_path / "untracked"
    _make_venv(untracked / _LEGACY, "sha256:stale")
    # The Python resolver also checks the slug, so the matching venv is named for this root.
    matching = untracked / f"venv-{project_path_slug(tmp_path)}-py313-00000002"
    _make_venv(matching, current)

    assert _bash_pick(tmp_path).stdout.strip() == str(resolve_existing_venv_python(tmp_path))
