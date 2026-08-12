"""Tests for CommentSizeHandler - caps over-long comments with grow/shrink tiering."""

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.constants import HandlerID, HandlerTag, Priority
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.comment_size import (
    CommentSizeHandler,
)


def _make_write_input(file_path: str, content: str) -> dict[str, Any]:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }


def _make_edit_input(file_path: str, old_string: str, new_string: str) -> dict[str, Any]:
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": file_path,
            "old_string": old_string,
            "new_string": new_string,
        },
    }


@pytest.fixture
def handler() -> CommentSizeHandler:
    h = CommentSizeHandler()
    # Small thresholds so tests don't need enormous fixtures.
    h._max_comment_line_chars = 40
    h._max_comment_block_lines = 3
    return h


class TestCommentSizeHandlerInit:
    def test_handler_id(self) -> None:
        assert CommentSizeHandler().handler_id == HandlerID.COMMENT_SIZE

    def test_priority(self) -> None:
        assert CommentSizeHandler().priority == Priority.COMMENT_SIZE

    def test_tags(self) -> None:
        handler = CommentSizeHandler()
        assert HandlerTag.MULTI_LANGUAGE in handler.tags
        assert HandlerTag.CONTENT_QUALITY in handler.tags
        assert HandlerTag.BLOCKING in handler.tags


class TestMatchesGating:
    def test_ignores_non_write_edit_tools(self, handler: CommentSizeHandler) -> None:
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        assert handler.matches(hook_input) is False

    def test_ignores_unknown_extension(self, handler: CommentSizeHandler) -> None:
        content = "# " + ("x" * 100) + "\n"
        hook_input = _make_write_input("/workspace/data.xyz", content)
        assert handler.matches(hook_input) is False

    def test_ignores_content_under_limits(self, handler: CommentSizeHandler) -> None:
        hook_input = _make_write_input("/workspace/src/mod.py", "# short comment\nx = 1\n")
        assert handler.matches(hook_input) is False

    def test_matches_new_file_with_over_long_line(self, handler: CommentSizeHandler) -> None:
        content = "x = 1  # " + ("y" * 60) + "\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is True

    def test_matches_new_file_with_over_long_block(self, handler: CommentSizeHandler) -> None:
        content = "\n".join(f"# line {i}" for i in range(6)) + "\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is True

    def test_ignores_skip_directories(self, handler: CommentSizeHandler) -> None:
        content = "x = 1  # " + ("y" * 60) + "\n"
        hook_input = _make_write_input("/workspace/vendor/mod.py", content)
        assert handler.matches(hook_input) is False


class TestDocstringExemption:
    def test_python_docstring_over_limit_does_not_match(self, handler: CommentSizeHandler) -> None:
        docstring_lines = "\n".join(f"Line {i} of the docstring body." for i in range(6))
        content = f'"""\n{docstring_lines}\n"""\n'
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is False

    def test_jsdoc_block_over_limit_does_not_match(self, handler: CommentSizeHandler) -> None:
        doc_lines = "\n".join(f" * Line {i} of the doc block." for i in range(6))
        content = f"/**\n{doc_lines}\n */\nfunction f() {{}}\n"
        hook_input = _make_write_input("/workspace/src/mod.ts", content)
        assert handler.matches(hook_input) is False


class TestBrandNewFileGrowth:
    """A brand new file has no 'before' -> any over-limit comment blocks immediately."""

    def test_new_file_over_limit_comment_is_denied(self, handler: CommentSizeHandler) -> None:
        content = "x = 1  # " + ("y" * 60) + "\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "comment" in (result.reason or "").lower()


class TestEditGrowthTiering:
    def test_edit_that_grows_the_comment_is_denied(self, handler: CommentSizeHandler) -> None:
        old = "x = 1  # short\n"
        new = "x = 1  # " + ("y" * 60) + "\n"
        hook_input = _make_edit_input("/workspace/src/mod.py", old, new)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_edit_that_shrinks_is_silent(self, handler: CommentSizeHandler) -> None:
        old = "x = 1  # " + ("y" * 90) + "\n"
        new = "x = 1  # " + ("y" * 60) + "\n"  # still over limit, but SHORTER than before
        hook_input = _make_edit_input("/workspace/src/mod.py", old, new)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_edit_that_stays_the_same_size_advises(self, handler: CommentSizeHandler) -> None:
        text = "x = 1  # " + ("y" * 60) + "\n"
        hook_input = _make_edit_input("/workspace/src/mod.py", text, text)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context


class TestWriteOnExistingFileGrowth:
    def test_write_growing_an_existing_oversized_file_is_denied(
        self, handler: CommentSizeHandler, tmp_path: Path
    ) -> None:
        target = tmp_path / "mod.py"
        old_content = "x = 1  # " + ("y" * 60) + "\n"
        target.write_text(old_content, encoding="utf-8")

        new_content = "x = 1  # " + ("y" * 90) + "\n"
        hook_input = _make_write_input(str(target), new_content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_write_shrinking_an_existing_oversized_file_is_silent(
        self, handler: CommentSizeHandler, tmp_path: Path
    ) -> None:
        target = tmp_path / "mod.py"
        old_content = "x = 1  # " + ("y" * 90) + "\n"
        target.write_text(old_content, encoding="utf-8")

        new_content = "x = 1  # " + ("y" * 60) + "\n"
        hook_input = _make_write_input(str(target), new_content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_write_reproducing_the_same_oversized_comment_advises(
        self, handler: CommentSizeHandler, tmp_path: Path
    ) -> None:
        target = tmp_path / "mod.py"
        content = "x = 1  # " + ("y" * 60) + "\n"
        target.write_text(content, encoding="utf-8")

        hook_input = _make_write_input(str(target), content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context


class TestEscapeHatch:
    def test_escape_hatch_downgrades_a_growing_block_to_advisory(
        self, handler: CommentSizeHandler
    ) -> None:
        old = "x = 1  # short\n"
        new = (
            "x = 1  # " + ("y" * 60) + "\n"
            "# MUST_EXCEED_COMMENT_SIZE_BECAUSE: verbatim upstream licence text\n"
        )
        hook_input = _make_edit_input("/workspace/src/mod.py", old, new)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context

    def test_bare_escape_hatch_marker_without_reason_does_not_count(
        self, handler: CommentSizeHandler
    ) -> None:
        old = "x = 1  # short\n"
        new = "x = 1  # " + ("y" * 60) + "\n" "# MUST_EXCEED_COMMENT_SIZE_BECAUSE:\n"
        hook_input = _make_edit_input("/workspace/src/mod.py", old, new)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY


class TestWarnMode:
    def test_warn_mode_downgrades_growth_block_to_advisory(
        self, handler: CommentSizeHandler
    ) -> None:
        handler._mode = "warn"
        content = "x = 1  # " + ("y" * 60) + "\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW
        assert result.context


class TestGuardClauses:
    def test_handle_allows_when_file_path_missing(self, handler: CommentSizeHandler) -> None:
        hook_input = {"tool_name": "Write", "tool_input": {"content": "x = 1"}}
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_allows_when_extension_unknown(self, handler: CommentSizeHandler) -> None:
        content = "# " + ("y" * 60) + "\n"
        hook_input = _make_write_input("/workspace/data.xyz", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_handle_allows_when_content_empty(self, handler: CommentSizeHandler) -> None:
        hook_input = _make_write_input("/workspace/src/mod.py", "")
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW

    def test_matches_false_when_content_empty(self, handler: CommentSizeHandler) -> None:
        hook_input = _make_write_input("/workspace/src/mod.py", "")
        assert handler.matches(hook_input) is False

    def test_matches_false_when_path_matches_exclude_glob(
        self, handler: CommentSizeHandler
    ) -> None:
        handler._exclude_paths = ["src/generated/**"]
        content = "x = 1  # " + ("y" * 60) + "\n"
        hook_input = _make_write_input("/workspace/src/generated/mod.py", content)
        assert handler.matches(hook_input) is False

    def test_apply_language_filter_is_idempotent(self, handler: CommentSizeHandler) -> None:
        handler._languages = ["Python"]
        handler._apply_language_filter()
        handler._apply_language_filter()
        assert handler._registry.registered_languages == ["Python"]


class TestDefaultThresholds:
    def test_default_max_comment_line_chars_is_400(self) -> None:
        handler = CommentSizeHandler()
        content = "x = 1  # " + ("y" * 401) + "\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is True

    def test_default_stays_under_400_is_allowed(self) -> None:
        handler = CommentSizeHandler()
        content = "x = 1  # " + ("y" * 50) + "\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is False

    def test_default_max_comment_block_lines_is_40(self) -> None:
        handler = CommentSizeHandler()
        content = "\n".join(f"# line {i}" for i in range(41)) + "\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        assert handler.matches(hook_input) is True


class TestBlockLinesOnlyBreach:
    """A span can breach the LINE-COUNT limit without breaching char-length."""

    def test_new_file_over_line_count_only_is_denied_and_describes_lines(
        self, handler: CommentSizeHandler
    ) -> None:
        content = "\n".join(f"# line {i}" for i in range(6)) + "\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "lines" in (result.reason or "")


class TestDirectHandleGuardClauses:
    def test_matches_false_when_file_path_missing(self, handler: CommentSizeHandler) -> None:
        hook_input = {"tool_name": "Write", "tool_input": {"content": "x = 1"}}
        assert handler.matches(hook_input) is False

    def test_handle_allows_when_no_breaching_spans(self, handler: CommentSizeHandler) -> None:
        hook_input = _make_write_input("/workspace/src/mod.py", "# short comment\nx = 1\n")
        result = handler.handle(hook_input)
        assert result.decision == Decision.ALLOW


class TestGetClaudeMd:
    def test_returns_non_empty_guidance(self) -> None:
        guidance = CommentSizeHandler().get_claude_md()
        assert guidance is not None
        assert "comment_size" in guidance


class TestGetAcceptanceTests:
    def test_returns_at_least_one_test(self) -> None:
        tests = CommentSizeHandler().get_acceptance_tests()
        assert len(tests) >= 1
