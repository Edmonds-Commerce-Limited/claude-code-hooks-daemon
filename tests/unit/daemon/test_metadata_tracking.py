"""Plan 00594 Task 5.1 -- a branch install records what it tracks.

``tracked_ref`` (exact, slashes kept), ``tracked_sha`` (full) and
``last_release_tag`` live in the venv's ``.daemon-metadata.json``; a release
install clears them. The stamp cannot carry the ref (its ``/`` becomes ``-``).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.daemon import cli
from claude_code_hooks_daemon.daemon.metadata import (
    DaemonVenvMetadata,
    read_daemon_metadata,
    record_tracking,
    write_daemon_metadata,
)

_SHA = "a" * 40
_OTHER_SHA = "b" * 40


def _base(**extra: str) -> DaemonVenvMetadata:
    return DaemonVenvMetadata(
        python_path="/usr/bin/python3.11",
        fingerprint="workspace-py311-2fa8b3c1",
        lock_hash="sha256:" + "a" * 64,
        daemon_version="v3.9.0+rc-1.2.3.aaaaaaa",
        written_at="2026-04-24T10:00:00Z",
        **extra,
    )


def _venv(tmp_path: Path, name: str = "venv-a", **extra: str) -> Path:
    venv = tmp_path / name
    venv.mkdir()
    write_daemon_metadata(venv, _base(**extra))
    return venv


class TestSchema:
    def test_tracking_fields_default_to_none(self) -> None:
        meta = _base()
        assert (meta.tracked_ref, meta.tracked_sha, meta.last_release_tag) == (None, None, None)

    def test_ref_keeps_its_slashes(self) -> None:
        meta = _base(tracked_ref="rc/1.2.3", tracked_sha=_SHA, last_release_tag="v3.8.0")
        assert meta.tracked_ref == "rc/1.2.3"

    def test_sha_must_be_full_lowercase_hex(self) -> None:
        with pytest.raises(ValidationError):
            _base(tracked_ref="rc/1.2.3", tracked_sha="abc1234")

    def test_ref_and_sha_come_together(self) -> None:
        with pytest.raises(ValidationError):
            _base(tracked_ref="rc/1.2.3")
        with pytest.raises(ValidationError):
            _base(tracked_sha=_SHA)

    def test_last_release_tag_must_be_a_release_tag(self) -> None:
        with pytest.raises(ValidationError):
            _base(last_release_tag="main")


class TestRecordTracking:
    def test_records_the_three_fields(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path)
        record_tracking(venv, tracked_ref="rc/1.2.3", tracked_sha=_SHA, last_release_tag="v3.8.0")
        meta = read_daemon_metadata(venv)
        assert meta is not None
        assert (meta.tracked_ref, meta.tracked_sha, meta.last_release_tag) == (
            "rc/1.2.3",
            _SHA,
            "v3.8.0",
        )
        assert meta.fingerprint == "workspace-py311-2fa8b3c1"

    def test_no_ref_clears_all_three(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, tracked_ref="rc/1.2.3", tracked_sha=_SHA, last_release_tag="v3.8.0")
        record_tracking(venv, tracked_ref=None, tracked_sha=None, last_release_tag=None)
        meta = read_daemon_metadata(venv)
        assert meta is not None
        assert (meta.tracked_ref, meta.tracked_sha, meta.last_release_tag) == (None, None, None)

    def test_missing_last_release_tag_is_inherited_from_the_previous_venv(
        self, tmp_path: Path
    ) -> None:
        """Re-tracking from a branch install must not forget the release before it."""
        previous = _venv(
            tmp_path,
            "venv-old",
            tracked_ref="rc/1.2.3",
            tracked_sha=_SHA,
            last_release_tag="v3.8.0",
        )
        venv = _venv(tmp_path, "venv-new")
        record_tracking(
            venv,
            tracked_ref="rc/1.2.3",
            tracked_sha=_OTHER_SHA,
            last_release_tag=None,
            previous_venv_dir=previous,
        )
        meta = read_daemon_metadata(venv)
        assert meta is not None
        assert meta.last_release_tag == "v3.8.0"
        assert meta.tracked_sha == _OTHER_SHA

    def test_explicit_last_release_tag_beats_the_previous_venv(self, tmp_path: Path) -> None:
        previous = _venv(
            tmp_path,
            "venv-old",
            tracked_ref="rc/1.2.3",
            tracked_sha=_SHA,
            last_release_tag="v3.7.0",
        )
        venv = _venv(tmp_path, "venv-new")
        record_tracking(
            venv,
            tracked_ref="rc/1.2.3",
            tracked_sha=_SHA,
            last_release_tag="v3.8.0",
            previous_venv_dir=previous,
        )
        meta = read_daemon_metadata(venv)
        assert meta is not None
        assert meta.last_release_tag == "v3.8.0"

    def test_missing_metadata_raises(self, tmp_path: Path) -> None:
        venv = tmp_path / "venv-bare"
        venv.mkdir()
        with pytest.raises(FileNotFoundError):
            record_tracking(venv, tracked_ref=None, tracked_sha=None, last_release_tag=None)


class TestRecordTrackingCommand:
    @staticmethod
    def _args(venv: Path, **kw: str | None) -> argparse.Namespace:
        values: dict[str, str | None] = {
            "tracked_ref": None,
            "tracked_sha": None,
            "last_release_tag": None,
            "previous_venv_path": None,
        }
        values.update(kw)
        return argparse.Namespace(venv_path=str(venv), **values)

    def test_records_through_the_cli(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path)
        rc = cli.cmd_record_venv_tracking(
            self._args(venv, tracked_ref="rc/1.2.3", tracked_sha=_SHA, last_release_tag="v3.8.0")
        )
        assert rc == 0
        meta = read_daemon_metadata(venv)
        assert meta is not None and meta.tracked_ref == "rc/1.2.3"

    def test_no_ref_clears_through_the_cli(self, tmp_path: Path) -> None:
        venv = _venv(tmp_path, tracked_ref="x", tracked_sha=_SHA)
        assert cli.cmd_record_venv_tracking(self._args(venv)) == 0
        meta = read_daemon_metadata(venv)
        assert meta is not None and meta.tracked_ref is None

    def test_invalid_sha_fails_with_a_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        venv = _venv(tmp_path)
        rc = cli.cmd_record_venv_tracking(self._args(venv, tracked_ref="rc/1", tracked_sha="short"))
        assert rc == 1
        assert "tracked_sha" in capsys.readouterr().err

    def test_missing_metadata_fails_with_a_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        venv = tmp_path / "venv-bare"
        venv.mkdir()
        assert cli.cmd_record_venv_tracking(self._args(venv)) == 1
        assert "metadata" in capsys.readouterr().err
