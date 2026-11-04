"""A public-pattern deny names the pattern and WHERE it matched, never WHAT matched (issue #92).

Owner ruling: a deny reason lands in the transcript, so echoing the matched text
puts the sensitive value there. The pattern name and the location are disclosed;
the match, a snippet of it, or a redacted-but-recoverable form never is.
"""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content import (
    SensitiveContentHandler,
)

SECRET_VALUE = "ZQ-4471-MARK"
PATTERN_NAME = "labelled-reference"


@pytest.fixture(autouse=True)
def _fresh_data_layer() -> Iterator[None]:
    reset_data_layer()
    yield
    reset_data_layer()


@pytest.fixture
def handler() -> SensitiveContentHandler:
    instance = SensitiveContentHandler()
    instance._public_patterns = [
        {"name": PATTERN_NAME, "pattern": r"ZQ-\d+-MARK", "description": "a reference"}
    ]
    return instance


def _bash(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def _assert_withheld(reason: str | None) -> str:
    assert reason is not None
    assert PATTERN_NAME in reason
    assert SECRET_VALUE not in reason
    assert "4471" not in reason
    return reason


class TestWriteAndEdit:
    def test_write_names_pattern_path_and_line_but_not_the_match(
        self, handler: SensitiveContentHandler
    ) -> None:
        content = f"first line\nsecond line\nref {SECRET_VALUE} here\n"
        result = handler.handle(
            {"tool_name": "Write", "tool_input": {"file_path": "/tmp/f.txt", "content": content}}
        )
        assert result.decision == Decision.DENY
        reason = _assert_withheld(result.reason)
        assert "/tmp/f.txt" in reason
        assert "line 3" in reason
        assert "edited text" not in reason

    def test_edit_names_pattern_path_and_line_but_not_the_match(
        self, handler: SensitiveContentHandler
    ) -> None:
        result = handler.handle(
            {
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": "/tmp/f.txt",
                    "old_string": "old",
                    "new_string": f"ok\nref {SECRET_VALUE}",
                },
            }
        )
        assert result.decision == Decision.DENY
        reason = _assert_withheld(result.reason)
        assert "/tmp/f.txt" in reason
        # The line counts inside new_string, not the file, and says so.
        assert "line 2 of the edited text" in reason

    def test_a_match_in_the_file_path_itself_is_not_echoed(
        self,
        handler: SensitiveContentHandler,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content.resolve_project_root",
            lambda: str(tmp_path),
        )
        target = tmp_path / f"{SECRET_VALUE}.txt"
        result = handler.handle(
            {"tool_name": "Write", "tool_input": {"file_path": str(target), "content": "clean"}}
        )
        assert result.decision == Decision.DENY
        _assert_withheld(result.reason)


class TestGitMetadata:
    def test_commit_message_names_the_field_but_not_the_match(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        result = handler.handle(_bash(f"git commit -m 'fix {SECRET_VALUE} handling'", tmp_path))
        assert result.decision == Decision.DENY
        reason = _assert_withheld(result.reason)
        assert "commit message" in reason

    def test_tag_names_the_field_but_not_the_match(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        result = handler.handle(_bash(f"git tag {SECRET_VALUE}", tmp_path))
        assert result.decision == Decision.DENY
        reason = _assert_withheld(result.reason)
        assert "tag" in reason

    def test_branch_names_the_field_but_not_the_match(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        result = handler.handle(_bash(f"git checkout -b {SECRET_VALUE}", tmp_path))
        assert result.decision == Decision.DENY
        reason = _assert_withheld(result.reason)
        assert "branch" in reason

    def test_author_identity_names_the_field_but_not_the_match(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        result = handler.handle(_bash(f"git config user.name {SECRET_VALUE}", tmp_path))
        assert result.decision == Decision.DENY
        reason = _assert_withheld(result.reason)
        assert "author identity" in reason


class TestGhBody:
    def test_inline_body_names_the_surface_but_not_the_match(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        result = handler.handle(
            _bash(f"gh issue comment 1 --body 'see {SECRET_VALUE} for details'", tmp_path)
        )
        assert result.decision == Decision.DENY
        reason = _assert_withheld(result.reason)
        assert "gh" in reason
        assert "inline" in reason

    def test_body_file_names_the_path_but_not_the_match(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        body = tmp_path / "body.txt"
        body.write_text(f"see {SECRET_VALUE}\n")
        result = handler.handle(_bash(f"gh issue comment 1 --body-file {body}", tmp_path))
        assert result.decision == Decision.DENY
        reason = _assert_withheld(result.reason)
        assert str(body) in reason


class TestLogs:
    @pytest.mark.parametrize("surface", ["write", "commit", "gh"])
    def test_no_log_record_holds_the_match(
        self,
        handler: SensitiveContentHandler,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        surface: str,
    ) -> None:
        hook_input: dict[str, Any]
        if surface == "write":
            hook_input = {
                "tool_name": "Write",
                "tool_input": {"file_path": "/tmp/f.txt", "content": f"x {SECRET_VALUE}"},
            }
        elif surface == "commit":
            hook_input = _bash(f"git commit -m 'x {SECRET_VALUE}'", tmp_path)
        else:
            hook_input = _bash(f"gh issue comment 1 --body 'x {SECRET_VALUE}'", tmp_path)
        with caplog.at_level(logging.DEBUG):
            handler.matches(hook_input)
            result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        for record in caplog.records:
            assert SECRET_VALUE not in record.getMessage()


class TestScanText:
    def test_scan_text_finding_does_not_hold_the_match(
        self, handler: SensitiveContentHandler
    ) -> None:
        finding = handler.scan_text(f"a {SECRET_VALUE}")
        assert finding is not None
        assert PATTERN_NAME in finding
        assert SECRET_VALUE not in finding
