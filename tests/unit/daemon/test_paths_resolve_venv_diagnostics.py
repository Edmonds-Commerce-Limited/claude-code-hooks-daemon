"""Unit tests for Plan 00100 Task 2.3: the diagnostic resolver + CLI dispatcher.

These exercise :func:`resolve_existing_venv_python_with_diagnostics` and the
argparse entry point directly — in-process — so coverage is captured for
``src/claude_code_hooks_daemon/daemon/paths.py``. Integration-layer
subprocess tests in ``tests/integration/test_paths_resolve_venv_cli.py``
verify the shell contract; this file verifies the Python internals.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.paths import (
    _cli_resolve_venv,
    main,
    python_venv_fingerprint,
    resolve_existing_venv_python_with_diagnostics,
)


def _make_fake_venv(venv_dir: Path) -> Path:
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    py = bin_dir / "python"
    py.write_text("#!/bin/bash\necho fake\n")
    py.chmod(py.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return py


def _write_pyproject(daemon_dir: Path, content: str = "[project]\nname = 'x'\n") -> Path:
    daemon_dir.mkdir(parents=True, exist_ok=True)
    path = daemon_dir / "pyproject.toml"
    path.write_text(content)
    return path


def _compute_test_lock_hash(daemon_dir: Path) -> str:
    """Tiny stdlib helper mirroring the stdlib lock-hash computation."""
    import hashlib

    hasher = hashlib.sha256()
    hasher.update((daemon_dir / "pyproject.toml").read_bytes())
    uv_lock = daemon_dir / "uv.lock"
    if uv_lock.is_file():
        hasher.update(uv_lock.read_bytes())
    else:
        hasher.update(b"\x00no-uv-lock\x00")
    return f"sha256:{hasher.hexdigest()}"


def _write_metadata(
    venv_dir: Path,
    *,
    python_path: str,
    lock_hash: str,
    fingerprint: str = "py311-testfake",
    daemon_version: str = "v3.8.0",
    written_at: str = "2026-04-24T00:00:00Z",
) -> Path:
    """Write a ``.daemon-metadata.json`` file directly via stdlib JSON.

    Bypasses the Pydantic writer so these unit tests don't require the
    daemon's install-time helper. Metadata contents exactly mirror the
    Pydantic schema field names.
    """
    venv_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "python_path": python_path,
        "fingerprint": fingerprint,
        "lock_hash": lock_hash,
        "daemon_version": daemon_version,
        "written_at": written_at,
    }
    metadata_path = venv_dir / ".daemon-metadata.json"
    metadata_path.write_text(json.dumps(meta))
    return metadata_path


def _make_fake_venv_python3_only(venv_dir: Path) -> Path:
    """Create a fake venv that only has ``bin/python3`` (no ``bin/python``).

    Some bash callers (notably ``scripts/venv-include.bash`` and its tests)
    create venvs where only ``bin/python3`` exists. The SSOT must accept
    either ``bin/python`` or ``bin/python3`` so every caller agrees on
    whether a venv is usable.
    """
    bin_dir = venv_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    py3 = bin_dir / "python3"
    py3.write_text("#!/bin/bash\necho fake-py3\n")
    py3.chmod(py3.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return py3


class TestDiagnosticsHelper:
    def test_override_hit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        override = tmp_path / "override"
        py = _make_fake_venv(override)
        monkeypatch.setenv("HOOKS_DAEMON_VENV_PATH", str(override))

        resolved, steps = resolve_existing_venv_python_with_diagnostics(tmp_path / "daemon")
        assert resolved == py
        assert any("step 1" in s and "OK" in s for s in steps)

    def test_override_set_but_missing_falls_through_and_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        daemon_dir = tmp_path / "daemon"
        daemon_dir.mkdir()
        monkeypatch.setenv("HOOKS_DAEMON_VENV_PATH", str(tmp_path / "nonexistent"))

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved is None
        assert any("step 1" in s and "missing" in s for s in steps)
        assert any(s.startswith("step 5") for s in steps)

    def test_fingerprint_keyed_hit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        fp = python_venv_fingerprint(daemon_dir)
        keyed = daemon_dir / "untracked" / f"venv-{fp}"
        py = _make_fake_venv(keyed)

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved == py
        assert any("step 3" in s and "OK" in s for s in steps)

    def test_scan_fallback_hit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        foreign = daemon_dir / "untracked" / "venv-py999-deadbeef"
        py = _make_fake_venv(foreign)

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved == py
        assert any("step 4" in s and "scan-fallback hit" in s for s in steps)

    def test_scan_finds_candidates_but_none_executable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        broken = daemon_dir / "untracked" / "venv-py999-broken"
        (broken / "bin").mkdir(parents=True)
        py = broken / "bin" / "python"
        py.write_text("#!/bin/bash\n")
        # Deliberately NOT executable.

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved is None
        scan_step = next(s for s in steps if s.startswith("step 4"))
        assert "no executable" in scan_step

    def test_scan_fallback_no_untracked_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon-missing"

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved is None
        scan_step = next(s for s in steps if s.startswith("step 4"))
        assert "does not exist" in scan_step

    def test_scan_untracked_exists_but_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        (daemon_dir / "untracked").mkdir(parents=True)

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved is None
        scan_step = next(s for s in steps if s.startswith("step 4"))
        assert "no venv-*" in scan_step

    def test_legacy_fallback_hit(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        legacy = daemon_dir / "untracked" / "venv"
        py = _make_fake_venv(legacy)

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved == py
        assert any("step 5" in s and "OK" in s for s in steps)


class TestCliDispatcher:
    def test_main_invokes_resolve_venv(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        fp = python_venv_fingerprint(daemon_dir)
        py = _make_fake_venv(daemon_dir / "untracked" / f"venv-{fp}")

        exit_code = main(["resolve-venv", "--daemon-dir", str(daemon_dir)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == str(py)
        assert captured.err == ""

    def test_main_failure_emits_trace_on_stderr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon-empty"

        exit_code = main(["resolve-venv", "--daemon-dir", str(daemon_dir)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        for marker in ("step 1", "step 2", "step 3", "step 4", "step 5"):
            assert marker in captured.err

    def test_main_defaults_daemon_dir_to_cwd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        fp = python_venv_fingerprint(daemon_dir)
        py = _make_fake_venv(daemon_dir / "untracked" / f"venv-{fp}")
        monkeypatch.chdir(daemon_dir)

        exit_code = main(["resolve-venv"])
        assert exit_code == 0
        assert capsys.readouterr().out.strip() == str(py)

    def test_cli_helper_is_idempotent_for_namespace_arg(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import argparse

        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        fp = python_venv_fingerprint(daemon_dir)
        py = _make_fake_venv(daemon_dir / "untracked" / f"venv-{fp}")

        ns = argparse.Namespace(daemon_dir=str(daemon_dir))
        rc = _cli_resolve_venv(ns)
        assert rc == 0
        assert capsys.readouterr().out.strip() == str(py)

    def test_module_invokes_sys_exit_when_run_as_script(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exercise the ``if __name__ == '__main__'`` guard via runpy.

        runpy doesn't execute the ``__main__`` block because the module is
        being *imported* under a non-``__main__`` name, so we simulate it by
        calling :func:`main` and verifying its integer return is suitable
        for :func:`sys.exit`.
        """
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        exit_code = main(["resolve-venv", "--daemon-dir", str(tmp_path / "empty")])
        assert isinstance(exit_code, int)
        assert exit_code == 1


class TestPython3OnlyAcceptance:
    """Real venvs have both ``bin/python`` and ``bin/python3`` symlinks, but
    fake venvs in bash callers (notably ``scripts/venv-include.bash``) often
    create only ``bin/python3``. The SSOT must accept either so there is ONE
    authoritative notion of "is this a usable venv"."""

    def test_fingerprint_keyed_python3_only_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        fp = python_venv_fingerprint(daemon_dir)
        keyed = daemon_dir / "untracked" / f"venv-{fp}"
        py3 = _make_fake_venv_python3_only(keyed)

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved == py3, "fingerprint-keyed venv with only bin/python3 must be accepted"
        assert any("step 3" in s and "OK" in s for s in steps)

    def test_scan_fallback_python3_only_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        foreign = daemon_dir / "untracked" / "venv-py999-deadbeef"
        py3 = _make_fake_venv_python3_only(foreign)

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved == py3, "scan fallback must accept foreign venv with only bin/python3"
        assert any("step 4" in s and "scan-fallback hit" in s for s in steps)

    def test_legacy_python3_only_is_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        legacy = daemon_dir / "untracked" / "venv"
        py3 = _make_fake_venv_python3_only(legacy)

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved == py3, "legacy venv with only bin/python3 must be accepted"
        assert any("step 5" in s and "OK" in s for s in steps)

    def test_bin_python_preferred_when_both_exist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When both symlinks exist, ``bin/python`` is preferred — matches the
        existing contract consumed by ``scripts/install/venv_resolver.sh`` and
        ``src/claude_code_hooks_daemon/skills/hooks-daemon/scripts/_resolve-venv.sh``."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        fp = python_venv_fingerprint(daemon_dir)
        keyed = daemon_dir / "untracked" / f"venv-{fp}"
        py = _make_fake_venv(keyed)
        _make_fake_venv_python3_only(keyed)  # adds bin/python3 too

        resolved, _ = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved == py, "bin/python must be preferred when both exist"


class TestFallbackTargetFlag:
    """The ``--fallback-target`` flag turns the CLI from 'resolve existing'
    into 'resolve or suggest creation path'. Consumed by
    ``scripts/venv-include.bash`` whose ``ensure_venv`` needs a target path
    on fresh projects before any venv has been created."""

    def test_flag_prints_fingerprint_keyed_path_when_nothing_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        fp = python_venv_fingerprint(daemon_dir)
        expected = daemon_dir / "untracked" / f"venv-{fp}" / "bin" / "python"

        exit_code = main(["resolve-venv", "--daemon-dir", str(daemon_dir), "--fallback-target"])
        assert exit_code == 0
        assert capsys.readouterr().out.strip() == str(expected)

    def test_flag_returns_existing_venv_when_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The flag does NOT override normal resolution — it only changes
        miss-behaviour. An existing venv must still win."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        fp = python_venv_fingerprint(daemon_dir)
        keyed = daemon_dir / "untracked" / f"venv-{fp}"
        py = _make_fake_venv(keyed)

        exit_code = main(["resolve-venv", "--daemon-dir", str(daemon_dir), "--fallback-target"])
        assert exit_code == 0
        assert capsys.readouterr().out.strip() == str(py)

    def test_flag_respects_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        override = tmp_path / "override"
        py = _make_fake_venv(override)
        monkeypatch.setenv("HOOKS_DAEMON_VENV_PATH", str(override))

        exit_code = main(
            [
                "resolve-venv",
                "--daemon-dir",
                str(tmp_path / "daemon"),
                "--fallback-target",
            ]
        )
        assert exit_code == 0
        assert capsys.readouterr().out.strip() == str(py)

    def test_without_flag_exit_code_is_still_1_on_miss(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression guard: the flag is opt-in. Omitting it MUST keep the
        previous contract so existing callers (``venv_resolver.sh``,
        ``_resolve-venv.sh``) continue to surface 'no venv found' diagnostics."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        exit_code = main(["resolve-venv", "--daemon-dir", str(tmp_path / "empty")])
        assert exit_code == 1


class TestMetadataDrivenResolution:
    """Plan 00100 Task 3.4: the resolver reads ``.daemon-metadata.json`` and
    uses ``python_path`` authoritatively when ``lock_hash`` matches the
    current project state. Fingerprint is never recomputed for lookup —
    metadata discovery is by JSON read, not by directory-name matching."""

    def test_metadata_match_returns_python_path_authoritatively(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A venv with valid metadata + matching lock_hash resolves via
        ``metadata.python_path`` — not via ``bin/python`` existence."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        _write_pyproject(daemon_dir)
        lock_hash = _compute_test_lock_hash(daemon_dir)

        venv = daemon_dir / "untracked" / "venv-py999-deadbeef"
        py = _make_fake_venv(venv)
        _write_metadata(venv, python_path=str(py), lock_hash=lock_hash)

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved == py
        assert any(
            "step 2" in s and "metadata" in s.lower() and "OK" in s for s in steps
        ), f"expected step 2 metadata OK in trace; got: {steps}"

    def test_metadata_match_preferred_over_fingerprint_keyed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When both a metadata-bearing venv and a fingerprint-keyed legacy
        venv exist, metadata wins (step 2 over step 3)."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        _write_pyproject(daemon_dir)
        lock_hash = _compute_test_lock_hash(daemon_dir)

        fp = python_venv_fingerprint(daemon_dir)
        legacy_keyed = daemon_dir / "untracked" / f"venv-{fp}"
        _make_fake_venv(legacy_keyed)  # no metadata — fallback target

        metadata_venv = daemon_dir / "untracked" / "venv-py999-freshmeta"
        py_meta = _make_fake_venv(metadata_venv)
        _write_metadata(metadata_venv, python_path=str(py_meta), lock_hash=lock_hash)

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved == py_meta, "metadata-bearing venv must win over fingerprint-keyed legacy"
        assert any(
            "step 2" in s and "OK" in s for s in steps
        ), f"trace must show step 2 metadata hit; got: {steps}"

    def test_metadata_lock_hash_mismatch_is_skipped_as_stale(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A venv whose metadata.lock_hash does NOT match the current project
        state is stale — resolver logs it, skips it, falls through."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        _write_pyproject(daemon_dir)

        venv = daemon_dir / "untracked" / "venv-py999-stale"
        _make_fake_venv(venv)
        bogus = "sha256:" + "0" * 64
        _write_metadata(venv, python_path=str(venv / "bin" / "python"), lock_hash=bogus)

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        # No OTHER venv exists so the scan fallback can still hit this
        # broken venv's bin/python — that's fine. The step-2 diagnostic
        # MUST mention stale.
        stale_step = next(
            (s for s in steps if s.startswith("step 2") and "stale" in s.lower()),
            None,
        )
        assert stale_step is not None, f"expected step 2 stale diagnostic; got: {steps}"
        # Scan fallback still finds bin/python since 3.4 has not yet
        # removed legacy behaviour (that is Task 3.5).
        assert resolved == venv / "bin" / "python"

    def test_metadata_absent_falls_through_to_fingerprint_keyed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No metadata anywhere → step 2 reports no match, step 3
        fingerprint-keyed (legacy) still resolves (Task 3.5 tightens this)."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        _write_pyproject(daemon_dir)
        fp = python_venv_fingerprint(daemon_dir)
        keyed = daemon_dir / "untracked" / f"venv-{fp}"
        py = _make_fake_venv(keyed)  # no metadata written

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved == py
        assert any(
            "step 2" in s and ("no" in s.lower() or "without" in s.lower()) for s in steps
        ), f"step 2 must announce no-metadata-found; got: {steps}"
        assert any("step 3" in s and "OK" in s for s in steps)

    def test_metadata_python_path_executable_check(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If metadata matches but ``python_path`` is not executable, step 2
        reports the issue and falls through. (Task 3.6 will add recovery.)"""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        _write_pyproject(daemon_dir)
        lock_hash = _compute_test_lock_hash(daemon_dir)

        venv = daemon_dir / "untracked" / "venv-py999-ghost"
        venv.mkdir(parents=True)
        missing = "/nonexistent/fake/python3.13"
        _write_metadata(venv, python_path=missing, lock_hash=lock_hash)

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved is None
        step2 = next(s for s in steps if s.startswith("step 2"))
        assert (
            "missing" in step2.lower() or "not executable" in step2.lower()
        ), f"step 2 must report missing python_path; got: {step2}"

    def test_metadata_malformed_json_falls_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Malformed metadata JSON is treated as absent — resolver never
        raises; it just skips to step 3."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        _write_pyproject(daemon_dir)

        venv = daemon_dir / "untracked" / "venv-py999-bad"
        py = _make_fake_venv(venv)
        (venv / ".daemon-metadata.json").write_text("{not valid json")

        resolved, _ = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        # Scan fallback still picks up bin/python.
        assert resolved == py

    def test_metadata_missing_required_keys_falls_through(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Metadata missing ``python_path`` or ``lock_hash`` → treated as absent."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"
        _write_pyproject(daemon_dir)

        venv = daemon_dir / "untracked" / "venv-py999-partial"
        py = _make_fake_venv(venv)
        (venv / ".daemon-metadata.json").write_text('{"fingerprint": "x"}')

        resolved, _ = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        assert resolved == py

    def test_metadata_step_runs_even_without_pyproject(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When pyproject.toml does not exist under daemon_dir, we cannot
        compute a current lock_hash for comparison — step 2 must gracefully
        announce that and fall through, never raise."""
        monkeypatch.delenv("HOOKS_DAEMON_VENV_PATH", raising=False)
        daemon_dir = tmp_path / "daemon"  # no pyproject.toml

        venv = daemon_dir / "untracked" / "venv-py999-orphan"
        py = _make_fake_venv(venv)
        _write_metadata(venv, python_path=str(py), lock_hash="sha256:" + "f" * 64)

        resolved, steps = resolve_existing_venv_python_with_diagnostics(daemon_dir)
        # Scan fallback still hits bin/python.
        assert resolved == py
        step2 = next(s for s in steps if s.startswith("step 2"))
        assert (
            "pyproject" in step2.lower() or "no lock" in step2.lower()
        ), f"step 2 must mention inability to compute current lock_hash; got: {step2}"
