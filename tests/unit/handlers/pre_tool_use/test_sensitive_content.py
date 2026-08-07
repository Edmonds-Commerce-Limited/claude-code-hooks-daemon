"""Tests for SensitiveContentHandler (Plan 00201).

Two independent sources: (a) configurable PUBLIC patterns, safe to name in
the deny reason; (b) a gitignored SECRET word list, whose matched term must
NEVER appear in the deny reason — only a 1-based index into the (gitignored,
hence meaningless-without-it) file.
"""

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content import (
    SensitiveContentHandler,
)
from claude_code_hooks_daemon.utils import secret_redaction as sr


def _write_input(file_path: str, content: str) -> dict[str, Any]:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }


def _edit_input(file_path: str, new_string: str, old_string: str = "old") -> dict[str, Any]:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": file_path, "old_string": old_string, "new_string": new_string},
    }


@pytest.fixture(autouse=True)
def _reset_redaction_caches() -> None:
    sr.reset_terms_cache()
    sr.reset_active_path_cache()
    yield
    sr.reset_terms_cache()
    sr.reset_active_path_cache()


def _handler_with_public_patterns(patterns: list[dict[str, str]]) -> SensitiveContentHandler:
    handler = SensitiveContentHandler()
    handler._public_patterns = patterns
    return handler


def _handler_with_secret_file(secret_file: Path) -> SensitiveContentHandler:
    handler = SensitiveContentHandler()
    handler._secret_word_list_path = str(secret_file)
    return handler


class TestInit:
    def test_identity(self) -> None:
        handler = SensitiveContentHandler()
        assert handler.name == "block-sensitive-content"
        assert handler.terminal is True

    def test_default_public_patterns_is_empty(self) -> None:
        handler = SensitiveContentHandler()
        assert handler._public_patterns == []


class TestMatchesIgnoresNonWriteEdit:
    def test_bash_tool_never_matches(self) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "x", "pattern": "secretpath", "description": "d"}]
        )
        hook_input = {"tool_name": "Bash", "tool_input": {"command": "echo secretpath"}}
        assert handler.matches(hook_input) is False

    def test_clean_content_does_not_match(self) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "x", "pattern": "/var/www/vhosts", "description": "d"}]
        )
        assert handler.matches(_write_input("/tmp/f.txt", "nothing sensitive here")) is False


class TestPublicPatternMatching:
    def test_matching_content_is_denied(self) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "vhosts-path", "pattern": "/var/www/vhosts", "description": "server path"}]
        )
        hook_input = _write_input("/tmp/f.txt", "deploy to /var/www/vhosts/app")
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_deny_reason_names_the_pattern(self) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "vhosts-path", "pattern": "/var/www/vhosts", "description": "server path"}]
        )
        hook_input = _write_input("/tmp/f.txt", "deploy to /var/www/vhosts/app")
        result = handler.handle(hook_input)
        assert "vhosts-path" in (result.reason or "")

    def test_deny_reason_shows_matched_text(self) -> None:
        """Public patterns are SAFE to echo — this is what makes them fixable."""
        handler = _handler_with_public_patterns(
            [{"name": "vhosts-path", "pattern": "/var/www/vhosts", "description": "server path"}]
        )
        hook_input = _write_input("/tmp/f.txt", "deploy to /var/www/vhosts/app")
        result = handler.handle(hook_input)
        assert "/var/www/vhosts" in (result.reason or "")

    def test_edit_new_string_is_checked(self) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "vhosts-path", "pattern": "/var/www/vhosts", "description": "server path"}]
        )
        hook_input = _edit_input("/tmp/f.txt", new_string="now at /var/www/vhosts/app")
        assert handler.matches(hook_input) is True

    def test_edit_old_string_is_not_checked(self) -> None:
        """Only the ADDED content matters — removing sensitive text must not be blocked."""
        handler = _handler_with_public_patterns(
            [{"name": "vhosts-path", "pattern": "/var/www/vhosts", "description": "server path"}]
        )
        hook_input = _edit_input(
            "/tmp/f.txt", new_string="clean now", old_string="/var/www/vhosts/app"
        )
        assert handler.matches(hook_input) is False

    def test_invalid_regex_pattern_is_skipped_not_crashed(self) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "broken", "pattern": "([unclosed", "description": "d"}]
        )
        hook_input = _write_input("/tmp/f.txt", "([unclosed is literal text here")
        # Must not raise; invalid pattern simply never matches.
        assert handler.matches(hook_input) is False

    def test_multiple_patterns_first_match_wins(self) -> None:
        handler = _handler_with_public_patterns(
            [
                {"name": "first", "pattern": "alpha", "description": "d1"},
                {"name": "second", "pattern": "beta", "description": "d2"},
            ]
        )
        hook_input = _write_input("/tmp/f.txt", "contains beta only")
        result = handler.handle(hook_input)
        assert "second" in (result.reason or "")


class TestSecretListMatching:
    def test_missing_secret_file_is_inert(self, tmp_path: Path) -> None:
        handler = _handler_with_secret_file(tmp_path / "nonexistent.secret")
        hook_input = _write_input("/tmp/f.txt", "anything at all")
        assert handler.matches(hook_input) is False

    def test_empty_secret_file_is_inert(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("")
        handler = _handler_with_secret_file(secret_file)
        assert handler.matches(_write_input("/tmp/f.txt", "anything")) is False

    def test_comments_only_secret_file_is_inert(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("# nothing real here\n")
        handler = _handler_with_secret_file(secret_file)
        assert handler.matches(_write_input("/tmp/f.txt", "anything")) is False

    def test_matching_secret_term_is_denied(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("zzqx-nonsense-term\n")
        handler = _handler_with_secret_file(secret_file)
        hook_input = _write_input("/tmp/f.txt", "contains zzqx-nonsense-term here")
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_deny_reason_never_contains_the_term(self, tmp_path: Path) -> None:
        """THE core security property of this handler."""
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("zzqx-nonsense-term\n")
        handler = _handler_with_secret_file(secret_file)
        hook_input = _write_input("/tmp/f.txt", "contains zzqx-nonsense-term here")
        result = handler.handle(hook_input)
        assert "zzqx-nonsense-term" not in (result.reason or "")

    def test_deny_reason_never_contains_surrounding_context(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("zzqx-nonsense-term\n")
        handler = _handler_with_secret_file(secret_file)
        hook_input = _write_input(
            "/tmp/f.txt", "the host is called zzqx-nonsense-term in our infra"
        )
        result = handler.handle(hook_input)
        reason = result.reason or ""
        assert "zzqx-nonsense-term" not in reason
        assert "the host is called" not in reason
        assert "in our infra" not in reason

    def test_deny_reason_cites_entry_index_and_total(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("alpha\nzzqx-nonsense-term\ncharlie\n")
        handler = _handler_with_secret_file(secret_file)
        hook_input = _write_input("/tmp/f.txt", "contains zzqx-nonsense-term here")
        result = handler.handle(hook_input)
        reason = result.reason or ""
        assert "entry 2 of 3" in reason

    def test_matching_is_case_insensitive(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("zzqx-nonsense-term\n")
        handler = _handler_with_secret_file(secret_file)
        hook_input = _write_input("/tmp/f.txt", "CONTAINS ZZQX-NONSENSE-TERM HERE")
        assert handler.matches(hook_input) is True

    def test_regex_metacharacter_term_matches_literally(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("a.b*c\n")
        handler = _handler_with_secret_file(secret_file)
        assert handler.matches(_write_input("/tmp/f.txt", "has a.b*c literally")) is True
        assert handler.matches(_write_input("/tmp/f.txt", "has axbyc instead")) is False

    def test_regex_compile_failure_in_secret_terms_never_raises(self, tmp_path: Path) -> None:
        """Secret terms are matched as literal substrings — never compiled as regex."""
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("([unclosed\n")
        handler = _handler_with_secret_file(secret_file)
        # Must not raise, and must still be able to match the literal term.
        assert handler.matches(_write_input("/tmp/f.txt", "clean content")) is False
        assert handler.matches(_write_input("/tmp/f.txt", "has ([unclosed inside")) is True


class TestExcludePaths:
    def test_excluded_path_is_not_matched(self, tmp_path: Path) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "vhosts-path", "pattern": "/var/www/vhosts", "description": "d"}]
        )
        handler._exclude_paths = ["tests/fixtures/**"]
        hook_input = _write_input("/workspace/tests/fixtures/sample.txt", "/var/www/vhosts/example")
        with patch(
            "claude_code_hooks_daemon.utils.path_exclusion.resolve_project_root",
            return_value="/workspace",
        ):
            assert handler.matches(hook_input) is False


class TestSecretListSelfExclusion:
    """The word list itself is the one file that MUST be allowed to hold the terms.

    Without this, the handler bricks its own configuration: the first Write
    succeeds (the list is empty, so nothing matches yet), and every subsequent
    Edit to add, remove, or correct a term is denied by the very terms the file
    exists to declare. Discovered by dogfooding during Plan 00201 -- adding one
    term to this repo's own list was blocked as "entry 8 of 10".
    """

    def test_writing_the_secret_list_itself_is_not_matched(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "block-words.secret"
        secret_file.write_text("alpha-term\nbeta-term\n")
        handler = _handler_with_secret_file(secret_file)

        # Sanity: the same content in ANY other file is still caught, so this
        # test cannot pass merely because matching is broken.
        assert handler.matches(_write_input(str(tmp_path / "other.md"), "beta-term")) is True

        assert handler.matches(_write_input(str(secret_file), "alpha-term\nbeta-term\n")) is False

    def test_editing_the_secret_list_to_add_a_term_is_not_matched(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "block-words.secret"
        secret_file.write_text("alpha-term\n")
        handler = _handler_with_secret_file(secret_file)

        hook_input = _edit_input(str(secret_file), "alpha-term\n", "alpha-term\ngamma-term\n")
        assert handler.matches(hook_input) is False

    def test_relative_configured_path_still_self_excludes(self, tmp_path: Path) -> None:
        """The config value is repo-relative; the tool always sends an absolute path.

        A naive string comparison would miss, so resolution must happen on both
        sides before comparing.
        """
        secret_file = tmp_path / ".claude" / "block-words.secret"
        secret_file.parent.mkdir(parents=True)
        secret_file.write_text("alpha-term\n")

        handler = SensitiveContentHandler()
        handler._secret_word_list_path = ".claude/block-words.secret"
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content.resolve_project_root",
            return_value=str(tmp_path),
        ):
            assert handler.matches(_write_input(str(secret_file), "alpha-term\n")) is False

    def test_example_seed_file_is_still_checked(self, tmp_path: Path) -> None:
        """`.example` is TRACKED, so a real term pasted into it would be published."""
        secret_file = tmp_path / "block-words.secret"
        secret_file.write_text("alpha-term\n")
        handler = _handler_with_secret_file(secret_file)

        example = tmp_path / "block-words.secret.example"
        assert handler.matches(_write_input(str(example), "alpha-term\n")) is True


class TestGetClaudeMd:
    def test_returns_guidance_mentioning_no_echo(self) -> None:
        handler = SensitiveContentHandler()
        text = handler.get_claude_md()
        assert text is not None
        assert "block-words.secret" in text
        assert "never" in text.lower() or "not shown" in text.lower()


class TestAcceptanceTests:
    def test_defines_at_least_two_tests(self) -> None:
        handler = SensitiveContentHandler()
        assert len(handler.get_acceptance_tests()) >= 2
