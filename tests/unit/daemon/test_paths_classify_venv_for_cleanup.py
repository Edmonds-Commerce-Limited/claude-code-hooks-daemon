"""Unit tests for ``classify_venv`` and ``list-stale-venvs`` (N441, Plan 00517 Task 3.1).

One function decides every venv's verdict. ``stale`` needs a positive finding;
``unproven`` is a venv the code cannot prove stale (unreadable metadata or
another view's slug); ``keep`` is everything the code can explain.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_code_hooks_daemon.daemon.paths import (
    VENV_KEEP,
    VENV_STALE,
    VENV_UNPROVEN,
    classify_untracked_venvs,
    classify_venv,
    main,
    project_path_slug,
    python_venv_fingerprint,
)

CURRENT_HASH = "sha256:" + "a" * 64
OTHER_HASH = "sha256:" + "b" * 64


def _venv(untracked: Path, name: str, lock_hash: str | None) -> Path:
    path = untracked / name
    path.mkdir(parents=True)
    if lock_hash is not None:
        (path / ".daemon-metadata.json").write_text(
            json.dumps({"python_path": "/x/bin/python", "lock_hash": lock_hash})
        )
    return path


def _classify(venv: Path, current_hash: str | None = CURRENT_HASH) -> tuple[str, str]:
    return classify_venv(venv, "me", current_hash, frozenset())


class TestClassifyVenv:
    """Removal needs a positive finding; everything else is kept or unproven."""

    def test_same_slug_mismatched_hash_is_stale(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-me-py311-abc12345", OTHER_HASH)
        assert _classify(venv)[0] == VENV_STALE

    def test_legacy_name_mismatched_hash_is_stale(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-py311-abc12345", OTHER_HASH)
        assert _classify(venv)[0] == VENV_STALE

    def test_bare_legacy_directory_is_stale(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv", None)
        verdict, reason = _classify(venv)
        assert verdict == VENV_STALE
        assert "legacy" in reason

    def test_other_slug_is_unproven(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-them-py311-abc12345", OTHER_HASH)
        verdict, reason = _classify(venv)
        assert verdict == VENV_UNPROVEN
        assert "slug" in reason

    def test_matching_hash_is_kept(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-me-py311-abc12345", CURRENT_HASH)
        assert _classify(venv) == (VENV_KEEP, "lock_hash matches the current source")

    def test_missing_metadata_is_unproven(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-me-py311-abc12345", None)
        verdict, reason = _classify(venv)
        assert verdict == VENV_UNPROVEN
        assert "metadata" in reason

    def test_unreadable_metadata_is_unproven(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-me-py311-abc12345", None)
        (venv / ".daemon-metadata.json").write_text("{not json")
        assert _classify(venv)[0] == VENV_UNPROVEN

    def test_uncomputable_current_hash_keeps_everything(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-me-py311-abc12345", OTHER_HASH)
        verdict, reason = _classify(venv, current_hash=None)
        assert verdict == VENV_KEEP
        assert "cannot compute" in reason

    def test_live_venv_is_kept_whatever_its_hash(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv-me-py311-abc12345", OTHER_HASH)
        verdict, reason = classify_venv(venv, "me", CURRENT_HASH, frozenset({venv.resolve()}))
        assert verdict == VENV_KEEP
        assert "live" in reason

    def test_live_bare_legacy_directory_is_kept(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, "venv", None)
        verdict, _ = classify_venv(venv, "me", CURRENT_HASH, frozenset({venv.resolve()}))
        assert verdict == VENV_KEEP


class TestClassifyUntrackedVenvs:
    """The directory scan feeds every caller the same verdicts."""

    def _project(self, tmp_path: Path) -> tuple[Path, Path, str]:
        daemon_dir = tmp_path / "proj"
        daemon_dir.mkdir()
        (daemon_dir / "pyproject.toml").write_text("[project]\n")
        return daemon_dir, daemon_dir / "untracked", project_path_slug(daemon_dir)

    def test_symlink_names_are_not_judged_by_their_target(self, tmp_path: Path) -> None:
        daemon_dir, untracked, slug = self._project(tmp_path)
        real = _venv(untracked, f"venv-{slug}-py311-abc12345", OTHER_HASH)
        (untracked / f"venv-{slug}-py310-linked").symlink_to(real)

        verdicts = {v.path.name: v for v in classify_untracked_venvs(daemon_dir)}

        assert verdicts[f"venv-{slug}-py311-abc12345"].verdict == VENV_STALE
        link = verdicts[f"venv-{slug}-py310-linked"]
        assert link.verdict == VENV_KEEP
        assert "symlink" in link.reason

    def test_extra_live_directory_is_kept(self, tmp_path: Path) -> None:
        daemon_dir, untracked, slug = self._project(tmp_path)
        current = _venv(untracked, f"venv-{slug}-py311-abc12345", OTHER_HASH)

        verdicts = classify_untracked_venvs(daemon_dir, extra_live=[current])

        assert [(v.path, v.verdict) for v in verdicts] == [(current, VENV_KEEP)]

    def test_current_fingerprints_venv_is_never_judged(self, tmp_path: Path) -> None:
        daemon_dir, untracked, _ = self._project(tmp_path)
        current = _venv(untracked, f"venv-{python_venv_fingerprint(daemon_dir)}", None)

        (verdict,) = classify_untracked_venvs(daemon_dir)

        assert (verdict.path, verdict.verdict) == (current, VENV_KEEP)
        assert "current fingerprint" in verdict.reason

    def test_no_untracked_directory_yields_nothing(self, tmp_path: Path) -> None:
        assert classify_untracked_venvs(tmp_path / "nowhere") == []


class TestListStaleVenvsCli:
    """The subcommand prints one verdict line per non-current venv-* directory."""

    def test_prints_verdicts_and_skips_current(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        daemon_dir = tmp_path / "proj"
        untracked = daemon_dir / "untracked"
        (daemon_dir / "pyproject.toml").parent.mkdir(parents=True)
        (daemon_dir / "pyproject.toml").write_text("[project]\n")
        slug = project_path_slug(daemon_dir)
        current = _venv(untracked, f"venv-{slug}-py311-deadbeef", OTHER_HASH)
        stale = _venv(untracked, f"venv-{slug}-py310-abc12345", OTHER_HASH)
        unproven = _venv(untracked, f"venv-{slug}-py312-0badcafe", None)
        (untracked / "venv-notadir").write_text("file")

        code = main(
            [
                "list-stale-venvs",
                "--daemon-dir",
                str(daemon_dir),
                "--current-venv",
                str(current),
            ]
        )

        out = capsys.readouterr().out.splitlines()
        assert code == 0
        assert out == [
            f"remove\t{stale.resolve()}\tlock_hash differs from the current source",
            f"unproven\t{unproven.resolve()}\tno usable .daemon-metadata.json",
        ]
