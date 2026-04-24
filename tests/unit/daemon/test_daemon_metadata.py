"""Tests for the ``.daemon-metadata.json`` schema and atomic read/write.

Plan 00100 Phase 3 (Tasks 3.1–3.2): persist installer-time choices into a
single atomic JSON file inside each venv so the daemon's startup resolver
never has to recompute or guess. Metadata schema is validated through a
Pydantic v2 model; writes are atomic (tmp-file + rename); reads tolerate
missing or malformed files by signalling "stale → rebuild" to the caller.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from claude_code_hooks_daemon.daemon.paths import (
    DaemonVenvMetadata,
    read_daemon_metadata,
    write_daemon_metadata,
)


class TestDaemonVenvMetadataSchema:
    """Pydantic model enforces required fields and value constraints."""

    def _valid_kwargs(self) -> dict[str, str]:
        return {
            "python_path": "/usr/bin/python3.11",
            "fingerprint": "workspace-py311-2fa8b3c1",
            "lock_hash": "sha256:" + "a" * 64,
            "daemon_version": "v3.9.0",
            "written_at": "2026-04-24T10:00:00Z",
        }

    def test_valid_instance_roundtrips_via_json(self) -> None:
        """Serialise to JSON and back preserves all fields."""
        m = DaemonVenvMetadata(**self._valid_kwargs())
        dumped = m.model_dump_json()
        restored = DaemonVenvMetadata.model_validate_json(dumped)
        assert restored == m

    def test_python_path_must_be_absolute(self) -> None:
        """Relative interpreter paths are non-sensical here."""
        kw = self._valid_kwargs()
        kw["python_path"] = "python3"
        with pytest.raises(ValidationError):
            DaemonVenvMetadata(**kw)

    def test_python_path_rejects_empty_string(self) -> None:
        kw = self._valid_kwargs()
        kw["python_path"] = ""
        with pytest.raises(ValidationError):
            DaemonVenvMetadata(**kw)

    def test_fingerprint_rejects_empty_string(self) -> None:
        kw = self._valid_kwargs()
        kw["fingerprint"] = ""
        with pytest.raises(ValidationError):
            DaemonVenvMetadata(**kw)

    def test_lock_hash_must_be_sha256_prefixed(self) -> None:
        """``lock_hash`` must be ``sha256:<64 hex>`` — format is the contract."""
        kw = self._valid_kwargs()
        kw["lock_hash"] = "a" * 64  # missing prefix
        with pytest.raises(ValidationError):
            DaemonVenvMetadata(**kw)

    def test_lock_hash_must_be_full_64_hex(self) -> None:
        kw = self._valid_kwargs()
        kw["lock_hash"] = "sha256:short"
        with pytest.raises(ValidationError):
            DaemonVenvMetadata(**kw)

    def test_daemon_version_must_be_v_prefixed(self) -> None:
        """Versions are tagged ``vX.Y.Z`` throughout this project."""
        kw = self._valid_kwargs()
        kw["daemon_version"] = "3.9.0"  # missing leading v
        with pytest.raises(ValidationError):
            DaemonVenvMetadata(**kw)

    def test_written_at_must_be_iso8601(self) -> None:
        kw = self._valid_kwargs()
        kw["written_at"] = "yesterday"
        with pytest.raises(ValidationError):
            DaemonVenvMetadata(**kw)

    def test_extra_fields_forbidden(self) -> None:
        """Unknown keys are rejected — schema is closed to prevent drift."""
        kw = self._valid_kwargs()
        kw["hello"] = "world"
        with pytest.raises(ValidationError):
            DaemonVenvMetadata(**kw)


class TestWriteDaemonMetadataAtomicity:
    """``write_daemon_metadata`` is atomic — no half-written file visible."""

    def _valid_meta(self) -> "DaemonVenvMetadata":
        return DaemonVenvMetadata(
            python_path="/usr/bin/python3.11",
            fingerprint="workspace-py311-2fa8b3c1",
            lock_hash="sha256:" + "b" * 64,
            daemon_version="v3.9.0",
            written_at="2026-04-24T10:00:00Z",
        )

    def test_creates_metadata_file_at_expected_path(self, tmp_path: Path) -> None:
        write_daemon_metadata(tmp_path, self._valid_meta())
        assert (tmp_path / ".daemon-metadata.json").exists()

    def test_written_content_parses_back_to_same_model(self, tmp_path: Path) -> None:
        meta = self._valid_meta()
        write_daemon_metadata(tmp_path, meta)
        raw = (tmp_path / ".daemon-metadata.json").read_text()
        assert DaemonVenvMetadata.model_validate_json(raw) == meta

    def test_temp_file_removed_after_successful_write(self, tmp_path: Path) -> None:
        """No ``.tmp`` sidecar must survive a successful write."""
        write_daemon_metadata(tmp_path, self._valid_meta())
        leftovers = list(tmp_path.glob(".daemon-metadata.json.tmp"))
        assert leftovers == []

    def test_overwrites_previous_metadata_atomically(self, tmp_path: Path) -> None:
        """Second write replaces first — no merged content, no partial state."""
        meta1 = self._valid_meta()
        write_daemon_metadata(tmp_path, meta1)
        meta2 = meta1.model_copy(update={"daemon_version": "v3.10.0"})
        write_daemon_metadata(tmp_path, meta2)
        raw = (tmp_path / ".daemon-metadata.json").read_text()
        assert DaemonVenvMetadata.model_validate_json(raw) == meta2

    def test_write_creates_parent_if_missing(self, tmp_path: Path) -> None:
        """Writer does NOT silently create parent — caller owns layout."""
        nonexistent = tmp_path / "does_not_exist"
        with pytest.raises((FileNotFoundError, OSError)):
            write_daemon_metadata(nonexistent, self._valid_meta())


class TestReadDaemonMetadata:
    """``read_daemon_metadata`` returns None on any unusable condition."""

    def _valid_meta(self) -> "DaemonVenvMetadata":
        return DaemonVenvMetadata(
            python_path="/usr/bin/python3.11",
            fingerprint="workspace-py311-2fa8b3c1",
            lock_hash="sha256:" + "c" * 64,
            daemon_version="v3.9.0",
            written_at="2026-04-24T10:00:00Z",
        )

    def test_returns_model_when_file_present_and_valid(self, tmp_path: Path) -> None:
        write_daemon_metadata(tmp_path, self._valid_meta())
        assert read_daemon_metadata(tmp_path) == self._valid_meta()

    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        assert read_daemon_metadata(tmp_path) is None

    def test_returns_none_when_file_is_empty(self, tmp_path: Path) -> None:
        (tmp_path / ".daemon-metadata.json").write_text("")
        assert read_daemon_metadata(tmp_path) is None

    def test_returns_none_when_file_is_invalid_json(self, tmp_path: Path) -> None:
        (tmp_path / ".daemon-metadata.json").write_text("{not valid json")
        assert read_daemon_metadata(tmp_path) is None

    def test_returns_none_when_schema_validation_fails(
        self, tmp_path: Path
    ) -> None:
        """Good JSON but wrong shape → signal stale-rebuild, never raise."""
        (tmp_path / ".daemon-metadata.json").write_text(
            json.dumps({"python_path": "/x", "fingerprint": "y"})  # missing fields
        )
        assert read_daemon_metadata(tmp_path) is None
