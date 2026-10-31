"""Tests for Plan 00099 Phase 5 venv-management CLI subcommands.

Covers:
- ``cmd_list_venvs``: enumerate ``venv-*/`` under untracked/, with current-env marker
- ``cmd_prune_venvs``: delete stale venvs with --dry-run/--legacy/--all-except-current
- ``cmd_repair`` migration to the fingerprint-keyed venv under the daemon dir
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.paths import python_venv_fingerprint

STALE_HASH = "sha256:" + "0" * 64


def _make_venv(path: Path, stamp_version: str | None = None, lock_hash: str | None = None) -> None:
    """Materialise a fake venv on disk that looks healthy enough for listing.

    ``lock_hash`` writes readable metadata; one that differs from the project's
    makes the venv proven stale, none leaves it UNPROVEN.
    """
    (path / "bin").mkdir(parents=True)
    (path / "bin" / "python").write_text('#!/bin/sh\nexec /usr/bin/python3 "$@"\n')
    (path / "bin" / "python").chmod(0o755)
    (path / "pyvenv.cfg").write_text("home = /usr/bin\n")  # what makes a directory a venv
    if stamp_version is not None:
        (path / ".daemon-version").write_text(stamp_version)
    if lock_hash is not None:
        (path / ".daemon-metadata.json").write_text(
            json.dumps({"python_path": str(path / "bin" / "python"), "lock_hash": lock_hash})
        )


def _mark_self_install(project_root: Path) -> None:
    """Stamp ``project_root`` with the self-install sentinel.

    ``_daemon_untracked_dir`` uses the presence of ``src/claude_code_hooks_daemon/``
    at the project root to route venv lookups to ``untracked/`` instead of
    ``.claude/hooks-daemon/untracked/``.
    """
    (project_root / "src" / "claude_code_hooks_daemon").mkdir(parents=True, exist_ok=True)
    (project_root / "pyproject.toml").write_text("[project]\nname = 'x'\n")


def _args(
    project_root: Path,
    *,
    json_output: bool = False,
    legacy: bool = False,
    stale: bool = False,
    all_except_current: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=project_root,
        json=json_output,
        legacy=legacy,
        stale=stale,
        all_except_current=all_except_current,
        dry_run=dry_run,
        force=force,
    )


class TestListVenvs:
    def test_list_empty_when_no_venvs_exist(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _mark_self_install(tmp_path)
        (tmp_path / "untracked").mkdir()

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_list_venvs(_args(tmp_path))

        assert rc == 0
        out = capsys.readouterr().out
        assert "No venvs found" in out

    def test_list_shows_fingerprint_keyed_and_legacy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        fp = python_venv_fingerprint(tmp_path)
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")
        _make_venv(untracked / "venv-py310-deadbeef", stamp_version="v3.6.0")
        _make_venv(untracked / "venv", stamp_version="v3.5.0")  # legacy pre-fp

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_list_venvs(_args(tmp_path))

        assert rc == 0
        out = capsys.readouterr().out
        assert fp in out
        assert "py310-deadbeef" in out
        assert "v3.7.0" in out
        assert "v3.6.0" in out
        # Current-env marker points at the fp-keyed row, not py310 or legacy
        lines = [ln for ln in out.splitlines() if "←" in ln or "current" in ln.lower()]
        assert any(fp in ln for ln in lines), f"current marker missing for {fp}"

    def test_list_json_mode_emits_machine_readable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        fp = python_venv_fingerprint(tmp_path)
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_list_venvs(_args(tmp_path, json_output=True))

        assert rc == 0
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert isinstance(payload, list)
        assert len(payload) == 1
        entry = payload[0]
        assert entry["fingerprint"] == fp
        assert entry["stamped_version"] == "v3.7.0"
        assert entry["is_current"] is True
        assert Path(entry["path"]).name == f"venv-{fp}"


class TestPruneVenvs:
    def test_dry_run_lists_but_does_not_delete(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        fp = python_venv_fingerprint(tmp_path)
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")
        stale = untracked / "venv-py310-deadbeef"
        _make_venv(stale, stamp_version="v3.6.0", lock_hash=STALE_HASH)

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_prune_venvs(_args(tmp_path, stale=True, dry_run=True, force=True))

        assert rc == 0
        assert stale.exists()  # not deleted
        out = capsys.readouterr().out
        assert "py310-deadbeef" in out
        assert "dry-run" in out.lower()

    def test_prune_legacy_removes_untracked_venv(self, tmp_path: Path) -> None:
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        fp = python_venv_fingerprint(tmp_path)
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")
        legacy = untracked / "venv"
        _make_venv(legacy, stamp_version="v3.5.0")

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_prune_venvs(_args(tmp_path, legacy=True, force=True))

        assert rc == 0
        assert not legacy.exists()
        assert (untracked / f"venv-{fp}").exists()  # current preserved

    def test_prune_stale_keeps_current_fp_venv_and_removes_proven_stale(
        self, tmp_path: Path
    ) -> None:
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        fp = python_venv_fingerprint(tmp_path)
        current = untracked / f"venv-{fp}"
        _make_venv(current, stamp_version="v3.7.0")
        other1 = untracked / "venv-py310-deadbeef"
        other2 = untracked / "venv-py312-12345678"
        _make_venv(other1, stamp_version="v3.6.0", lock_hash=STALE_HASH)
        _make_venv(other2, stamp_version="v3.5.0", lock_hash=STALE_HASH)

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_prune_venvs(_args(tmp_path, stale=True, force=True))

        assert rc == 0
        assert current.exists()
        assert not other1.exists()
        assert not other2.exists()

    def test_prune_refuses_without_force(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Destructive delete requires --force or --dry-run — otherwise abort."""
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        fp = python_venv_fingerprint(tmp_path)
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")
        stale = untracked / "venv-py310-deadbeef"
        _make_venv(stale, stamp_version="v3.6.0", lock_hash=STALE_HASH)

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_prune_venvs(_args(tmp_path, stale=True))

        assert rc == 1
        assert stale.exists()
        captured = capsys.readouterr()
        combined = (captured.out + captured.err).lower()
        assert "force" in combined or "dry-run" in combined

    def test_prune_refuses_to_delete_current_fingerprint(self, tmp_path: Path) -> None:
        """Even with --stale + --force, never touch current-env venv."""
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        fp = python_venv_fingerprint(tmp_path)
        current = untracked / f"venv-{fp}"
        _make_venv(current, stamp_version="v3.7.0")

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_prune_venvs(_args(tmp_path, stale=True, force=True))

        assert rc == 0
        assert current.exists()

    def test_prune_stale_never_selects_an_unproven_venv(self, tmp_path: Path) -> None:
        """Missing metadata and another view's slug are not proof of staleness."""
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        no_metadata = untracked / "venv-py310-nometada"
        other_view = untracked / "venv-someoneelse-py310-deadbeef"
        _make_venv(no_metadata, stamp_version="v3.6.0")
        _make_venv(other_view, stamp_version="v3.6.0", lock_hash=STALE_HASH)

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_prune_venvs(_args(tmp_path, stale=True, force=True))

        assert rc == 0
        assert no_metadata.exists()
        assert other_view.exists()

    def test_all_except_current_is_removed_with_a_clear_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        victim = untracked / "venv-py310-deadbeef"
        _make_venv(victim, stamp_version="v3.6.0", lock_hash=STALE_HASH)

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_prune_venvs(_args(tmp_path, all_except_current=True, force=True))

        assert rc == 1
        assert victim.exists()
        assert "--all-except-current was removed" in capsys.readouterr().err


class TestEnumerateAndHelpers:
    def test_enumerate_returns_empty_when_untracked_missing(self, tmp_path: Path) -> None:
        # No untracked/ dir at all
        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_list_venvs(_args(tmp_path))
        assert rc == 0

    def test_enumerate_skips_non_directories_and_unrelated_names(self, tmp_path: Path) -> None:
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        (untracked / "not_a_dir.txt").write_text("irrelevant")
        (untracked / "random_other_dir").mkdir()
        fp = python_venv_fingerprint(tmp_path)
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_list_venvs(_args(tmp_path, json_output=True))
        assert rc == 0

    def test_enumerate_skips_directory_without_pyvenv_cfg(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A directory is a venv by its ``pyvenv.cfg``; an interpreter file alone is not."""
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        impostor = untracked / "venv-py311-badbadba"
        (impostor / "bin").mkdir(parents=True)
        (impostor / "bin" / "python").write_text("#!/bin/sh\n")
        (impostor / "bin" / "python").chmod(0o755)
        fp = python_venv_fingerprint(tmp_path)
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_list_venvs(_args(tmp_path, json_output=True))
        assert rc == 0
        listed = json.loads(capsys.readouterr().out)
        assert [Path(e["path"]).name for e in listed] == [f"venv-{fp}"]

    def test_human_bytes_covers_all_units(self) -> None:
        assert "B" in cli._human_bytes(100)
        assert "KB" in cli._human_bytes(100 * 1024)
        assert "MB" in cli._human_bytes(100 * 1024 * 1024)
        assert "GB" in cli._human_bytes(100 * 1024 * 1024 * 1024)

    def test_prune_refuses_without_selection_flag(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_prune_venvs(_args(tmp_path, force=True))
        assert rc == 1
        captured = capsys.readouterr()
        assert "--legacy" in captured.err or "--legacy" in captured.out


class TestEnumerateVenvsInstallModes:
    """Regression coverage: `_enumerate_venvs` must look in the right untracked dir.

    Normal install: venvs live under ``$PROJECT/.claude/hooks-daemon/untracked/``.
    Self install:   venvs live under ``$PROJECT/untracked/``.

    Reported in untracked/hooks-daemon-post-install-venv-cleanup-broken.md:
    ``list-venvs`` / ``prune-venvs --legacy`` returned empty for normal-install
    users because the function hardcoded ``project_root / "untracked"``.
    """

    def _make_normal_install_layout(
        self, tmp_path: Path, with_legacy: bool = True
    ) -> tuple[Path, Path]:
        """Build a fake normal-install project tree; return (untracked_dir, legacy)."""
        daemon_dir = tmp_path / ".claude" / "hooks-daemon"
        untracked = daemon_dir / "untracked"
        untracked.mkdir(parents=True)
        # A client install keys its venv on the DAEMON dir (Plan 00456), so the
        # resolver serves this one and the legacy venv/ is not live.
        fp = python_venv_fingerprint(daemon_dir)
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")
        legacy = untracked / "venv"
        if with_legacy:
            _make_venv(legacy, stamp_version="v3.5.0")
        return untracked, legacy

    def test_list_finds_venvs_in_normal_install_layout(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        untracked, _ = self._make_normal_install_layout(tmp_path)
        fp = python_venv_fingerprint(tmp_path / ".claude" / "hooks-daemon")

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_list_venvs(_args(tmp_path))

        assert rc == 0
        out = capsys.readouterr().out
        assert "No venvs found" not in out, (
            "Regression: normal-install venvs under .claude/hooks-daemon/untracked/ "
            "were not detected"
        )
        assert fp in out
        assert str(untracked) in out or str(untracked / f"venv-{fp}") in out

    def test_prune_legacy_works_in_normal_install_layout(self, tmp_path: Path) -> None:
        _, legacy = self._make_normal_install_layout(tmp_path)
        assert legacy.exists()

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_prune_venvs(_args(tmp_path, legacy=True, force=True))

        assert rc == 0
        assert (
            not legacy.exists()
        ), "Regression: prune-venvs --legacy --force was a no-op in normal-install mode"

    def test_self_install_layout_still_works(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Self-install sentinel: daemon source at project root
        (tmp_path / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        fp = python_venv_fingerprint(tmp_path)
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")

        with patch("claude_code_hooks_daemon.daemon.cli.get_project_path", return_value=tmp_path):
            rc = cli.cmd_list_venvs(_args(tmp_path))

        assert rc == 0
        out = capsys.readouterr().out
        assert fp in out


class TestRepairUsesFingerprintKeyedPath:
    def test_repair_targets_fingerprint_keyed_venv(self, tmp_path: Path) -> None:
        """cmd_repair must provision the fingerprint-keyed venv, not untracked/venv.

        tmp_path is a CLIENT layout, so the venv is keyed on the daemon dir
        beneath it, as bash ensure_venv and the resolver key it (Plan 00456).
        """
        args = argparse.Namespace(project_root=tmp_path)

        daemon_dir = tmp_path / ".claude" / "hooks-daemon"
        expected_venv = daemon_dir / "untracked" / f"venv-{python_venv_fingerprint(daemon_dir)}"
        assert expected_venv.name != "venv"

        sync_call: dict[str, str] = {}

        def fake_run(cmd: list[str], **kw: object) -> MagicMock:
            env = kw.get("env", {})
            if isinstance(env, dict) and env.get("UV_PROJECT_ENVIRONMENT"):
                sync_call["UV_PROJECT_ENVIRONMENT"] = str(env["UV_PROJECT_ENVIRONMENT"])
            m = MagicMock()
            m.returncode = 0
            m.stderr = ""
            m.stdout = "OK\n"
            return m

        with (
            patch(
                "claude_code_hooks_daemon.daemon.cli.get_project_path",
                return_value=tmp_path,
            ),
            patch("claude_code_hooks_daemon.daemon.cli.read_pid_file", return_value=None),
            patch("subprocess.run", side_effect=fake_run),
        ):
            rc = cli.cmd_repair(args)

        assert rc == 0
        assert sync_call["UV_PROJECT_ENVIRONMENT"] == str(expected_venv)


class TestStaleVenvAdvisory:
    """Plan 00181 Task 4.2 — daemon start SURFACES reclaimable stale venvs.

    Decision 1: the daemon never auto-deletes venvs (unsafe in the
    multi-container shared-untracked model). It reports reclaimable space and
    points at the guarded ``prune-venvs`` command.
    """

    def _setup(self, tmp_path: Path) -> Path:
        _mark_self_install(tmp_path)
        untracked = tmp_path / "untracked"
        untracked.mkdir()
        return untracked

    def test_stale_selector_includes_legacy_and_lock_hash_stale(self, tmp_path: Path) -> None:
        untracked = self._setup(tmp_path)
        fp = python_venv_fingerprint(tmp_path)
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")
        _make_venv(untracked / "venv-py310-deadbeef", lock_hash=STALE_HASH)  # lock-hash-stale
        _make_venv(untracked / "venv", stamp_version="v3.5.0")  # legacy

        reclaimable = cli._stale_venv_entries(cli._enumerate_venvs(tmp_path))

        paths = {Path(e["path"]).name for e in reclaimable}
        assert paths == {"venv-py310-deadbeef", "venv"}

    def test_stale_selector_excludes_current_and_unproven(self, tmp_path: Path) -> None:
        untracked = self._setup(tmp_path)
        fp = python_venv_fingerprint(tmp_path)
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")
        # A differing stamp is not staleness; no readable metadata is UNPROVEN.
        _make_venv(untracked / "venv-py310-deadbeef", stamp_version="v3.6.0")

        entries = cli._enumerate_venvs(tmp_path)

        assert cli._stale_venv_entries(entries) == []
        assert [Path(e["path"]).name for e in cli._unproven_venv_entries(entries)] == [
            "venv-py310-deadbeef"
        ]

    def test_enumerate_include_size_false_skips_walk(self, tmp_path: Path) -> None:
        untracked = self._setup(tmp_path)
        fp = python_venv_fingerprint(tmp_path)
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")

        entries = cli._enumerate_venvs(tmp_path, include_size=False)

        assert entries
        assert all(e["size_bytes"] == 0 for e in entries)

    def test_advisory_none_when_only_current_venv(self, tmp_path: Path) -> None:
        untracked = self._setup(tmp_path)
        fp = python_venv_fingerprint(tmp_path)
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")

        assert cli._stale_venv_advisory(tmp_path) is None

    def test_advisory_none_when_no_venvs(self, tmp_path: Path) -> None:
        self._setup(tmp_path)
        assert cli._stale_venv_advisory(tmp_path) is None

    def test_advisory_reports_count_and_prune_command(self, tmp_path: Path) -> None:
        untracked = self._setup(tmp_path)
        fp = python_venv_fingerprint(tmp_path)
        _make_venv(untracked / f"venv-{fp}", stamp_version="v3.7.0")
        _make_venv(untracked / "venv-py310-deadbeef", stamp_version="v3.6.0", lock_hash=STALE_HASH)

        advisory = cli._stale_venv_advisory(tmp_path)

        assert advisory is not None
        assert "prune-venvs" in advisory
        assert "1" in advisory  # one reclaimable venv
