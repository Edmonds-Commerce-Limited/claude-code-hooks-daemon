"""Plan 00466 N37 — the venv resolver's hot-path cache never carries an override.

``scripts/lib/resolve_venv.sh`` caches its answer in
``untracked/.python-cmd-cache``. Written from ANY resolution, including one
steered by ``HOOKS_DAEMON_VENV_PATH`` or run on a ``HOOKS_DAEMON_PYTHON``
interpreter, and served to every later call, an override set once goes on
answering for calls that set none, and a call that sets an override is handed
the cached, un-overridden answer. Plan 00376 met the first half as a gate
bypass: a forged venv named once was read back as the installed one.

The rule pinned here: an override-derived answer is never cached, a call with
an override never reads the cache, and a cached entry is only served when it
is one of the daemon's own ``untracked/venv-*`` interpreters.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVE_VENV_SH = REPO_ROOT / "scripts" / "lib" / "resolve_venv.sh"
FINGERPRINT_HELPER = REPO_ROOT / "scripts" / "install" / "python_fingerprint.sh"
BASH = shutil.which("bash") or "/bin/bash"
CACHE_NAME = ".python-cmd-cache"
_TIMEOUT_SECONDS = 60


def _daemon_with_keyed_venv(tmp_path: Path) -> tuple[Path, Path]:
    """A daemon dir whose fingerprint-keyed venv is the honest answer."""
    daemon_dir = tmp_path / "daemon"
    install_dir = daemon_dir / "scripts" / "install"
    install_dir.mkdir(parents=True)
    (install_dir / "python_fingerprint.sh").symlink_to(FINGERPRINT_HELPER)
    venv_python = (
        daemon_dir / "untracked" / f"venv-{python_venv_fingerprint(daemon_dir)}" / "bin" / "python"
    )
    venv_python.parent.mkdir(parents=True)
    venv_python.symlink_to(sys.executable)
    return daemon_dir, venv_python


def _forged_venv(tmp_path: Path) -> Path:
    """A venv outside the daemon, as an override would name it."""
    forged_python = tmp_path / "forged" / "bin" / "python"
    forged_python.parent.mkdir(parents=True)
    forged_python.symlink_to(sys.executable)
    return forged_python


def _fake_interpreter(tmp_path: Path, answer: Path) -> Path:
    """An interpreter that answers every resolve-venv call with ``answer``."""
    fake = tmp_path / "fake-python"
    fake.write_text(
        "#!/bin/bash\n"
        'for arg in "$@"; do\n'
        f'    if [ "$arg" = "resolve-venv" ]; then echo "{answer}"; exit 0; fi\n'
        "done\n"
        f'exec "{sys.executable}" "$@"\n'
    )
    fake.chmod(0o755)
    return fake


def _resolve(daemon_dir: Path, **overrides: str) -> str:
    """Call the public ``resolve_venv_python`` with only the given overrides set."""
    env = os.environ.copy()
    env.pop("HOOKS_DAEMON_PYTHON", None)
    env.pop("HOOKS_DAEMON_VENV_PATH", None)
    env.update(overrides)
    result = subprocess.run(
        [BASH, "-c", f'. "{RESOLVE_VENV_SH}" && resolve_venv_python "{daemon_dir}"'],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, f"resolve failed: {result.stderr}"
    return result.stdout.strip()


def test_a_venv_path_override_is_not_served_to_a_later_call(tmp_path: Path) -> None:
    daemon_dir, venv_python = _daemon_with_keyed_venv(tmp_path)
    forged = _forged_venv(tmp_path)

    assert _resolve(daemon_dir, HOOKS_DAEMON_VENV_PATH=str(forged.parent.parent)) == str(forged)
    assert _resolve(daemon_dir) == str(venv_python)


def test_an_interpreter_override_is_not_served_to_a_later_call(tmp_path: Path) -> None:
    daemon_dir, venv_python = _daemon_with_keyed_venv(tmp_path)
    forged = _forged_venv(tmp_path)
    fake = _fake_interpreter(tmp_path, forged)

    assert _resolve(daemon_dir, HOOKS_DAEMON_PYTHON=str(fake)) == str(forged)
    assert _resolve(daemon_dir) == str(venv_python)


def test_an_override_call_is_not_served_the_cached_answer(tmp_path: Path) -> None:
    daemon_dir, venv_python = _daemon_with_keyed_venv(tmp_path)
    forged = _forged_venv(tmp_path)

    assert _resolve(daemon_dir) == str(venv_python)
    assert (daemon_dir / "untracked" / CACHE_NAME).is_file(), "the plain call caches"
    assert _resolve(daemon_dir, HOOKS_DAEMON_VENV_PATH=str(forged.parent.parent)) == str(forged)


def test_a_cache_naming_a_foreign_interpreter_is_not_served(tmp_path: Path) -> None:
    """A cache an older resolver wrote from an override is ignored, not trusted."""
    daemon_dir, venv_python = _daemon_with_keyed_venv(tmp_path)
    forged = _forged_venv(tmp_path)
    untracked = daemon_dir / "untracked"
    plant = subprocess.run(
        [
            BASH,
            "-c",
            f'. "{RESOLVE_VENV_SH}" && : > "{untracked / CACHE_NAME}" '
            f'&& m="$(_rv_dir_mtime "{untracked}")" '
            f'&& printf "%s %s\\n" "$m" "{forged}" > "{untracked / CACHE_NAME}"',
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )
    assert plant.returncode == 0, plant.stderr

    assert _resolve(daemon_dir) == str(venv_python)
