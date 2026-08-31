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
        assert HandlerTag.TERMINAL not in handler.tags

    def test_is_not_terminal(self) -> None:
        """The shrink and same-size tiers ALLOW, and must not end the chain.

        The chain breaks on ANY terminal match whatever it decided. While
        this handler was terminal, shrinking an over-long comment -- an
        outcome meant to be silent -- ended dispatch at priority 33 and
        disabled every higher-numbered handler for that write.
        """
        assert CommentSizeHandler().terminal is False


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


class TestNonUtf8ExistingFile:
    """A file the daemon did not write has no encoding contract with it.

    Every other fixture here writes UTF-8, which is exactly why an unguarded
    decode of the EXISTING file survived: latin-1/CP1252 sources are ordinary
    in PHP and C# trees, both in this handler's language registry, and one
    raised UnicodeDecodeError straight out of handle(). Fail-open turned that
    into user-visible exception text; strict_mode turned it into a hard DENY
    of a legitimate write.
    """

    def test_latin1_existing_file_does_not_raise(
        self, handler: CommentSizeHandler, tmp_path: Path
    ) -> None:
        target = tmp_path / "legacy.py"
        target.write_bytes(("x = 1  # caf\xe9 " + ("y" * 90) + "\n").encode("latin-1"))

        new_content = "x = 1  # " + ("y" * 120) + "\n"
        result = handler.handle(_make_write_input(str(target), new_content))

        # The point is that it decides rather than raising; growth past the
        # limit still denies, so the guard is not a silent escape hatch.
        assert result.decision == Decision.DENY

    def test_latin1_existing_file_still_allows_a_shrink(
        self, handler: CommentSizeHandler, tmp_path: Path
    ) -> None:
        target = tmp_path / "legacy.py"
        target.write_bytes(("x = 1  # caf\xe9 " + ("y" * 120) + "\n").encode("latin-1"))

        new_content = "x = 1  # " + ("y" * 60) + "\n"
        result = handler.handle(_make_write_input(str(target), new_content))

        assert result.decision != Decision.DENY


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

    def test_matches_false_for_vendor_dir_with_no_exclude_paths_configured(
        self, handler: CommentSizeHandler
    ) -> None:
        """vendor/build dirs are skipped BY DEFAULT (Plan 00288 Task 4.6),
        matching the get_claude_md() guidance -- no exclude_paths option
        needs to be set for this."""
        content = "x = 1  # " + ("y" * 401) + "\n"
        hook_input = _make_write_input("/workspace/vendor/acme/lib.py", content)
        assert handler.matches(hook_input) is False

    def test_matches_false_for_test_fixture_dir_with_no_exclude_paths_configured(
        self, handler: CommentSizeHandler
    ) -> None:
        """Test fixture dirs are skipped BY DEFAULT (Plan 00288 Task 4.6)."""
        content = "x = 1  # " + ("y" * 401) + "\n"
        hook_input = _make_write_input("/workspace/tests/fixtures/broken.py", content)
        assert handler.matches(hook_input) is False

    def test_matches_false_for_third_party_dir_with_no_exclude_paths_configured(
        self, handler: CommentSizeHandler
    ) -> None:
        """third_party/ is part of the canonical vendored core (Task 3.2) but
        was NOT already covered by the per-language strategy's own
        skip_directories -- this specifically exercises the new
        handler_excludes_path(defaults=...) wiring, not the pre-existing
        strategy-level skip."""
        content = "x = 1  # " + ("y" * 401) + "\n"
        hook_input = _make_write_input("/workspace/third_party/lib/mod.py", content)
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


class TestCommentSizeGetRules:
    """get_rules() (Plan 00116): one rule for both independent size limits."""

    def test_get_rules_returns_one_rule(self) -> None:
        assert len(CommentSizeHandler().get_rules()) == 1

    def test_get_rules_rule_id_is_constant(self) -> None:
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        assert CommentSizeHandler().get_rules()[0].rule_id == RuleID.COMMENT_SIZE

    def test_get_rules_verbose_is_non_empty(self) -> None:
        assert CommentSizeHandler().get_rules()[0].verbose


class TestCommentSizeDisclosureLadder:
    """Verbose-first/terse-after per (transcript_path, rule_id) (Plan 00116)."""

    @pytest.fixture(autouse=True)
    def _reset_disclosure_tracker(self):
        from claude_code_hooks_daemon.core import reset_data_layer

        reset_data_layer()
        yield
        reset_data_layer()

    @staticmethod
    def _hook_input(transcript_path: str | None) -> dict[str, Any]:
        content = "x = 1  # " + ("y" * 60) + "\n"
        hook_input = _make_write_input("/workspace/src/mod.py", content)
        if transcript_path is not None:
            hook_input["transcript_path"] = transcript_path
        return hook_input

    def test_deny_reason_starts_with_rule_id_prefix(self, handler: CommentSizeHandler) -> None:
        from claude_code_hooks_daemon.constants.rule_ids import RuleID

        result = handler.handle(self._hook_input("/tmp/transcript-cs-a.jsonl"))
        assert result.reason.startswith(f"BLOCKED [{RuleID.COMMENT_SIZE}]")

    def test_first_fire_is_verbose(self, handler: CommentSizeHandler) -> None:
        result = handler.handle(self._hook_input("/tmp/transcript-cs-b.jsonl"))
        assert "MUST_EXCEED_COMMENT_SIZE_BECAUSE" in result.reason

    def test_second_fire_same_agent_is_terse(self, handler: CommentSizeHandler) -> None:
        transcript = "/tmp/transcript-cs-c.jsonl"
        handler.handle(self._hook_input(transcript))
        second = handler.handle(self._hook_input(transcript))
        assert "shrinking edits are never blocked" not in second.reason
        assert "exceed the size limit" in second.reason

    def test_different_agent_is_independently_verbose(self, handler: CommentSizeHandler) -> None:
        handler.handle(self._hook_input("/tmp/transcript-cs-d.jsonl"))
        other = handler.handle(self._hook_input("/tmp/transcript-cs-e.jsonl"))
        assert "MUST_EXCEED_COMMENT_SIZE_BECAUSE" in other.reason

    def test_missing_transcript_path_always_verbose(self, handler: CommentSizeHandler) -> None:
        first = handler.handle(self._hook_input(None))
        second = handler.handle(self._hook_input(None))
        assert "MUST_EXCEED_COMMENT_SIZE_BECAUSE" in first.reason
        assert "MUST_EXCEED_COMMENT_SIZE_BECAUSE" in second.reason
