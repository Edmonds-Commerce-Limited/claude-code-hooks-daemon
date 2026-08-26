"""Tests for utils/secret_meta.py (Plan 00272 Phase 5).

The metadata helper core: presence and safe metadata about a protected file,
NEVER content. Keyed HMAC digest by default; plain sha256 and exact size only
behind ``allow_plain_hash``. The HMAC key is generated on first use with
0600 permissions, and a group/world-readable key REFUSES to sign.
"""

import json
import os
import stat
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import secret_meta as sm


def _secret(tmp_path: Path, content: bytes = b"hunter2\n") -> Path:
    path = tmp_path / "fixture.vault-password"
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def _key_path(tmp_path: Path) -> Path:
    return tmp_path / "untracked" / "secret-meta.key"


class TestCollect:
    def test_missing_file_reports_exists_false(self, tmp_path: Path) -> None:
        meta = sm.collect_secret_meta(tmp_path / "nope", key_path=_key_path(tmp_path))
        assert meta["exists"] is False

    def test_existing_file_reports_metadata_without_content(self, tmp_path: Path) -> None:
        secret = _secret(tmp_path)
        meta = sm.collect_secret_meta(secret, key_path=_key_path(tmp_path))
        assert meta["exists"] is True
        assert "mtime" in meta
        assert meta["mode"] == "0600"
        serialised = json.dumps(meta)
        assert "hunter2" not in serialised

    def test_size_is_bucketed_by_default(self, tmp_path: Path) -> None:
        secret = _secret(tmp_path)
        meta = sm.collect_secret_meta(secret, key_path=_key_path(tmp_path))
        assert "size_bucket" in meta
        assert "size_bytes" not in meta

    def test_exact_size_and_sha256_only_with_plain_flag(self, tmp_path: Path) -> None:
        secret = _secret(tmp_path)
        meta = sm.collect_secret_meta(secret, key_path=_key_path(tmp_path), allow_plain_hash=True)
        assert meta["size_bytes"] == 8
        assert len(meta["sha256"]) == 64

    def test_hmac_digest_is_stable_under_same_key(self, tmp_path: Path) -> None:
        secret = _secret(tmp_path)
        key_path = _key_path(tmp_path)
        first = sm.collect_secret_meta(secret, key_path=key_path)
        second = sm.collect_secret_meta(secret, key_path=key_path)
        assert first["digest"] == second["digest"]
        assert len(first["digest"]) == 64

    def test_digest_differs_across_keys(self, tmp_path: Path) -> None:
        secret = _secret(tmp_path)
        first = sm.collect_secret_meta(secret, key_path=tmp_path / "a" / "k1")
        second = sm.collect_secret_meta(secret, key_path=tmp_path / "b" / "k2")
        assert first["digest"] != second["digest"]

    def test_key_file_is_created_owner_only(self, tmp_path: Path) -> None:
        secret = _secret(tmp_path)
        key_path = _key_path(tmp_path)
        sm.collect_secret_meta(secret, key_path=key_path)
        assert key_path.exists()
        mode = stat.S_IMODE(key_path.stat().st_mode)
        assert mode == 0o600

    def test_permissive_key_refuses_to_sign(self, tmp_path: Path) -> None:
        """A group/world-readable key is a compromised key — never sign with it."""
        secret = _secret(tmp_path)
        key_path = _key_path(tmp_path)
        sm.collect_secret_meta(secret, key_path=key_path)
        key_path.chmod(0o644)
        meta = sm.collect_secret_meta(secret, key_path=key_path)
        assert meta["digest"] is None
        assert "key" in meta["digest_refused"].lower()

    def test_world_readable_secret_flagged_in_hygiene(self, tmp_path: Path) -> None:
        """Task 6.1's cheaply-shippable OS-boundary piece: mode hygiene."""
        secret = _secret(tmp_path)
        secret.chmod(0o644)
        meta = sm.collect_secret_meta(secret, key_path=_key_path(tmp_path))
        assert meta["permissions_ok"] is False
        assert "chmod 600" in meta["permissions_hint"]

    def test_owner_only_secret_passes_hygiene(self, tmp_path: Path) -> None:
        secret = _secret(tmp_path)
        meta = sm.collect_secret_meta(secret, key_path=_key_path(tmp_path))
        assert meta["permissions_ok"] is True

    def test_directory_target_reports_clean_error(self, tmp_path: Path) -> None:
        """Review finding 7: a directory is reported, never a crash."""
        meta = sm.collect_secret_meta(tmp_path, key_path=_key_path(tmp_path))
        assert meta["exists"] is True
        assert "directory" in meta["error"]

    def test_unreadable_file_reports_clean_error(
        self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
    ) -> None:
        """Review finding 7: a permission problem is what the tool exists to
        report — metadata still present, error explicit, no crash."""
        secret = _secret(tmp_path)

        def _raise_permission(_self: Path) -> bytes:
            raise PermissionError("denied")

        monkeypatch.setattr(Path, "read_bytes", _raise_permission)
        meta = sm.collect_secret_meta(secret, key_path=_key_path(tmp_path))
        assert "permission denied" in meta["error"]
        assert meta["mode"] == "0600"

    def test_key_creation_race_adopts_winner_key(
        self, tmp_path: Path, monkeypatch: "pytest.MonkeyPatch"
    ) -> None:
        """Review finding 7: an O_EXCL loser re-reads the winner's key."""
        secret = _secret(tmp_path)
        key_path = _key_path(tmp_path)
        real_open = os.open
        raced = {"done": False}

        def _racing_open(path: str | Path, flags: int, mode: int = 0o777) -> int:
            if not raced["done"] and os.O_EXCL & flags:
                raced["done"] = True
                key_path.parent.mkdir(parents=True, exist_ok=True)
                descriptor = real_open(key_path, os.O_WRONLY | os.O_CREAT, 0o600)
                os.write(descriptor, b"w" * 32)
                os.close(descriptor)
                raise FileExistsError(str(path))
            return real_open(path, flags, mode)

        monkeypatch.setattr(os, "open", _racing_open)
        meta = sm.collect_secret_meta(secret, key_path=key_path)
        assert meta["digest"] is not None
        assert key_path.read_bytes() == b"w" * 32
