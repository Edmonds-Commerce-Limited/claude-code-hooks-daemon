"""Tests for the exempt-agent-type resolution and the one-at-a-time lock probe."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from claude_code_hooks_daemon.qa.full_qa_lock import acquire_full_qa_lock, host_lock_path
from claude_code_hooks_daemon.utils.agent_dispatch_registry import record_dispatch
from claude_code_hooks_daemon.utils.full_qa_exemption import (
    LockState,
    declared_exempt_types,
    exempt_types_problem,
    exempting_entry,
    lock_holder_text,
    lock_path_text,
    probe_full_qa_lock,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


class TestDeclared:
    def test_non_list_declares_nothing(self) -> None:
        assert declared_exempt_types("qa-full-runner") == []
        assert declared_exempt_types(None) == []

    def test_only_non_empty_strings_count(self) -> None:
        assert declared_exempt_types(["a", "", "  ", 3, "b"]) == ["a", "b"]

    def test_problem_reports_shape_and_entries(self) -> None:
        assert exempt_types_problem(None) is None
        assert exempt_types_problem(["a"]) is None
        assert "list" in (exempt_types_problem("a") or "")
        assert "non-empty" in (exempt_types_problem(["a", 3]) or "")


class TestExemptingEntry:
    def test_nothing_declared_exempts_nobody(self, tmp_path: Path) -> None:
        assert exempting_entry([], tmp_path, "s", "a") is None

    @pytest.mark.parametrize("agent_type", [None, "", "  ", 5])
    def test_unplaceable_agent_type_is_not_exempt(self, tmp_path: Path, agent_type: object) -> None:
        assert exempting_entry(["a"], tmp_path, "s", agent_type) is None

    @pytest.mark.parametrize("session_id", [None, "", 5])
    def test_no_session_is_not_exempt(self, tmp_path: Path, session_id: object) -> None:
        assert exempting_entry(["a"], tmp_path, session_id, "a") is None

    def test_exact_unnamed_match(self, tmp_path: Path) -> None:
        assert exempting_entry(["a"], tmp_path, "s", "a") == "a"

    def test_named_dispatch_resolves_through_the_record(self, tmp_path: Path) -> None:
        record_dispatch(tmp_path, "s", "w", "a")
        assert exempting_entry(["a"], tmp_path, "s", "w") == "a"

    def test_name_of_another_type_is_not_exempt(self, tmp_path: Path) -> None:
        record_dispatch(tmp_path, "s", "a", "other")
        assert exempting_entry(["a"], tmp_path, "s", "a") is None


class TestLockProbe:
    def test_free_then_held_then_free(self, repo: Path) -> None:
        assert probe_full_qa_lock(repo) is LockState.FREE
        with acquire_full_qa_lock(repo):
            assert probe_full_qa_lock(repo) is LockState.HELD
        assert probe_full_qa_lock(repo) is LockState.FREE

    def test_not_a_repository_is_unknown(self, tmp_path: Path) -> None:
        assert probe_full_qa_lock(tmp_path / "nowhere") is LockState.UNKNOWN

    def test_holder_is_named_from_a_live_stamp(self, repo: Path) -> None:
        with acquire_full_qa_lock(repo):
            host_lock_path(repo).write_text(
                f"pid={os.getpid()}\ncheckout=/some/worktree\nstarted=2026-10-13T00:00:00Z\n",
                encoding="utf-8",
            )
            text = lock_holder_text(repo)
        assert f"pid {os.getpid()}" in text
        assert "/some/worktree" in text
        assert "2026-10-13T00:00:00Z" in text

    def test_stamp_of_a_dead_pid_is_not_named(self, repo: Path) -> None:
        dead = subprocess.Popen(["true"])
        dead.wait()
        host_lock_path(repo).write_text(f"pid={dead.pid}\ncheckout=/x\n", encoding="utf-8")
        assert "not named" in lock_holder_text(repo)

    @pytest.mark.parametrize("content", ["", "garbage", "pid=notanumber\n"])
    def test_unstamped_or_garbled_lock_is_not_named(self, repo: Path, content: str) -> None:
        host_lock_path(repo).write_text(content, encoding="utf-8")
        assert "not named" in lock_holder_text(repo)

    def test_missing_lock_file_is_not_named(self, tmp_path: Path) -> None:
        assert "not named" in lock_holder_text(tmp_path / "nowhere")

    def test_holder_owned_by_another_user_still_counts_as_alive(
        self, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _denied(pid: int, sig: int) -> None:
            raise PermissionError

        monkeypatch.setattr(os, "kill", _denied)
        host_lock_path(repo).write_text("pid=1\ncheckout=/x\n", encoding="utf-8")
        assert "pid 1 in /x" in lock_holder_text(repo)

    def test_lock_path_text(self, repo: Path, tmp_path: Path) -> None:
        assert lock_path_text(repo).endswith("hooksdaemon-full-qa.lock")
        assert "unknown" in lock_path_text(tmp_path / "nowhere")
