"""Tests for the per-session scratch directory and its manifest (Plan 00627 Tasks 4.1, 4.2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from claude_code_hooks_daemon.core import scratch_session
from claude_code_hooks_daemon.core.scratch_session import (
    MANIFEST_NAME,
    SessionError,
    bounded_ttl_hours,
    check_entry_name,
    check_session_id,
    ensure_session_dir,
    find_session_dir,
    is_session_dir_name,
    new_entry,
    read_manifest,
    resolve_session_dir,
    session_dir_name,
)

SID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
NOW = datetime(2026, 11, 21, 9, 30, 5, tzinfo=UTC)
LATER = datetime(2026, 11, 21, 10, 0, 0, tzinfo=UTC)


def _ensure(root: Path, sid: str = SID, now: datetime = NOW) -> Path:
    return ensure_session_dir(root, sid, now=now, checkout="/repo", branch="main").path


class TestSessionId:
    def test_uuid_gives_first_eight(self) -> None:
        assert check_session_id(SID) == "aaaaaaaa"

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "short",
            "../../etc/passwd",
            "aaaaaaaa/x",
            "aaaa-aaaa-x",
            "*" * 10,
            "aaaaaaaa\n",
            "é" * 9,
        ],
    )
    def test_refuses_anything_outside_the_charset(self, bad: str) -> None:
        with pytest.raises(SessionError):
            check_session_id(bad)

    def test_name_shape(self) -> None:
        name = session_dir_name(SID, NOW)
        assert name == "s-20261121T093005Z-aaaaaaaa"
        assert is_session_dir_name(name)
        assert not is_session_dir_name("s-2026-aaaaaaaa")
        assert not is_session_dir_name("notes")


class TestEnsure:
    def test_creates_directory_and_manifest(self, tmp_path: Path) -> None:
        result = ensure_session_dir(tmp_path, SID, now=NOW, checkout="/repo", branch="main")
        assert result.created
        assert result.path == tmp_path / "s-20261121T093005Z-aaaaaaaa"
        manifest = read_manifest(result.path)
        assert manifest is not None
        assert manifest.session_id == SID
        assert manifest.born == NOW.timestamp()
        assert manifest.checkout == "/repo"
        assert manifest.branch == "main"
        assert manifest.entries == {}
        raw = json.loads((result.path / MANIFEST_NAME).read_text(encoding="utf-8"))
        assert raw["schema"] == scratch_session.SCHEMA_VERSION

    def test_idempotent_and_never_rewrites_the_manifest(self, tmp_path: Path) -> None:
        first = _ensure(tmp_path)
        before = (first / MANIFEST_NAME).read_bytes()
        again = ensure_session_dir(tmp_path, SID, now=LATER, checkout="/x", branch="y")
        assert not again.created
        assert again.path == first
        assert (first / MANIFEST_NAME).read_bytes() == before

    def test_other_session_gets_its_own(self, tmp_path: Path) -> None:
        assert _ensure(tmp_path) != _ensure(tmp_path, OTHER)

    def test_creates_the_root(self, tmp_path: Path) -> None:
        root = tmp_path / "untracked" / "scratch"
        assert _ensure(root).parent == root

    def test_refuses_a_bad_session_id_before_touching_disk(self, tmp_path: Path) -> None:
        with pytest.raises(SessionError):
            ensure_session_dir(tmp_path, "../evil-id", now=NOW, checkout="/r", branch=None)
        assert list(tmp_path.iterdir()) == []

    def test_mkdir_failure_is_a_session_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def denied(*_args: object, **_kwargs: object) -> None:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "mkdir", denied)
        with pytest.raises(SessionError, match="PermissionError"):
            _ensure(tmp_path / "root")

    def test_explicit_name_must_carry_the_session(self, tmp_path: Path) -> None:
        with pytest.raises(SessionError):
            ensure_session_dir(
                tmp_path,
                SID,
                now=NOW,
                checkout="/r",
                branch=None,
                name="s-20261121T093005Z-bbbbbbbb",
            )


class TestFind:
    def test_finds_by_manifest_session(self, tmp_path: Path) -> None:
        made = _ensure(tmp_path)
        assert find_session_dir(tmp_path, SID) == made
        assert find_session_dir(tmp_path, OTHER) is None

    def test_absent_root(self, tmp_path: Path) -> None:
        assert find_session_dir(tmp_path / "nope", SID) is None

    def test_same_prefix_other_session_is_not_a_match(self, tmp_path: Path) -> None:
        _ensure(tmp_path, "aaaaaaaa-twin")
        assert find_session_dir(tmp_path, SID) is None

    def test_link_is_not_followed(self, tmp_path: Path) -> None:
        real = _ensure(tmp_path / "elsewhere")
        root = tmp_path / "root"
        root.mkdir()
        (root / real.name).symlink_to(real)
        assert find_session_dir(root, SID) is None

    def test_garbage_manifest_is_not_a_session(self, tmp_path: Path) -> None:
        made = _ensure(tmp_path)
        (made / MANIFEST_NAME).write_text("{not json", encoding="utf-8")
        assert read_manifest(made) is None
        assert find_session_dir(tmp_path, SID) is None

    def test_manifest_link_is_not_read(self, tmp_path: Path) -> None:
        made = _ensure(tmp_path)
        other = _ensure(tmp_path / "o")
        (made / MANIFEST_NAME).unlink()
        (made / MANIFEST_NAME).symlink_to(other / MANIFEST_NAME)
        assert read_manifest(made) is None


class TestResolve:
    def test_own_checkout_first(self, tmp_path: Path) -> None:
        own, main = tmp_path / "own", tmp_path / "main"
        made = _ensure(own)
        _ensure(main, now=LATER)
        found = resolve_session_dir(own, main, SID, now=LATER, checkout="/w", branch="b")
        assert found == made

    def test_mirrors_the_main_name(self, tmp_path: Path) -> None:
        own, main = tmp_path / "own", tmp_path / "main"
        parent = _ensure(main)
        found = resolve_session_dir(own, main, SID, now=LATER, checkout="/w", branch="b")
        assert found == own / parent.name
        manifest = read_manifest(found)
        assert manifest is not None and manifest.checkout == "/w"

    def test_creates_when_neither_has_one(self, tmp_path: Path) -> None:
        own, main = tmp_path / "own", tmp_path / "main"
        found = resolve_session_dir(own, main, SID, now=NOW, checkout="/w", branch=None)
        assert found.parent == own
        assert not main.exists()


class TestEntryName:
    @pytest.mark.parametrize("good", ["probe", "00627-review", "a.b_c+d@e~f"])
    def test_accepts(self, good: str) -> None:
        assert check_entry_name(good) == good

    @pytest.mark.parametrize(
        "bad",
        ["", ".scratch-keep", MANIFEST_NAME, ".sweeping-x", "-rf", "a/b", "..", "a b", "x" * 200],
    )
    def test_refuses(self, bad: str) -> None:
        with pytest.raises(SessionError):
            check_entry_name(bad)


class TestBoundedTtl:
    def test_none_is_none(self) -> None:
        assert bounded_ttl_hours(None, max_ttl_hours=72, root_ttl_hours=24) is None

    def test_within_bound(self) -> None:
        assert bounded_ttl_hours(48, max_ttl_hours=72, root_ttl_hours=24) == 48

    def test_root_ttl_longer_than_max_is_the_bound(self) -> None:
        assert bounded_ttl_hours(100, max_ttl_hours=72, root_ttl_hours=168) == 100

    @pytest.mark.parametrize("bad", [0, -1, 73])
    def test_refuses(self, bad: int) -> None:
        with pytest.raises(SessionError):
            bounded_ttl_hours(bad, max_ttl_hours=72, root_ttl_hours=24)


class TestNewEntry:
    def test_records_and_creates(self, tmp_path: Path) -> None:
        session = _ensure(tmp_path)
        path = new_entry(session, "probe", now=LATER, purpose="repro", plan="00627", ttl_hours=48)
        assert path == session / "probe"
        assert path.is_dir()
        manifest = read_manifest(session)
        assert manifest is not None
        record = manifest.entries["probe"]
        assert record.born == LATER.timestamp()
        assert (record.purpose, record.plan, record.ttl_hours) == ("repro", "00627", 48)

    def test_existing_entry_refused_and_birth_kept(self, tmp_path: Path) -> None:
        session = _ensure(tmp_path)
        new_entry(session, "probe", now=NOW, purpose=None, plan=None, ttl_hours=None)
        with pytest.raises(SessionError, match="exists"):
            new_entry(session, "probe", now=LATER, purpose=None, plan=None, ttl_hours=None)
        manifest = read_manifest(session)
        assert manifest is not None and manifest.entries["probe"].born == NOW.timestamp()

    def test_unrecorded_existing_path_refused(self, tmp_path: Path) -> None:
        session = _ensure(tmp_path)
        (session / "probe").write_text("x", encoding="utf-8")
        with pytest.raises(SessionError):
            new_entry(session, "probe", now=NOW, purpose=None, plan=None, ttl_hours=None)

    def test_invalid_manifest_refused(self, tmp_path: Path) -> None:
        session = _ensure(tmp_path)
        (session / MANIFEST_NAME).write_text("[]", encoding="utf-8")
        with pytest.raises(SessionError, match="manifest"):
            new_entry(session, "probe", now=NOW, purpose=None, plan=None, ttl_hours=None)
        assert not (session / "probe").exists()

    def test_bad_plan_refused(self, tmp_path: Path) -> None:
        session = _ensure(tmp_path)
        with pytest.raises(SessionError):
            new_entry(session, "probe", now=NOW, purpose=None, plan="abc", ttl_hours=None)

    def test_no_temp_file_left(self, tmp_path: Path) -> None:
        session = _ensure(tmp_path)
        new_entry(session, "a", now=NOW, purpose=None, plan=None, ttl_hours=None)
        new_entry(session, "b", now=NOW, purpose=None, plan=None, ttl_hours=None)
        assert sorted(item.name for item in session.iterdir()) == [MANIFEST_NAME, "a", "b"]
