"""Every Python site that needs the install mode asks `daemon.install_layout` (N386).

The rule is `install_layout.is_self_install_mode`: the daemon SOURCE DIRECTORY
is present at the project root. Four sites used to keep their own copy, three
of them with `.exists()`, so a FILE at the marker path read as a self-install
there and as a client install everywhere else. These tests pin the behaviour
the one rule gives: a file at the marker path is NOT a self-install.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest

from claude_code_hooks_daemon.daemon.install_layout import get_untracked_dir
from claude_code_hooks_daemon.install.client_validator import ClientInstallValidator
from claude_code_hooks_daemon.utils.ccy_supervisor import daemon_untracked_dir

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
_DEBUG_INFO: Final[Path] = _REPO_ROOT / "scripts" / "debug_info.py"


def _marker_dir(root: Path) -> None:
    (root / "src" / "claude_code_hooks_daemon").mkdir(parents=True)


def _marker_file(root: Path) -> None:
    marker = root / "src" / "claude_code_hooks_daemon"
    marker.parent.mkdir(parents=True)
    marker.write_text("a file, not the source tree", encoding="utf-8")


def _load_debug_info() -> ModuleType:
    spec = importlib.util.spec_from_file_location("debug_info_single_source", _DEBUG_INFO)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _debug_info_untracked(root: Path) -> Path:
    module = _load_debug_info()
    generator = module.DebugInfoGenerator(project_root=root)
    result = generator._untracked_dir()
    assert isinstance(result, Path)
    return result


class TestCcySupervisorUntrackedDir:
    def test_directory_marker_is_self_install(self, tmp_path: Path) -> None:
        _marker_dir(tmp_path)
        assert daemon_untracked_dir(tmp_path) == get_untracked_dir(tmp_path)
        assert daemon_untracked_dir(tmp_path) == tmp_path / "untracked"

    def test_file_at_the_marker_path_is_a_client_install(self, tmp_path: Path) -> None:
        _marker_file(tmp_path)
        assert daemon_untracked_dir(tmp_path) == get_untracked_dir(tmp_path)
        assert daemon_untracked_dir(tmp_path) == tmp_path / ".claude" / "hooks-daemon" / "untracked"


class TestClientValidatorRefusesOnlyTheDaemonRepo:
    def test_directory_marker_is_refused(self, tmp_path: Path) -> None:
        _marker_dir(tmp_path)
        assert ClientInstallValidator._check_not_daemon_repo(tmp_path).passed is False

    def test_file_at_the_marker_path_is_not_the_daemon_repo(self, tmp_path: Path) -> None:
        _marker_file(tmp_path)
        assert ClientInstallValidator._check_not_daemon_repo(tmp_path).passed is True

    def test_absent_marker_passes(self, tmp_path: Path) -> None:
        assert ClientInstallValidator._check_not_daemon_repo(tmp_path).passed is True


class TestDebugInfoUntrackedDir:
    """`scripts/debug_info.py` runs on a bare interpreter, so it loads the rule by path."""

    @pytest.mark.parametrize("layout", ["dir", "file", "absent"])
    def test_agrees_with_the_canonical_rule(self, tmp_path: Path, layout: str) -> None:
        if layout == "dir":
            _marker_dir(tmp_path)
        elif layout == "file":
            _marker_file(tmp_path)
        assert _debug_info_untracked(tmp_path) == get_untracked_dir(tmp_path)

    def test_loaded_without_importing_the_package(self, tmp_path: Path) -> None:
        """The by-path load must not need `claude_code_hooks_daemon` importable."""
        import subprocess
        import sys

        _marker_dir(tmp_path)
        code = (
            "import importlib.util, sys\n"
            f"spec = importlib.util.spec_from_file_location('di', {str(_DEBUG_INFO)!r})\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            f"from pathlib import Path\n"
            f"g = m.DebugInfoGenerator(project_root=Path({str(tmp_path)!r}))\n"
            "print(g._untracked_dir())\n"
            "assert 'claude_code_hooks_daemon' not in sys.modules or "
            "sys.modules['claude_code_hooks_daemon'].__file__ is None\n"
        )
        result = subprocess.run(
            [sys.executable, "-S", "-I", "-c", code],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == str(tmp_path / "untracked")
