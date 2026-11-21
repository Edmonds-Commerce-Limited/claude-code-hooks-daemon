"""Tests for the scratch_sweep SessionStart handler (Plan 00627 Task 4.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.core.scratch_session import find_session_dir, read_manifest
from claude_code_hooks_daemon.handlers.session_start import scratch_sweep as module
from claude_code_hooks_daemon.handlers.session_start.scratch_sweep import ScratchSweepHandler

SID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


@pytest.fixture
def handler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ScratchSweepHandler:
    instance = ScratchSweepHandler()
    monkeypatch.setattr(instance, "_get_project_root", lambda: tmp_path)
    return instance


def _input(tmp_path: Path, **extra: Any) -> dict[str, Any]:
    return {
        "hook_event_name": "SessionStart",
        "session_id": SID,
        "source": "startup",
        "cwd": str(tmp_path),
        **extra,
    }


class TestIdentity:
    def test_id_priority_and_non_terminal(self) -> None:
        instance = ScratchSweepHandler()
        assert instance.name == HandlerID.SCRATCH_SWEEP.display_name
        assert instance.priority == Priority.SCRATCH_SWEEP
        assert not instance.terminal

    @pytest.mark.parametrize("source", ["startup", "resume", "compact", "clear"])
    def test_matches_every_source(self, handler: ScratchSweepHandler, source: str) -> None:
        assert handler.matches({"session_id": SID, "source": source})


class TestCreates:
    def test_creates_and_announces(self, handler: ScratchSweepHandler, tmp_path: Path) -> None:
        result = handler.handle(_input(tmp_path))
        session = find_session_dir(tmp_path / "untracked" / "scratch", SID)
        assert session is not None
        text = "\n".join(result.context)
        assert "your scratch directory" in text.lower()
        assert str(session) in text
        assert "scratch new" in text
        manifest = read_manifest(session)
        assert manifest is not None and manifest.checkout == str(tmp_path)
        assert (tmp_path / "untracked" / ".gitignore").is_file()

    def test_second_start_reuses_it(self, handler: ScratchSweepHandler, tmp_path: Path) -> None:
        handler.handle(_input(tmp_path))
        first = find_session_dir(tmp_path / "untracked" / "scratch", SID)
        result = handler.handle(_input(tmp_path, source="compact"))
        assert str(first) in "\n".join(result.context)
        assert len(list((tmp_path / "untracked" / "scratch").iterdir())) == 1

    @pytest.mark.parametrize("bad", [None, "", "../../x", 42])
    def test_unusable_session_id_is_silent(
        self, handler: ScratchSweepHandler, tmp_path: Path, bad: object
    ) -> None:
        result = handler.handle(_input(tmp_path, session_id=bad))
        assert result.context == []
        assert not (tmp_path / "untracked" / "scratch").exists()


class TestFailure:
    def test_eacces_is_an_advisory_not_a_raise(
        self, handler: ScratchSweepHandler, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def denied(*_args: object, **_kwargs: object) -> None:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(Path, "mkdir", denied)
        result = handler.handle(_input(tmp_path))
        text = "\n".join(result.context)
        assert "not created" in text
        assert "PermissionError" in text

    @pytest.mark.parametrize(
        "cwd", ["bad\x00cwd", 7, ["a"], "", "relative/dir", "/no/such/dir/at/all"]
    )
    def test_odd_cwd_never_raises(
        self, handler: ScratchSweepHandler, tmp_path: Path, cwd: object
    ) -> None:
        result = handler.handle(_input(tmp_path, cwd=cwd))
        assert find_session_dir(tmp_path / "untracked" / "scratch", SID) is not None
        assert "your scratch directory" in "\n".join(result.context).lower()

    @pytest.mark.parametrize("link", ["untracked", "untracked/scratch"])
    def test_a_symlinked_root_is_never_followed_outside(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, link: str
    ) -> None:
        project = tmp_path / "project"
        outside = tmp_path / "outside"
        outside.mkdir()
        (project / link).parent.mkdir(parents=True, exist_ok=True)
        (project / link).symlink_to(outside, target_is_directory=True)
        instance = ScratchSweepHandler()
        monkeypatch.setattr(instance, "_get_project_root", lambda: project)
        result = instance.handle(_input(project))
        assert list(outside.rglob("s-*")) == []
        assert "not created" in "\n".join(result.context)

    @pytest.mark.parametrize(
        "payload",
        [
            '{"schema": 1, "archives": [{"expires_at": "soon"}]}',
            '{"schema": 1, "entries": [null]}',
            "[]",
            "\xff\xfe",
        ],
    )
    def test_a_malformed_inventory_is_reported_not_raised(
        self, handler: ScratchSweepHandler, tmp_path: Path, payload: str
    ) -> None:
        (tmp_path / "untracked").mkdir()
        (tmp_path / "untracked" / "scratch-inventory.json").write_text(payload, encoding="utf-8")
        result = handler.handle(_input(tmp_path))
        assert "inventory" in "\n".join(result.context).lower()
        assert handler.verify_still_needed() is False

    def test_an_unparseable_config_falls_back_to_default_caps(
        self, handler: ScratchSweepHandler, tmp_path: Path
    ) -> None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "hooks-daemon.yaml").write_text("scratch: [:\n", encoding="utf-8")
        result = handler.handle(_input(tmp_path))
        assert "your scratch directory" in "\n".join(result.context).lower()

    def test_ignore_file_failure_is_an_advisory(
        self, handler: ScratchSweepHandler, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def denied(_root: Path) -> bool:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(module, "ensure_scratch_dir", denied)
        result = handler.handle(_input(tmp_path))
        assert "not created" in "\n".join(result.context)
