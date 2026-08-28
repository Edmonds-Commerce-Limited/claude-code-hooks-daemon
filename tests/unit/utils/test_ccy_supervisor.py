"""Unit tests for the shared ccy-supervisor liveness/arming helpers (Plan 00283).

These pure functions were extracted from ``ccy_supervisor_integrity`` so the
SessionStart integrity handler and the ``standing_authorisations`` channel
router share ONE implementation of "is a ccy supervisor armed and live for this
project". The behaviour asserted here is exactly the behaviour that handler
relied on before extraction — these tests are the regression guard for the DRY
move.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from claude_code_hooks_daemon.utils import ccy_supervisor


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestCcyDir:
    def test_resolves_dot_claude_ccy_under_root(self, tmp_path: Path) -> None:
        assert ccy_supervisor.ccy_dir(tmp_path) == tmp_path / ".claude" / "ccy"


class TestIsArmed:
    def test_absent_env_is_not_armed(self, tmp_path: Path) -> None:
        assert ccy_supervisor.is_armed(tmp_path / "ccy.env") is False

    def test_export_referencing_script_is_armed(self, tmp_path: Path) -> None:
        env = tmp_path / "ccy.env"
        _write(env, 'export CCY_CLAUDE_WRAPPER="/x/.claude/ccy/claude-supervise.py --arm --"\n')
        assert ccy_supervisor.is_armed(env) is True

    def test_commented_export_is_not_armed(self, tmp_path: Path) -> None:
        env = tmp_path / "ccy.env"
        _write(env, '# export CCY_CLAUDE_WRAPPER="/x/.claude/ccy/claude-supervise.py --arm --"\n')
        assert ccy_supervisor.is_armed(env) is False

    def test_wrapper_key_without_script_is_not_armed(self, tmp_path: Path) -> None:
        env = tmp_path / "ccy.env"
        _write(env, 'export CCY_CLAUDE_WRAPPER="/usr/bin/some-other-wrapper"\n')
        assert ccy_supervisor.is_armed(env) is False

    def test_unreadable_env_is_not_armed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        env = tmp_path / "ccy.env"
        _write(env, "export CCY_CLAUDE_WRAPPER=claude-supervise.py\n")

        def _raise(*_args: object, **_kwargs: object) -> str:
            raise OSError("unreadable")

        monkeypatch.setattr(Path, "read_text", _raise)
        assert ccy_supervisor.is_armed(env) is False


class TestDaemonUntrackedDir:
    def test_self_install_layout(self, tmp_path: Path) -> None:
        (tmp_path / "src" / "claude_code_hooks_daemon").mkdir(parents=True)
        assert ccy_supervisor.daemon_untracked_dir(tmp_path) == tmp_path / "untracked"

    def test_normal_client_layout(self, tmp_path: Path) -> None:
        assert (
            ccy_supervisor.daemon_untracked_dir(tmp_path)
            == tmp_path / ".claude" / "hooks-daemon" / "untracked"
        )


class TestHashSupervisorSource:
    def test_short_sha256_prefix_is_stable_and_length_capped(self, tmp_path: Path) -> None:
        script = tmp_path / "claude-supervise.py"
        _write(script, "print('hello')\n")
        first = ccy_supervisor.hash_supervisor_source(script)
        second = ccy_supervisor.hash_supervisor_source(script)
        assert first == second
        assert len(first) == 12

    def test_content_change_changes_hash(self, tmp_path: Path) -> None:
        script = tmp_path / "claude-supervise.py"
        _write(script, "print('a')\n")
        before = ccy_supervisor.hash_supervisor_source(script)
        _write(script, "print('b')\n")
        after = ccy_supervisor.hash_supervisor_source(script)
        assert before != after


class TestPidAlive:
    def test_current_process_is_alive(self) -> None:
        assert ccy_supervisor.pid_alive(os.getpid()) is True

    def test_non_int_pid_is_not_alive(self) -> None:
        assert ccy_supervisor.pid_alive("nope") is False
        assert ccy_supervisor.pid_alive(None) is False

    def test_non_positive_pid_is_not_alive(self) -> None:
        assert ccy_supervisor.pid_alive(0) is False
        assert ccy_supervisor.pid_alive(-1) is False

    def test_dead_pid_is_not_alive(self) -> None:
        # A very high pid is overwhelmingly unlikely to be live.
        assert ccy_supervisor.pid_alive(4_000_000_000) is False

    def test_process_lookup_error_is_not_alive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(_pid: int, _sig: int) -> None:
            raise ProcessLookupError

        monkeypatch.setattr(ccy_supervisor.os, "kill", _raise)
        assert ccy_supervisor.pid_alive(1234) is False

    def test_permission_error_means_alive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(_pid: int, _sig: int) -> None:
            raise PermissionError

        monkeypatch.setattr(ccy_supervisor.os, "kill", _raise)
        assert ccy_supervisor.pid_alive(1234) is True

    def test_other_oserror_is_not_alive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise(_pid: int, _sig: int) -> None:
            raise OSError("boom")

        monkeypatch.setattr(ccy_supervisor.os, "kill", _raise)
        assert ccy_supervisor.pid_alive(1234) is False


class TestReadSupervisorStatus:
    def test_absent_file_returns_empty_dict(self, tmp_path: Path) -> None:
        assert ccy_supervisor.read_supervisor_status(tmp_path) == {}

    def test_valid_status_is_returned(self, tmp_path: Path) -> None:
        status = tmp_path / ".claude" / "hooks-daemon" / "untracked" / "supervise"
        status.mkdir(parents=True)
        payload = {"version": "3.56.0", "source_hash": "abc123", "pid": 42}
        _write(status / "supervisor-status.json", json.dumps(payload))
        assert ccy_supervisor.read_supervisor_status(tmp_path) == payload

    def test_malformed_json_returns_empty_dict(self, tmp_path: Path) -> None:
        status = tmp_path / ".claude" / "hooks-daemon" / "untracked" / "supervise"
        status.mkdir(parents=True)
        _write(status / "supervisor-status.json", "{not json")
        assert ccy_supervisor.read_supervisor_status(tmp_path) == {}

    def test_non_dict_json_returns_empty_dict(self, tmp_path: Path) -> None:
        status = tmp_path / ".claude" / "hooks-daemon" / "untracked" / "supervise"
        status.mkdir(parents=True)
        _write(status / "supervisor-status.json", "[1, 2, 3]")
        assert ccy_supervisor.read_supervisor_status(tmp_path) == {}


class TestArmedSupervisorLive:
    def _make_project(self, tmp_path: Path, *, armed: bool, script: bool) -> Path:
        ccy = tmp_path / ".claude" / "ccy"
        ccy.mkdir(parents=True)
        wrapper = "claude-supervise.py" if armed else "some-other-wrapper"
        _write(ccy / "ccy.env", f'export CCY_CLAUDE_WRAPPER="/x/.claude/ccy/{wrapper} --arm --"\n')
        if script:
            _write(ccy / "claude-supervise.py", "print('supervisor')\n")
        return tmp_path

    def _write_status(self, tmp_path: Path, *, pid: int, source_hash: str) -> None:
        status = tmp_path / ".claude" / "hooks-daemon" / "untracked" / "supervise"
        status.mkdir(parents=True, exist_ok=True)
        payload = {"version": "3.56.0", "source_hash": source_hash, "pid": pid}
        _write(status / "supervisor-status.json", json.dumps(payload))

    def test_not_armed_is_false(self, tmp_path: Path) -> None:
        root = self._make_project(tmp_path, armed=False, script=True)
        assert ccy_supervisor.armed_supervisor_live(root) is False

    def test_armed_but_no_script_is_false(self, tmp_path: Path) -> None:
        root = self._make_project(tmp_path, armed=True, script=False)
        assert ccy_supervisor.armed_supervisor_live(root) is False

    def test_armed_but_no_status_file_is_false(self, tmp_path: Path) -> None:
        root = self._make_project(tmp_path, armed=True, script=True)
        assert ccy_supervisor.armed_supervisor_live(root) is False

    def test_armed_but_dead_pid_is_false(self, tmp_path: Path) -> None:
        root = self._make_project(tmp_path, armed=True, script=True)
        script = root / ".claude" / "ccy" / "claude-supervise.py"
        self._write_status(
            root, pid=4_000_000_000, source_hash=ccy_supervisor.hash_supervisor_source(script)
        )
        assert ccy_supervisor.armed_supervisor_live(root) is False

    def test_armed_but_stale_hash_is_false(self, tmp_path: Path) -> None:
        root = self._make_project(tmp_path, armed=True, script=True)
        self._write_status(root, pid=os.getpid(), source_hash="stale000000")
        assert ccy_supervisor.armed_supervisor_live(root) is False

    def test_armed_missing_hash_is_false(self, tmp_path: Path) -> None:
        root = self._make_project(tmp_path, armed=True, script=True)
        status = root / ".claude" / "hooks-daemon" / "untracked" / "supervise"
        status.mkdir(parents=True, exist_ok=True)
        _write(status / "supervisor-status.json", json.dumps({"pid": os.getpid()}))
        assert ccy_supervisor.armed_supervisor_live(root) is False

    def test_armed_live_and_current_is_true(self, tmp_path: Path) -> None:
        root = self._make_project(tmp_path, armed=True, script=True)
        script = root / ".claude" / "ccy" / "claude-supervise.py"
        self._write_status(
            root, pid=os.getpid(), source_hash=ccy_supervisor.hash_supervisor_source(script)
        )
        assert ccy_supervisor.armed_supervisor_live(root) is True

    def test_hash_error_is_false(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        root = self._make_project(tmp_path, armed=True, script=True)
        self._write_status(root, pid=os.getpid(), source_hash="whatever0000")

        def _raise(_path: Path) -> str:
            raise OSError("cannot read")

        monkeypatch.setattr(ccy_supervisor, "hash_supervisor_source", _raise)
        assert ccy_supervisor.armed_supervisor_live(root) is False
