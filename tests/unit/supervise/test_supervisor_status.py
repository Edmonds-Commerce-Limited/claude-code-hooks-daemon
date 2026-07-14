"""Plan 00164 Phase 3 — the running supervisor advertises its identity.

After a daemon upgrade delivers a NEW ``claude-supervise.py`` to disk, the
still-running supervisor is stale but nothing surfaces it. The running supervisor
now writes a small status file (pid + version + source content hash + started-at)
to the shared daemon untracked dir so a SessionStart advisory can compare the
on-disk supervisor against the running one and tell the user to restart ccy.

These tests exercise the standalone script's status helpers directly.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tests.unit.supervise._load import SCRIPT_PATH, load_supervisor_module

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

_mod = load_supervisor_module()


def test_compute_source_hash_is_stable_and_content_sensitive(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    a.write_text("print('one')\n")
    b = tmp_path / "b.py"
    b.write_text("print('one')\n")
    c = tmp_path / "c.py"
    c.write_text("print('two')\n")

    ha = _mod.compute_source_hash(a)
    assert isinstance(ha, str) and ha
    # Same content -> same hash; different content -> different hash.
    assert ha == _mod.compute_source_hash(b)
    assert ha != _mod.compute_source_hash(c)


def test_hash_of_real_supervisor_matches_itself() -> None:
    """The running script can hash its own source deterministically."""
    assert _mod.compute_source_hash(SCRIPT_PATH) == _mod.compute_source_hash(SCRIPT_PATH)


def test_write_and_remove_supervisor_status(tmp_path: Path) -> None:
    status_path = _mod.write_supervisor_status(
        tmp_path,
        version="3.40.0",
        source_hash="abc123",
        pid=4242,
        started_at=1000.0,
    )
    assert status_path is not None
    assert status_path.is_file()

    payload = json.loads(status_path.read_text())
    assert payload["version"] == "3.40.0"
    assert payload["source_hash"] == "abc123"
    assert payload["pid"] == 4242
    assert payload["started_at"] == 1000.0

    _mod.remove_supervisor_status(tmp_path)
    assert not status_path.exists()


def test_remove_is_idempotent(tmp_path: Path) -> None:
    # Removing when no status file exists must not raise.
    _mod.remove_supervisor_status(tmp_path)


def test_status_lives_under_supervise_subdir(tmp_path: Path) -> None:
    status_path = _mod.write_supervisor_status(
        tmp_path, version="3.40.0", source_hash="h", pid=1, started_at=0.0
    )
    assert status_path is not None
    # Same 'supervise' subdir the decision log uses, so it is discoverable.
    assert status_path.parent.name == _mod._LOG_SUBDIRECTORY


def test_main_writes_status_during_run_and_removes_it_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """main() advertises the running identity for the duration of supervise()
    and cleans it up on exit."""
    seen: dict[str, bool] = {}

    def _fake_supervise(child_argv: list[str], **_kwargs: object) -> int:
        # The status file must exist WHILE the supervisor is running.
        seen["existed_during_run"] = _mod._supervisor_status_path(tmp_path).is_file()
        return 0

    monkeypatch.setattr(_mod, "_daemon_untracked_dir", lambda: tmp_path)
    monkeypatch.setattr(_mod, "supervise", _fake_supervise)

    rc = _mod.main(["--", "true"])
    assert rc == 0
    assert seen.get("existed_during_run") is True
    # Removed on exit — a clean shutdown leaves no stale identity.
    assert not _mod._supervisor_status_path(tmp_path).exists()
