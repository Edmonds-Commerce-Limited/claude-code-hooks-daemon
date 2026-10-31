"""Plan 00555 Task 2.4: a start failure names what is wrong with the venv.

The diagnosis is needed exactly when the venv is broken, so it is stdlib-only
and judges the venv by running ITS interpreter. Fixtures: a venv whose
``bin/python`` is the running interpreter (so it launches) and whose
``pyvenv.cfg`` declares the minor the test chooses, with or without the
matching ``lib/pythonX.Y/site-packages``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon import paths
from claude_code_hooks_daemon.daemon.paths import diagnose_venv_start

_RUNNING = (sys.version_info.major, sys.version_info.minor)
_OTHER = (_RUNNING[0], _RUNNING[1] + 1)


def _venv(venv_dir: Path, cfg_version: tuple[int, int], *, with_package: bool) -> Path:
    """A venv whose interpreter is the running one and whose cfg says ``cfg_version``."""
    (venv_dir / "bin").mkdir(parents=True)
    (venv_dir / "bin" / "python").symlink_to(os.path.realpath(sys.executable))
    (venv_dir / "pyvenv.cfg").write_text(
        f"home = {Path(os.path.realpath(sys.executable)).parent}\n"
        f"version_info = {cfg_version[0]}.{cfg_version[1]}.5\n"
    )
    site_packages = venv_dir / "lib" / f"python{cfg_version[0]}.{cfg_version[1]}" / "site-packages"
    site_packages.mkdir(parents=True)
    if with_package:
        package = site_packages / "claude_code_hooks_daemon"
        package.mkdir()
        (package / "__init__.py").write_text("")
    return venv_dir


class TestHealthyVenv:
    def test_says_healthy_and_names_both_versions(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path / "v", _RUNNING, with_package=True)
        result = diagnose_venv_start(venv, tmp_path / "daemon")
        text = "\n".join(result.lines)
        assert result.healthy is True
        assert f"{_RUNNING[0]}.{_RUNNING[1]}" in text
        assert "site-packages on sys.path: yes" in text
        assert "claude_code_hooks_daemon importable: yes" in text
        assert "repair" not in text


class TestDriftedVenv:
    def test_names_both_versions_and_reports_site_packages_absent(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path / "v", _OTHER, with_package=True)
        result = diagnose_venv_start(venv, tmp_path / "daemon")
        text = "\n".join(result.lines)
        assert result.healthy is False
        assert f"interpreter version: {_RUNNING[0]}.{_RUNNING[1]}" in text
        assert f"pyvenv.cfg version_info: {_OTHER[0]}.{_OTHER[1]}" in text
        assert "site-packages on sys.path: no" in text
        assert "claude_code_hooks_daemon importable: no" in text

    def test_fix_is_the_repair_verb_not_uv_sync(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path / "v", _OTHER, with_package=True)
        daemon_dir = tmp_path / "daemon"
        text = "\n".join(diagnose_venv_start(venv, daemon_dir).lines)
        assert f"{daemon_dir}/bin/hooks-daemon repair" in text
        assert "uv sync" not in text


class TestPackageMissing:
    def test_matching_version_but_no_package_reports_site_packages_present(
        self, tmp_path: Path
    ) -> None:
        venv = _venv(tmp_path / "v", _RUNNING, with_package=False)
        result = diagnose_venv_start(venv, tmp_path / "daemon")
        text = "\n".join(result.lines)
        assert result.healthy is False
        assert "site-packages on sys.path: yes" in text
        assert "claude_code_hooks_daemon importable: no" in text
        assert "hooks-daemon repair" in text


class TestUnrunnableVenv:
    def test_missing_interpreter_is_reported_with_the_fix(self, tmp_path: Path) -> None:
        venv = tmp_path / "v"
        venv.mkdir()
        (venv / "pyvenv.cfg").write_text("version_info = 3.11.5\n")
        result = diagnose_venv_start(venv, tmp_path / "daemon")
        text = "\n".join(result.lines)
        assert result.healthy is False
        assert "interpreter: cannot run" in text
        assert "pyvenv.cfg version_info: 3.11" in text
        assert "hooks-daemon repair" in text


class TestCli:
    def test_diagnose_venv_prints_lines_and_exits_1_when_unhealthy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        venv = _venv(tmp_path / "v", _OTHER, with_package=True)
        rc = paths.main(
            ["diagnose-venv", "--daemon-dir", str(tmp_path / "daemon"), "--venv-dir", str(venv)]
        )
        assert rc == 1
        assert "site-packages on sys.path: no" in capsys.readouterr().out

    def test_without_venv_dir_diagnoses_every_untracked_venv(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        daemon_dir = tmp_path / "daemon"
        _venv(daemon_dir / "untracked" / "venv-a", _OTHER, with_package=True)
        _venv(daemon_dir / "untracked" / "venv-b", _RUNNING, with_package=True)
        rc = paths.main(["diagnose-venv", "--daemon-dir", str(daemon_dir)])
        out = capsys.readouterr().out
        assert rc == 1
        assert "venv-a" in out
        assert "venv-b" in out

    def test_no_venv_at_all_says_so_and_names_the_fix(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        rc = paths.main(["diagnose-venv", "--daemon-dir", str(daemon_dir)])
        out = capsys.readouterr().out
        assert rc == 1
        assert "no venv found" in out
        assert f"{daemon_dir}/bin/hooks-daemon repair" in out
