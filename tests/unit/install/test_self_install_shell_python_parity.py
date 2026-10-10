"""The shell self-install test agrees with the Python rule on the same layouts (N386).

`daemon/install_layout.is_self_install_mode` is the one Python definition. The
shell cannot call it, so `scripts/install/mode_guard.sh` carries ONE shell
function, `is_self_install_checkout`, which `setup_worktree.sh`,
`health_check.sh` and `detect_self_install_mode` all call. This test runs both
on the same temporary layouts so the pair cannot drift: a directory at the
marker path, a FILE at the marker path, and no marker at all.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Final

import pytest

from claude_code_hooks_daemon.daemon.install_layout import is_self_install_mode

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_MODE_GUARD_SH: Final[Path] = _REPO_ROOT / "scripts" / "install" / "mode_guard.sh"
_TIMEOUT_SECONDS: Final[int] = 30


def _marker_dir(root: Path) -> None:
    (root / "src" / "claude_code_hooks_daemon").mkdir(parents=True)


def _marker_file(root: Path) -> None:
    marker = root / "src" / "claude_code_hooks_daemon"
    marker.parent.mkdir(parents=True)
    marker.write_text("a file, not the source tree", encoding="utf-8")


def _src_is_a_file(root: Path) -> None:
    (root / "src").write_text("src is a file", encoding="utf-8")


def _absent(root: Path) -> None:
    del root


_LAYOUTS: Final[dict[str, Callable[[Path], None]]] = {
    "marker-dir": _marker_dir,
    "file-at-marker": _marker_file,
    "src-is-a-file": _src_is_a_file,
    "marker-absent": _absent,
}


def _shell_says_self_install(root: Path) -> bool:
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; is_self_install_checkout "$2"',
            "_",
            str(_MODE_GUARD_SH),
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr
    return result.returncode == 0


@pytest.mark.parametrize("layout", sorted(_LAYOUTS))
def test_shell_and_python_agree(tmp_path: Path, layout: str) -> None:
    _LAYOUTS[layout](tmp_path)

    assert _shell_says_self_install(tmp_path) is is_self_install_mode(tmp_path)


def test_the_directory_layout_is_a_self_install(tmp_path: Path) -> None:
    """Guards the parity test against agreeing on 'False' everywhere."""
    _marker_dir(tmp_path)

    assert _shell_says_self_install(tmp_path) is True


def test_an_empty_path_is_not_a_self_install() -> None:
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; is_self_install_checkout ""', "_", str(_MODE_GUARD_SH)],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
        check=False,
    )

    assert result.returncode == 1, result.stderr
