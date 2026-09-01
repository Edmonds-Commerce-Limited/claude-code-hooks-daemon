"""Unit tests for daemon-side hook-payload capture (Plan 00158).

The daemon receives every ``{event, hook_input}`` envelope, so payload capture
for dogfooding lives here — not in the dumb forwarder. It is config-driven
(tracked ``hooks-daemon.yaml``) and applied by a daemon restart; no Claude Code
relaunch is ever needed.

These tests pin the pure capture helpers (primitives in, no pydantic/context
coupling) so the behaviour is verifiable in isolation.
"""

from __future__ import annotations

import json
from pathlib import Path

from claude_code_hooks_daemon.daemon.payload_capture import (
    capture_payload,
    resolve_capture_dir,
)


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_disabled_writes_nothing(tmp_path: Path) -> None:
    result = capture_payload(
        enabled=False,
        events=[],
        capture_dir=tmp_path,
        event="Status",
        hook_input={"session_id": "abc"},
    )
    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_enabled_writes_event_jsonl(tmp_path: Path) -> None:
    hook_input = {"session_id": "abc", "model": {"id": "opus"}}
    result = capture_payload(
        enabled=True,
        events=[],
        capture_dir=tmp_path / "cap",
        event="Status",
        hook_input=hook_input,
    )
    assert result == tmp_path / "cap" / "Status.jsonl"
    lines = _read_lines(result)
    assert len(lines) == 1
    assert json.loads(lines[0]) == hook_input


def test_system_event_is_never_captured(tmp_path: Path) -> None:
    result = capture_payload(
        enabled=True,
        events=[],
        capture_dir=tmp_path,
        event="_system",
        hook_input={"command": "status"},
    )
    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_events_filter_skips_unlisted_event(tmp_path: Path) -> None:
    result = capture_payload(
        enabled=True,
        events=["Status"],
        capture_dir=tmp_path,
        event="PreToolUse",
        hook_input={"tool_name": "Bash"},
    )
    assert result is None
    assert list(tmp_path.iterdir()) == []


def test_events_filter_allows_listed_event(tmp_path: Path) -> None:
    result = capture_payload(
        enabled=True,
        events=["Status"],
        capture_dir=tmp_path,
        event="Status",
        hook_input={"session_id": "abc"},
    )
    assert result is not None
    assert result.name == "Status.jsonl"


def test_appends_across_calls(tmp_path: Path) -> None:
    for i in range(3):
        capture_payload(
            enabled=True,
            events=[],
            capture_dir=tmp_path,
            event="Status",
            hook_input={"n": i},
        )
    assert len(_read_lines(tmp_path / "Status.jsonl")) == 3


def test_event_name_is_sanitised_for_filename(tmp_path: Path) -> None:
    result = capture_payload(
        enabled=True,
        events=[],
        capture_dir=tmp_path,
        event="weird/../name",
        hook_input={},
    )
    assert result is not None
    # No path separators survive into the filename.
    assert result.parent == tmp_path
    assert "/" not in result.name


def test_resolve_capture_dir_defaults_to_untracked(tmp_path: Path) -> None:
    assert resolve_capture_dir(None, tmp_path) == tmp_path / "payload-capture"


def test_resolve_capture_dir_uses_configured_dir(tmp_path: Path) -> None:
    """A repository-relative ``configured_dir`` is joined to ``untracked_dir``."""
    assert resolve_capture_dir("custom/capture", tmp_path) == tmp_path / "custom" / "capture"


def test_resolve_capture_dir_rejects_absolute_configured_dir(tmp_path: Path) -> None:
    """Config carries zero absolute paths (Plan 00303): degrade, never raise.

    ``payload_capture`` is a best-effort dogfooding aid, so an absolute
    ``configured_dir`` is logged and treated as unset -- the default is used
    instead -- rather than raising.
    """
    absolute = str(tmp_path / "custom")
    assert resolve_capture_dir(absolute, tmp_path) == tmp_path / "payload-capture"


class TestSecretRedaction:
    """Plan 00201: a secret term must never reach a capture file verbatim."""

    def test_default_no_terms_writes_payload_unredacted(self, tmp_path: Path) -> None:
        """No terms passed = no-op redaction (backward compatible default)."""
        hook_input = {"tool_input": {"content": "perfectly normal content"}}
        result = capture_payload(
            enabled=True,
            events=[],
            capture_dir=tmp_path,
            event="PreToolUse",
            hook_input=hook_input,
        )
        assert result is not None
        assert json.loads(_read_lines(result)[0]) == hook_input

    def test_secret_term_is_redacted_before_writing(self, tmp_path: Path) -> None:
        hook_input = {"tool_input": {"content": "contains zzqx-nonsense-term here"}}
        result = capture_payload(
            enabled=True,
            events=[],
            capture_dir=tmp_path,
            event="PreToolUse",
            hook_input=hook_input,
            secret_terms=("zzqx-nonsense-term",),
        )
        assert result is not None
        raw_bytes = result.read_bytes()
        assert b"zzqx-nonsense-term" not in raw_bytes

    def test_secret_term_redacted_in_nested_fields(self, tmp_path: Path) -> None:
        hook_input = {
            "tool_input": {"file_path": "/tmp/f.txt", "content": "line1\nzzqx-nonsense-term\n"},
            "session_id": "abc",
        }
        result = capture_payload(
            enabled=True,
            events=[],
            capture_dir=tmp_path,
            event="PreToolUse",
            hook_input=hook_input,
            secret_terms=("zzqx-nonsense-term",),
        )
        assert result is not None
        parsed = json.loads(_read_lines(result)[0])
        assert "zzqx-nonsense-term" not in json.dumps(parsed)
        # Unrelated fields survive untouched.
        assert parsed["session_id"] == "abc"
        assert parsed["tool_input"]["file_path"] == "/tmp/f.txt"


class TestProtectedPathExclusion:
    """Plan 00272 Task 4-5: a protected-path event is excluded, never redacted."""

    _PATTERNS = ("*.dummy-fixture-glob",)
    _PROTECTED_PATH = "/tmp/fixture.dummy-fixture-glob"

    def test_read_of_protected_path_excluded(self, tmp_path: Path) -> None:
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": self._PROTECTED_PATH},
        }
        result = capture_payload(
            enabled=True,
            events=[],
            capture_dir=tmp_path,
            event="PreToolUse",
            hook_input=hook_input,
            protected_patterns=self._PATTERNS,
        )
        assert result is None
        assert list(tmp_path.iterdir()) == []

    def test_bash_mention_of_protected_path_excluded(self, tmp_path: Path) -> None:
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": f"cat {self._PROTECTED_PATH}"},
        }
        result = capture_payload(
            enabled=True,
            events=[],
            capture_dir=tmp_path,
            event="PreToolUse",
            hook_input=hook_input,
            protected_patterns=self._PATTERNS,
        )
        assert result is None
        assert list(tmp_path.iterdir()) == []

    def test_unrelated_payload_still_captured(self, tmp_path: Path) -> None:
        hook_input = {"tool_name": "Read", "tool_input": {"file_path": "/tmp/normal.txt"}}
        result = capture_payload(
            enabled=True,
            events=[],
            capture_dir=tmp_path,
            event="PreToolUse",
            hook_input=hook_input,
            protected_patterns=self._PATTERNS,
        )
        assert result is not None

    def test_empty_patterns_never_excludes(self, tmp_path: Path) -> None:
        hook_input = {
            "tool_name": "Read",
            "tool_input": {"file_path": self._PROTECTED_PATH},
        }
        result = capture_payload(
            enabled=True,
            events=[],
            capture_dir=tmp_path,
            event="PreToolUse",
            hook_input=hook_input,
        )
        assert result is not None
