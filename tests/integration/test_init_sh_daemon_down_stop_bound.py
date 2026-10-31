"""Plan 00555 Task 2.6 (a), N=3: the daemon-down Stop block is bounded.

The first two consecutive daemon-down stop blocks in a session block; the
third is allowed with a loud systemMessage. ``STOPPING BECAUSE: [awaiting-human]``
in the last assistant message allows at any count. CI_ENFORCED,
invalid_hook_input and NEEDS_PROVISION are never counted.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import Timeout
from claude_code_hooks_daemon.handlers.stop.auto_continue_stop import (
    _AWAITING_HUMAN_DECLARATION,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
INIT_SH = REPO_ROOT / "init.sh"
BASH = shutil.which("bash") or "/bin/bash"
SESSION = "sess-1"
AWAITING = "All done. STOPPING BECAUSE: [awaiting-human] need the owner."


def _make_project(root: Path) -> Path:
    daemon_root = root / ".claude" / "hooks-daemon"
    (daemon_root / "untracked").mkdir(parents=True)
    shutil.copy(INIT_SH, root / ".claude" / "init.sh")
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    (root / ".claude" / "hooks-daemon.env").write_text(
        'HOOKS_DAEMON_ROOT_DIR="$PROJECT_PATH/.claude/hooks-daemon"\n'
    )
    launcher = daemon_root / "bin" / "hooks-daemon"
    launcher.parent.mkdir()
    launcher.write_text("#!/bin/bash\n")
    return root


@pytest.fixture
def project(tmp_path: Path) -> Path:
    return _make_project(tmp_path / "proj")


@pytest.fixture
def dead_socket() -> Iterator[Path]:
    short = Path(tempfile.mkdtemp(prefix="hd-"))
    try:
        yield short / "none.sock"
    finally:
        shutil.rmtree(short, ignore_errors=True)


def _untracked(project: Path) -> Path:
    return project / ".claude" / "hooks-daemon" / "untracked"


def _counter(project: Path, event: str = "Stop", session: str = SESSION) -> Path:
    return _untracked(project) / f".daemon-down-stops.{session}.{event}"


def _log(project: Path) -> Path:
    return _untracked(project) / ".daemon-down-stops.log"


def _payload(session: str = SESSION, transcript: Path | None = None, **extra: Any) -> str:
    data: dict[str, Any] = {"session_id": session, "hook_event_name": "Stop", **extra}
    if transcript is not None:
        data["transcript_path"] = str(transcript)
    return json.dumps(data)


def _run(
    project: Path, script: str, payload: str, sock: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("CLAUDE_HOOKS_", "HOOKS_DAEMON_"))
    }
    env["CLAUDE_HOOKS_SOCKET_TIMEOUT"] = "0.4"
    if sock is not None:
        env["CLAUDE_HOOKS_SOCKET_PATH"] = str(sock)
    return subprocess.run(
        [BASH, "-c", f"source .claude/init.sh; {script}"],
        cwd=project,
        env=env,
        input=payload,
        capture_output=True,
        text=True,
        timeout=Timeout.REQUEST_LONG,
        check=False,
    )


def _forward(
    project: Path, sock: Path, payload: str, event: str = "Stop"
) -> subprocess.CompletedProcess[str]:
    return _run(project, f"forward_stop_event {event}", payload, sock)


def _emit(
    project: Path, payload: str, flag: str = "", event: str = "Stop"
) -> subprocess.CompletedProcess[str]:
    setup = f"{flag}=true; " if flag else ""
    return _run(project, f"{setup}emit_hook_error {event} daemon_startup_failed detail", payload)


def _is_block(result: subprocess.CompletedProcess[str]) -> bool:
    return '"decision"' in result.stdout and "block" in result.stdout


def _transcript(path: Path, entries: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))
    return path


def _assistant(text: str | list[dict[str, Any]]) -> dict[str, Any]:
    content = [{"type": "text", "text": text}] if isinstance(text, str) else text
    return {"type": "assistant", "message": {"role": "assistant", "content": content}}


def _user(text: str) -> dict[str, Any]:
    return {"type": "user", "message": {"role": "user", "content": text}}


class TestTransportPath:
    def test_blocks_one_and_two_then_allows_the_third(self, project: Path, dead_socket: Path) -> None:
        for expected_count in (1, 2):
            result = _forward(project, dead_socket, _payload())
            assert result.returncode == 2, result.stderr
            assert "Hooks daemon not running" in result.stderr
            assert _counter(project).read_text().strip() == str(expected_count)
        third = _forward(project, dead_socket, _payload())
        assert third.returncode == 0, third.stderr
        message = json.loads(third.stdout.strip().splitlines()[-1])["systemMessage"]
        assert "3 consecutive" in message
        assert "protection" in message and "NOT active" in message
        assert "diagnose" in message
        assert "decision" not in third.stdout
        line = _log(project).read_text()
        assert SESSION in line and "\t3\t" in line

    def test_later_stops_keep_allowing_until_reset(self, project: Path, dead_socket: Path) -> None:
        for _ in range(3):
            _forward(project, dead_socket, _payload())
        assert _forward(project, dead_socket, _payload()).returncode == 0

    def test_a_new_session_starts_at_one(self, project: Path, dead_socket: Path) -> None:
        for _ in range(3):
            _forward(project, dead_socket, _payload())
        assert _forward(project, dead_socket, _payload("other")).returncode == 2

    def test_deleting_the_counter_resets(self, project: Path, dead_socket: Path) -> None:
        for _ in range(2):
            _forward(project, dead_socket, _payload())
        _counter(project).unlink()
        assert _forward(project, dead_socket, _payload()).returncode == 2
        assert _counter(project).read_text().strip() == "1"

    def test_stop_and_subagent_stop_do_not_share_a_count(
        self, project: Path, dead_socket: Path
    ) -> None:
        for _ in range(2):
            _forward(project, dead_socket, _payload())
        assert _forward(project, dead_socket, _payload(), "SubagentStop").returncode == 2
        assert _counter(project, "SubagentStop").read_text().strip() == "1"
        assert _counter(project, "Stop").read_text().strip() == "2"

    def test_a_missing_session_id_is_bounded_too(self, project: Path, dead_socket: Path) -> None:
        results = [_forward(project, dead_socket, "{}").returncode for _ in range(3)]
        assert results == [2, 2, 0]
        assert _counter(project, session="unknown").exists()

    def test_a_hostile_session_id_cannot_escape_the_untracked_dir(
        self, project: Path, dead_socket: Path
    ) -> None:
        _forward(project, dead_socket, _payload("../../evil"))
        assert not (project / "evil.Stop").exists()
        names = [p.name for p in _untracked(project).iterdir()]
        assert any(n.startswith(".daemon-down-stops.") for n in names)
        assert not any("/" in n for n in names)

    def test_invalid_hook_input_never_counts_and_never_allows(
        self, project: Path, dead_socket: Path
    ) -> None:
        for _ in range(4):
            result = _forward(project, dead_socket, "not json")
            assert result.returncode == 2
            assert "malformed hook payload" in result.stderr
        assert not _counter(project, session="unknown").exists()

    def test_a_reached_but_slow_daemon_keeps_allowing_without_counting(
        self, project: Path
    ) -> None:
        import socket
        import threading

        short = Path(tempfile.mkdtemp(prefix="hd-"))
        server = socket.socket(socket.AF_UNIX)
        server.bind(str(short / "s.sock"))
        server.listen(5)
        held: list[socket.socket] = []

        def accept() -> None:
            conn, _ = server.accept()
            held.append(conn)

        thread = threading.Thread(target=accept, daemon=True)
        thread.start()
        try:
            result = _forward(project, short / "s.sock", _payload())
        finally:
            for conn in held:
                conn.close()
            server.close()
            shutil.rmtree(short, ignore_errors=True)
        assert result.returncode == 0
        assert not _counter(project).exists()

    def test_unwritable_untracked_still_blocks_and_names_the_path(
        self, project: Path, dead_socket: Path
    ) -> None:
        # A directory where the counter file belongs cannot be read or written
        # (a file in place of untracked/ would abort init.sh at source time).
        _counter(project).mkdir()
        for _ in range(4):
            result = _forward(project, dead_socket, _payload())
            assert result.returncode == 2
        assert str(_untracked(project)) in result.stderr

    def test_a_response_from_the_daemon_resets_the_count(self, project: Path) -> None:
        import socket
        import threading

        for _ in range(2):
            _forward(project, project / "nowhere.sock", _payload())
        assert _counter(project).exists()
        short = Path(tempfile.mkdtemp(prefix="hd-"))
        server = socket.socket(socket.AF_UNIX)
        server.bind(str(short / "s.sock"))
        server.listen(5)

        def answer() -> None:
            conn, _ = server.accept()
            conn.recv(65536)
            conn.sendall(b"{}\n")
            conn.close()

        thread = threading.Thread(target=answer, daemon=True)
        thread.start()
        try:
            result = _forward(project, short / "s.sock", _payload())
        finally:
            server.close()
            shutil.rmtree(short, ignore_errors=True)
        assert result.returncode == 0
        assert not _counter(project).exists()


class TestEmitHookErrorPath:
    @pytest.mark.parametrize(
        "flag",
        ["", "_HOOKS_DAEMON_VENV_MISSING", "_HOOKS_DAEMON_NOT_INSTALLED"],
    )
    def test_blocks_one_and_two_then_allows_the_third(self, project: Path, flag: str) -> None:
        for _ in range(2):
            assert _is_block(_emit(project, _payload(), flag))
        third = _emit(project, _payload(), flag)
        assert third.returncode == 0
        assert not _is_block(third)
        assert "NOT active" in json.loads(third.stdout)["systemMessage"]

    def test_alternating_reasons_count_as_three(self, project: Path) -> None:
        assert _is_block(_emit(project, _payload(), ""))
        assert _is_block(_emit(project, _payload(), "_HOOKS_DAEMON_VENV_MISSING"))
        assert not _is_block(_emit(project, _payload(), ""))

    def test_ci_enforced_stays_unbounded(self, project: Path) -> None:
        for _ in range(5):
            assert _is_block(_emit(project, _payload(), "_HOOKS_DAEMON_CI_ENFORCED"))
        assert not _counter(project).exists()

    def test_needs_provision_is_untouched(self, project: Path) -> None:
        for _ in range(4):
            result = _emit(project, _payload(), "_HOOKS_DAEMON_NEEDS_PROVISION")
            assert "daemon not running" not in result.stdout.lower()
        assert not _counter(project).exists()

    def test_subagent_stop_is_bounded_separately(self, project: Path) -> None:
        for _ in range(2):
            assert _is_block(_emit(project, _payload(), "", "SubagentStop"))
        assert _is_block(_emit(project, _payload(), "", "Stop"))
        assert not _is_block(_emit(project, _payload(), "", "SubagentStop"))

    def test_an_empty_stdin_still_blocks_without_hanging(self, project: Path) -> None:
        assert _is_block(_emit(project, ""))

    def test_the_log_line_names_session_class_and_event(self, project: Path) -> None:
        for _ in range(3):
            _emit(project, _payload(), "_HOOKS_DAEMON_VENV_MISSING")
        fields = _log(project).read_text().strip().split("\t")
        assert SESSION in fields
        assert "3" in fields
        assert "venv_missing" in fields
        assert "Stop" in fields

    def test_unwritable_untracked_still_blocks(self, project: Path) -> None:
        _counter(project).mkdir()
        for _ in range(4):
            result = _emit(project, _payload())
            assert _is_block(result)
        assert str(_untracked(project)) in result.stderr


class TestAwaitingHumanDeclaration:
    def test_honoured_at_count_one_without_incrementing(self, project: Path, tmp_path: Path) -> None:
        transcript = _transcript(tmp_path / "t.jsonl", [_user("hi"), _assistant(AWAITING)])
        result = _emit(project, _payload(transcript=transcript))
        assert result.returncode == 0
        assert not _is_block(result)
        message = json.loads(result.stdout)["systemMessage"]
        assert "awaiting-human" in message
        assert "no stand-in" in message or "stand-in" in message
        assert not _counter(project).exists()

    def test_honoured_through_the_transport(
        self, project: Path, tmp_path: Path, dead_socket: Path
    ) -> None:
        transcript = _transcript(tmp_path / "t.jsonl", [_assistant(AWAITING)])
        result = _forward(project, dead_socket, _payload(transcript=transcript))
        assert result.returncode == 0

    def test_list_content_blocks(self, project: Path, tmp_path: Path) -> None:
        blocks = [
            {"type": "thinking", "thinking": "x"},
            {"type": "text", "text": "STOPPING BECAUSE:   [Awaiting-Human] x"},
        ]
        transcript = _transcript(tmp_path / "t.jsonl", [_assistant(blocks)])
        assert not _is_block(_emit(project, _payload(transcript=transcript)))

    def test_plain_string_content(self, project: Path, tmp_path: Path) -> None:
        entry = {"type": "assistant", "message": {"role": "assistant", "content": AWAITING}}
        transcript = _transcript(tmp_path / "t.jsonl", [entry])
        assert not _is_block(_emit(project, _payload(transcript=transcript)))

    def test_token_in_a_user_message_does_not_count(self, project: Path, tmp_path: Path) -> None:
        transcript = _transcript(tmp_path / "t.jsonl", [_assistant("working"), _user(AWAITING)])
        assert _is_block(_emit(project, _payload(transcript=transcript)))

    def test_token_in_an_earlier_assistant_message_does_not_count(
        self, project: Path, tmp_path: Path
    ) -> None:
        transcript = _transcript(tmp_path / "t.jsonl", [_assistant(AWAITING), _assistant("more")])
        assert _is_block(_emit(project, _payload(transcript=transcript)))

    @pytest.mark.parametrize("shape", ["missing", "empty", "garbage", "truncated"])
    def test_unreadable_transcripts_mean_no_declaration(
        self, project: Path, tmp_path: Path, shape: str
    ) -> None:
        path = tmp_path / "t.jsonl"
        if shape == "empty":
            path.write_text("")
        elif shape == "garbage":
            path.write_text("not json\n\x00\x01\n")
        elif shape == "truncated":
            path.write_text(json.dumps(_assistant(AWAITING))[:-10])
        assert _is_block(_emit(project, _payload(transcript=path)))

    def test_a_large_transcript_reads_only_the_tail(self, project: Path, tmp_path: Path) -> None:
        filler = [_assistant("x" * 1000) for _ in range(400)]
        transcript = _transcript(tmp_path / "t.jsonl", [_assistant("old"), *filler])
        with transcript.open("a") as handle:
            handle.write(json.dumps(_assistant(AWAITING)) + "\n")
        assert transcript.stat().st_size > 256 * 1024
        assert not _is_block(_emit(project, _payload(transcript=transcript)))

    def test_ci_enforced_ignores_the_declaration(self, project: Path, tmp_path: Path) -> None:
        transcript = _transcript(tmp_path / "t.jsonl", [_assistant(AWAITING)])
        result = _emit(project, _payload(transcript=transcript), "_HOOKS_DAEMON_CI_ENFORCED")
        assert _is_block(result)

    @pytest.mark.parametrize(
        "text",
        [
            "STOPPING BECAUSE: [awaiting-human] x",
            "stopping because:[AWAITING-HUMAN]",
            "STOPPING BECAUSE:\n\t [awaiting-human]",
            "STOPPING BECAUSE: [awaiting human]",
            "STOPPING  BECAUSE: [awaiting-human]",
            "STOPPING BECAUSE awaiting-human",
            "[awaiting-human]",
            "no token here",
        ],
    )
    def test_matches_the_daemon_regex(self, project: Path, tmp_path: Path, text: str) -> None:
        transcript = _transcript(tmp_path / "t.jsonl", [_assistant(text)])
        allowed = not _is_block(_emit(project, _payload(transcript=transcript)))
        assert allowed == bool(_AWAITING_HUMAN_DECLARATION.search(text))


def test_the_bound_constant_is_three() -> None:
    assert re.search(r"^_STOP_BOUND = 3$", INIT_SH.read_text(), re.MULTILINE)
