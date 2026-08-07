"""Tests for utils.secret_redaction — the ONE place the secret word list is
loaded, matched, and used to redact text (Plan 00201).

No-echo threat model: a term that matches must never appear verbatim in any
value this module returns except the term list itself (which callers must
never surface directly — only an index into it).
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.utils import secret_redaction as sr


class TestResolveSecretWordListPath:
    def test_default_path_is_relative_to_project_root(self, tmp_path: Path) -> None:
        result = sr.resolve_secret_word_list_path(None, tmp_path)
        assert result == tmp_path / ".claude" / "block-words.secret"

    def test_empty_string_uses_default(self, tmp_path: Path) -> None:
        result = sr.resolve_secret_word_list_path("", tmp_path)
        assert result == tmp_path / ".claude" / "block-words.secret"

    def test_configured_relative_path_is_joined_to_project_root(self, tmp_path: Path) -> None:
        result = sr.resolve_secret_word_list_path("custom/words.secret", tmp_path)
        assert result == tmp_path / "custom" / "words.secret"

    def test_configured_absolute_path_is_used_verbatim(self, tmp_path: Path) -> None:
        absolute = tmp_path / "elsewhere" / "words.secret"
        result = sr.resolve_secret_word_list_path(str(absolute), tmp_path)
        assert result == absolute


class TestLoadSecretTerms:
    def test_missing_file_returns_empty_tuple(self, tmp_path: Path) -> None:
        assert sr.load_secret_terms(tmp_path / "nonexistent.secret") == ()

    def test_empty_file_returns_empty_tuple(self, tmp_path: Path) -> None:
        path = tmp_path / "words.secret"
        path.write_text("")
        assert sr.load_secret_terms(path) == ()

    def test_comments_only_file_returns_empty_tuple(self, tmp_path: Path) -> None:
        path = tmp_path / "words.secret"
        path.write_text("# just a comment\n# another\n")
        assert sr.load_secret_terms(path) == ()

    def test_blank_lines_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "words.secret"
        path.write_text("\n\nalpha\n\n\nbeta\n\n")
        assert sr.load_secret_terms(path) == ("alpha", "beta")

    def test_comments_and_terms_mixed(self, tmp_path: Path) -> None:
        path = tmp_path / "words.secret"
        path.write_text("# header comment\nalpha\n# inline note\nbeta\n")
        assert sr.load_secret_terms(path) == ("alpha", "beta")

    def test_preserves_file_order_for_index_stability(self, tmp_path: Path) -> None:
        path = tmp_path / "words.secret"
        path.write_text("zulu\nalpha\nmike\n")
        assert sr.load_secret_terms(path) == ("zulu", "alpha", "mike")

    def test_whitespace_around_terms_is_stripped(self, tmp_path: Path) -> None:
        path = tmp_path / "words.secret"
        path.write_text("  alpha  \n\tbeta\t\n")
        assert sr.load_secret_terms(path) == ("alpha", "beta")


class TestCachedSecretTerms:
    def test_missing_file_is_inert(self, tmp_path: Path) -> None:
        sr.reset_terms_cache()
        assert sr.get_cached_secret_terms(tmp_path / "nonexistent.secret") == ()

    def test_reads_file_on_first_call(self, tmp_path: Path) -> None:
        sr.reset_terms_cache()
        path = tmp_path / "words.secret"
        path.write_text("alpha\n")
        assert sr.get_cached_secret_terms(path) == ("alpha",)

    def test_caches_until_mtime_changes(self, tmp_path: Path) -> None:
        sr.reset_terms_cache()
        path = tmp_path / "words.secret"
        path.write_text("alpha\n")
        first = sr.get_cached_secret_terms(path)
        # Rewrite without changing mtime resolution granularity issues by
        # patching load_secret_terms to prove the cache short-circuits.
        with patch.object(sr, "load_secret_terms", return_value=("SHOULD_NOT_BE_CALLED",)):
            second = sr.get_cached_secret_terms(path)
        assert first == second == ("alpha",)

    def test_reloads_when_mtime_changes(self, tmp_path: Path) -> None:
        sr.reset_terms_cache()
        path = tmp_path / "words.secret"
        path.write_text("alpha\n")
        first = sr.get_cached_secret_terms(path)
        # Force a distinct mtime (filesystem mtime resolution can be coarse).
        new_mtime = (path.stat().st_mtime or 0) + 5
        path.write_text("beta\n")
        import os

        os.utime(path, (new_mtime, new_mtime))
        second = sr.get_cached_secret_terms(path)
        assert first == ("alpha",)
        assert second == ("beta",)

    def test_reset_terms_cache_clears_state(self, tmp_path: Path) -> None:
        path = tmp_path / "words.secret"
        path.write_text("alpha\n")
        sr.get_cached_secret_terms(path)
        sr.reset_terms_cache()
        with patch.object(sr, "load_secret_terms", return_value=("beta",)) as mock_load:
            result = sr.get_cached_secret_terms(path)
        mock_load.assert_called_once()
        assert result == ("beta",)


class TestFindFirstMatchIndex:
    def test_no_terms_returns_none(self) -> None:
        assert sr.find_first_match_index("hello world", ()) is None

    def test_no_match_returns_none(self) -> None:
        assert sr.find_first_match_index("hello world", ("zulu", "mike")) is None

    def test_match_returns_one_based_index(self) -> None:
        assert sr.find_first_match_index("contains alpha here", ("zulu", "alpha", "mike")) == 2

    def test_match_is_case_insensitive(self) -> None:
        assert sr.find_first_match_index("contains ALPHA here", ("alpha",)) == 1

    def test_regex_metacharacter_term_matches_literally(self) -> None:
        """A term like 'a.b*c' must be matched as the literal string, not a pattern."""
        assert sr.find_first_match_index("prefix a.b*c suffix", ("a.b*c",)) == 1
        # The "pattern interpretation" would match "axbyc" too (. any char, * repeat) -
        # literal matching must NOT match that.
        assert sr.find_first_match_index("prefix axbyc suffix", ("a.b*c",)) is None

    def test_empty_term_is_skipped(self) -> None:
        assert sr.find_first_match_index("anything", ("", "alpha")) is None
        assert sr.find_first_match_index("has alpha", ("", "alpha")) == 2


class TestRedactText:
    def test_no_terms_returns_text_unchanged(self) -> None:
        assert sr.redact_text("hello world", ()) == "hello world"

    def test_no_match_returns_text_unchanged(self) -> None:
        assert sr.redact_text("hello world", ("zulu",)) == "hello world"

    def test_matched_term_is_replaced(self) -> None:
        result = sr.redact_text("contains alpha here", ("alpha",))
        assert "alpha" not in result
        assert sr.REDACTED_PLACEHOLDER in result

    def test_matched_term_is_replaced_case_insensitively(self) -> None:
        result = sr.redact_text("contains ALPHA here", ("alpha",))
        assert "alpha" not in result.lower()

    def test_all_occurrences_are_replaced(self) -> None:
        result = sr.redact_text("alpha and alpha again", ("alpha",))
        assert "alpha" not in result.lower()
        assert result.count(sr.REDACTED_PLACEHOLDER) == 2

    def test_regex_metacharacter_term_redacted_literally(self) -> None:
        result = sr.redact_text("prefix a.b*c suffix", ("a.b*c",))
        assert "a.b*c" not in result
        # A literal-unrelated string that would match if '.' and '*' were
        # regex metacharacters must survive untouched.
        untouched = sr.redact_text("prefix axbyc suffix", ("a.b*c",))
        assert untouched == "prefix axbyc suffix"


class TestRedactStructure:
    def test_redacts_nested_strings(self) -> None:
        payload = {"tool_input": {"content": "has alpha in it"}, "other": ["alpha", "clean"]}
        result = sr.redact_structure(payload, ("alpha",))
        assert "alpha" not in str(result)

    def test_non_string_values_untouched(self) -> None:
        payload = {"count": 5, "flag": True, "nothing": None}
        result = sr.redact_structure(payload, ("alpha",))
        assert result == payload

    def test_empty_terms_returns_equivalent_structure(self) -> None:
        payload = {"a": ["b", "c"], "d": "e"}
        assert sr.redact_structure(payload, ()) == payload


class TestActiveSecretTerms:
    def test_uninitialized_project_context_returns_empty(self) -> None:
        sr.reset_active_path_cache()
        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext._initialized", False
        ):
            assert sr.get_active_secret_terms() == ()

    def test_resolves_and_caches_configured_path(self, tmp_path: Path) -> None:
        sr.reset_active_path_cache()
        sr.reset_terms_cache()
        secret_file = tmp_path / ".claude" / "block-words.secret"
        secret_file.parent.mkdir(parents=True)
        secret_file.write_text("alpha\n")

        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext._initialized", True
        ), patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root",
            return_value=tmp_path,
        ), patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.config_path",
            return_value=tmp_path / ".claude" / "hooks-daemon.yaml",
        ):
            result = sr.get_active_secret_terms()
        assert result == ("alpha",)

    def test_reset_active_path_cache_forces_re_resolution(self, tmp_path: Path) -> None:
        sr.reset_active_path_cache()
        sr.reset_terms_cache()
        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext._initialized", False
        ):
            assert sr.get_active_secret_terms() == ()
        sr.reset_active_path_cache()
        secret_file = tmp_path / ".claude" / "block-words.secret"
        secret_file.parent.mkdir(parents=True)
        secret_file.write_text("beta\n")
        with patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext._initialized", True
        ), patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.project_root",
            return_value=tmp_path,
        ), patch(
            "claude_code_hooks_daemon.core.project_context.ProjectContext.config_path",
            return_value=tmp_path / ".claude" / "hooks-daemon.yaml",
        ):
            assert sr.get_active_secret_terms() == ("beta",)


@pytest.fixture(autouse=True)
def _reset_module_caches() -> None:
    """Isolate every test from the process-lifetime caches this module keeps."""
    sr.reset_terms_cache()
    sr.reset_active_path_cache()
    yield
    sr.reset_terms_cache()
    sr.reset_active_path_cache()
