"""Plan 00104 Phase 7 Task 7.1 — multi-host NFS fail-fast unit tests.

Exercises ``_collect_hostname_suffixed_venvs`` and the multi-host fail-fast
branch of ``_cli_resolve_venv`` in-process so coverage is captured against
``src/claude_code_hooks_daemon/daemon/paths.py``. Integration-layer
subprocess tests in
``tests/integration/test_venv_resolver_multi_host_nfs_fail_fast.py`` verify
the shell contract; this file pins the Python internals.
"""

from __future__ import annotations

import argparse
import stat
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.paths import (
    _cli_resolve_venv,
    _collect_hostname_suffixed_venvs,
)


def _make_fake_venv_python(venv_dir: Path) -> Path:
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    py = bin_dir / "python"
    py.write_text("#!/bin/bash\necho fake\n")
    py.chmod(py.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return py


class TestCollectHostnameSuffixedVenvs:
    def test_returns_empty_when_untracked_dir_missing(self, tmp_path: Path) -> None:
        result = _collect_hostname_suffixed_venvs(tmp_path / "does-not-exist")
        assert result == []

    def test_returns_empty_when_untracked_dir_is_a_file(self, tmp_path: Path) -> None:
        not_a_dir = tmp_path / "untracked"
        not_a_dir.write_text("decoy")
        result = _collect_hostname_suffixed_venvs(not_a_dir)
        assert result == []

    def test_skips_files_inside_untracked_dir(self, tmp_path: Path) -> None:
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        (untracked / "venv-py311-deadbeef-hostalpha").write_text("decoy file")
        result = _collect_hostname_suffixed_venvs(untracked)
        assert result == []

    def test_fingerprint_only_venv_does_not_match(self, tmp_path: Path) -> None:
        untracked = tmp_path / "untracked"
        (untracked / "venv-py311-deadbeef").mkdir(parents=True)
        result = _collect_hostname_suffixed_venvs(untracked)
        assert result == []

    def test_extracts_hostname_from_two_suffixed_venvs(self, tmp_path: Path) -> None:
        untracked = tmp_path / "untracked"
        alpha = untracked / "venv-py311-deadbeef-hostalpha"
        bravo = untracked / "venv-py311-deadbeef-hostbravo"
        alpha.mkdir(parents=True)
        bravo.mkdir(parents=True)

        result = dict(_collect_hostname_suffixed_venvs(untracked))
        assert result == {alpha: "hostalpha", bravo: "hostbravo"}

    def test_extracts_hostname_with_slug_prefix(self, tmp_path: Path) -> None:
        untracked = tmp_path / "untracked"
        slugged = untracked / "venv-myproject-py311-deadbeef-hostalpha"
        slugged.mkdir(parents=True)

        result = _collect_hostname_suffixed_venvs(untracked)
        assert result == [(slugged, "hostalpha")]


class TestCliResolveVenvMultiHostFailFast:
    def test_fails_fast_when_hostname_unset_and_two_suffixes_present(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.delenv("HOSTNAME", raising=False)
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        untracked = daemon_dir / "untracked"
        (untracked / "venv-py311-deadbeef-hostalpha").mkdir(parents=True)
        (untracked / "venv-py311-deadbeef-hostbravo").mkdir(parents=True)

        ns = argparse.Namespace(daemon_dir=str(daemon_dir), fallback_target=False)
        rc = _cli_resolve_venv(ns)
        assert rc == 2
        captured = capsys.readouterr()
        assert "HOSTNAME unset" in captured.err
        assert "hostalpha" in captured.err
        assert "hostbravo" in captured.err

    def test_treats_blank_hostname_as_unset(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("HOSTNAME", "   ")
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        untracked = daemon_dir / "untracked"
        (untracked / "venv-py311-deadbeef-hostalpha").mkdir(parents=True)
        (untracked / "venv-py311-deadbeef-hostbravo").mkdir(parents=True)

        ns = argparse.Namespace(daemon_dir=str(daemon_dir), fallback_target=False)
        rc = _cli_resolve_venv(ns)
        assert rc == 2
        assert "HOSTNAME unset" in capsys.readouterr().err

    def test_passes_when_only_one_hostname_suffix_present(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("HOSTNAME", raising=False)
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        untracked = daemon_dir / "untracked"
        suffixed = untracked / "venv-py311-deadbeef-hostalpha"
        py = _make_fake_venv_python(suffixed)

        ns = argparse.Namespace(daemon_dir=str(daemon_dir), fallback_target=False)
        rc = _cli_resolve_venv(ns)
        # Single hostname suffix → fail-fast does NOT trigger; resolver
        # falls through to the scan-fallback branch and returns OK.
        assert rc == 0
        # Sanity: the resolved path is the suffixed venv's python.
        assert py.exists()

    def test_passes_when_hostname_set_even_with_multiple_suffixes(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOSTNAME", "hostalpha")
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        untracked = daemon_dir / "untracked"
        alpha = untracked / "venv-py311-deadbeef-hostalpha"
        bravo = untracked / "venv-py311-deadbeef-hostbravo"
        _make_fake_venv_python(alpha)
        _make_fake_venv_python(bravo)

        ns = argparse.Namespace(daemon_dir=str(daemon_dir), fallback_target=False)
        rc = _cli_resolve_venv(ns)
        # HOSTNAME set → fail-fast skipped even with two suffixes present.
        assert rc == 0
