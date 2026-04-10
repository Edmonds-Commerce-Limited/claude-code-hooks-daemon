"""Tests for GitignoreSafetyCheckerHandler."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.handlers.session_start.gitignore_safety_checker import (
    _REQUIRED_GITIGNORE_PATTERNS,
    GitignoreSafetyCheckerHandler,
)


class TestGitignoreSafetyCheckerInit:
    """Handler initialisation tests."""

    @pytest.fixture
    def handler(self) -> GitignoreSafetyCheckerHandler:
        return GitignoreSafetyCheckerHandler()

    def test_init_sets_correct_name(self, handler: GitignoreSafetyCheckerHandler) -> None:
        assert handler.name == "gitignore-safety-checker"

    def test_init_sets_correct_priority(self, handler: GitignoreSafetyCheckerHandler) -> None:
        assert handler.priority == 54

    def test_init_sets_terminal_false(self, handler: GitignoreSafetyCheckerHandler) -> None:
        assert handler.terminal is False


class TestGitignoreSafetyCheckerMatches:
    """matches() tests."""

    @pytest.fixture
    def handler(self) -> GitignoreSafetyCheckerHandler:
        return GitignoreSafetyCheckerHandler()

    def test_matches_new_session_returns_true(self, handler: GitignoreSafetyCheckerHandler) -> None:
        """New session (no transcript) should match."""
        hook_input = {"hook_event_name": "SessionStart"}
        assert handler.matches(hook_input) is True

    def test_matches_resume_session_returns_false(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Resume session (large transcript) should not match."""
        transcript = tmp_path / "transcript.json"
        transcript.write_text("x" * 200)
        hook_input = {"hook_event_name": "SessionStart", "transcript_path": str(transcript)}
        assert handler.matches(hook_input) is False

    def test_matches_small_transcript_returns_true(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Tiny transcript (new session) should match."""
        transcript = tmp_path / "transcript.json"
        transcript.write_text("{}")
        hook_input = {"hook_event_name": "SessionStart", "transcript_path": str(transcript)}
        assert handler.matches(hook_input) is True


class TestFindMissingEntries:
    """_find_missing_entries() tests."""

    @pytest.fixture
    def handler(self) -> GitignoreSafetyCheckerHandler:
        return GitignoreSafetyCheckerHandler()

    def test_returns_empty_when_root_gitignore_covers_all(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """All entries present in root .gitignore → no missing."""
        gitignore = tmp_path / ".gitignore"
        # Write all required root patterns
        lines = [f"{root}\n" for root, _, _ in _REQUIRED_GITIGNORE_PATTERNS]
        gitignore.write_text("".join(lines))
        assert handler._find_missing_entries(tmp_path) == []

    def test_returns_empty_when_claude_gitignore_covers_all(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Scoped entries in .claude/.gitignore + root-only entries in .gitignore → no missing."""
        # Patterns with a scoped_pattern go into .claude/.gitignore
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        claude_gitignore = claude_dir / ".gitignore"
        scoped_lines = [f"{scoped}\n" for _, scoped, _ in _REQUIRED_GITIGNORE_PATTERNS if scoped]
        claude_gitignore.write_text("".join(scoped_lines))
        # Patterns with empty scoped_pattern must be in root .gitignore
        root_only = [f"{root}\n" for root, scoped, _ in _REQUIRED_GITIGNORE_PATTERNS if not scoped]
        if root_only:
            (tmp_path / ".gitignore").write_text("".join(root_only))
        assert handler._find_missing_entries(tmp_path) == []

    def test_returns_descriptions_for_missing_entries(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Missing entries → returns list of descriptions."""
        # No gitignore files at all
        missing = handler._find_missing_entries(tmp_path)
        assert len(missing) == len(_REQUIRED_GITIGNORE_PATTERNS)
        for _, _, description in _REQUIRED_GITIGNORE_PATTERNS:
            assert description in missing

    def test_pre_inject_pattern_is_required(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Regression: .CLAUDE.md.pre-inject must be in required patterns."""
        # Only worktrees covered, pre-inject missing
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".claude/worktrees/\n")
        missing = handler._find_missing_entries(tmp_path)
        assert any(".CLAUDE.md.pre-inject" in m for m in missing)

    def test_pre_inject_satisfied_in_root_gitignore(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """pre-inject entry in root .gitignore satisfies requirement."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".claude/worktrees/\n.CLAUDE.md.pre-inject\n")
        missing = handler._find_missing_entries(tmp_path)
        assert missing == []

    def test_ignores_commented_lines(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Commented-out entries should not count as present."""
        gitignore = tmp_path / ".gitignore"
        root_pattern = _REQUIRED_GITIGNORE_PATTERNS[0][0]
        gitignore.write_text(f"# {root_pattern}\n")
        missing = handler._find_missing_entries(tmp_path)
        # Still missing since it's a comment
        assert any(_REQUIRED_GITIGNORE_PATTERNS[0][2] in m for m in missing)

    def test_handles_missing_gitignore_files_gracefully(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """No gitignore files → all entries missing, no crash."""
        missing = handler._find_missing_entries(tmp_path)
        assert isinstance(missing, list)


class TestComputeGitignoreHash:
    """_compute_gitignore_hash() tests."""

    @pytest.fixture
    def handler(self) -> GitignoreSafetyCheckerHandler:
        return GitignoreSafetyCheckerHandler()

    def test_returns_string(self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path) -> None:
        result = handler._compute_gitignore_hash(tmp_path)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_consistent_for_same_content(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        (tmp_path / ".gitignore").write_text("untracked/\n.claude/worktrees/\n")
        h1 = handler._compute_gitignore_hash(tmp_path)
        h2 = handler._compute_gitignore_hash(tmp_path)
        assert h1 == h2

    def test_changes_when_root_gitignore_changes(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        (tmp_path / ".gitignore").write_text("untracked/\n")
        h1 = handler._compute_gitignore_hash(tmp_path)
        (tmp_path / ".gitignore").write_text("untracked/\n.claude/worktrees/\n")
        h2 = handler._compute_gitignore_hash(tmp_path)
        assert h1 != h2

    def test_changes_when_claude_gitignore_changes(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        h1 = handler._compute_gitignore_hash(tmp_path)
        (claude_dir / ".gitignore").write_text("worktrees/\n")
        h2 = handler._compute_gitignore_hash(tmp_path)
        assert h1 != h2

    def test_stable_with_no_files(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """No gitignore files → returns stable empty hash."""
        h = handler._compute_gitignore_hash(tmp_path)
        assert h == handler._compute_gitignore_hash(tmp_path)


class TestCacheLogic:
    """Cache read/write/validation tests."""

    @pytest.fixture
    def handler(self) -> GitignoreSafetyCheckerHandler:
        return GitignoreSafetyCheckerHandler()

    def test_is_cache_valid_returns_false_when_no_file(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        cache_file = tmp_path / "cache.json"
        assert handler._is_cache_valid(cache_file, "abc123") is False

    def test_is_cache_valid_returns_true_when_hash_matches(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps({"gitignore_hash": "abc123", "missing_entries": []}))
        assert handler._is_cache_valid(cache_file, "abc123") is True

    def test_is_cache_valid_returns_false_when_hash_differs(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        cache_file = tmp_path / "cache.json"
        cache_file.write_text(json.dumps({"gitignore_hash": "abc123", "missing_entries": []}))
        assert handler._is_cache_valid(cache_file, "different") is False

    def test_is_cache_valid_returns_false_for_corrupt_json(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        cache_file = tmp_path / "cache.json"
        cache_file.write_text("not valid json{{{")
        assert handler._is_cache_valid(cache_file, "abc123") is False

    def test_write_and_read_cache(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        cache_file = tmp_path / "cache.json"
        handler._write_cache(cache_file, "abc123", ["entry1"])
        assert cache_file.exists()
        data = json.loads(cache_file.read_text())
        assert data["gitignore_hash"] == "abc123"
        assert data["missing_entries"] == ["entry1"]

    def test_get_cached_missing_entries(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        cache_file = tmp_path / "cache.json"
        handler._write_cache(cache_file, "abc123", ["some missing entry"])
        result = handler._get_cached_missing_entries(cache_file)
        assert result == ["some missing entry"]

    def test_get_cached_missing_entries_returns_none_on_error(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        cache_file = tmp_path / "nonexistent.json"
        assert handler._get_cached_missing_entries(cache_file) is None


class TestHandle:
    """handle() integration tests."""

    @pytest.fixture
    def handler(self) -> GitignoreSafetyCheckerHandler:
        return GitignoreSafetyCheckerHandler()

    def test_handle_returns_allow_when_all_present(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """No missing entries → ALLOW with no advisory context."""
        # Write all required root patterns to root .gitignore
        gitignore = tmp_path / ".gitignore"
        lines = [f"{root}\n" for root, _, _ in _REQUIRED_GITIGNORE_PATTERNS]
        gitignore.write_text("".join(lines))

        with patch.object(handler, "_get_project_root", return_value=tmp_path):
            with patch.object(handler, "_get_cache_file", return_value=tmp_path / "cache.json"):
                result = handler.handle({})

        assert result.decision == "allow"
        # No advisory lines about missing entries
        context_text = "\n".join(result.context)
        assert "MISSING" not in context_text.upper() or len(result.context) == 0

    def test_handle_returns_advisory_when_entries_missing(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Missing entries → ALLOW with advisory context listing them."""
        # Empty project - no gitignore files
        with patch.object(handler, "_get_project_root", return_value=tmp_path):
            with patch.object(handler, "_get_cache_file", return_value=tmp_path / "cache.json"):
                result = handler.handle({})

        assert result.decision == "allow"
        assert len(result.context) > 0
        context_text = "\n".join(result.context)
        # Should mention the missing entry
        assert _REQUIRED_GITIGNORE_PATTERNS[0][2] in context_text

    def test_handle_uses_cache_on_second_call(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Second call with same gitignore → reads from cache, no re-scan."""
        gitignore = tmp_path / ".gitignore"
        lines = [f"{root}\n" for root, _, _ in _REQUIRED_GITIGNORE_PATTERNS]
        gitignore.write_text("".join(lines))
        cache_file = tmp_path / "cache.json"

        with patch.object(handler, "_get_project_root", return_value=tmp_path):
            with patch.object(handler, "_get_cache_file", return_value=cache_file):
                handler.handle({})  # first call writes cache
                with patch.object(
                    handler, "_find_missing_entries", wraps=handler._find_missing_entries
                ) as mock_find:
                    handler.handle({})  # second call should use cache
                    mock_find.assert_not_called()

    def test_handle_rechecks_when_gitignore_changes(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """After gitignore content changes → re-scans (cache miss)."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("untracked/\n")
        cache_file = tmp_path / "cache.json"

        with patch.object(handler, "_get_project_root", return_value=tmp_path):
            with patch.object(handler, "_get_cache_file", return_value=cache_file):
                handler.handle({})  # first call, caches old hash

                # Modify .gitignore
                lines = [f"{root}\n" for root, _, _ in _REQUIRED_GITIGNORE_PATTERNS]
                gitignore.write_text("untracked/\n" + "".join(lines))

                with patch.object(
                    handler, "_find_missing_entries", wraps=handler._find_missing_entries
                ) as mock_find:
                    handler.handle({})  # should re-scan due to hash change
                    mock_find.assert_called_once()


class TestExceptionPaths:
    """Tests for exception handling / fallback paths."""

    @pytest.fixture
    def handler(self) -> GitignoreSafetyCheckerHandler:
        return GitignoreSafetyCheckerHandler()

    def test_get_project_root_fallback_on_runtime_error(
        self, handler: GitignoreSafetyCheckerHandler
    ) -> None:
        """Falls back to cwd when ProjectContext raises RuntimeError."""
        with patch(
            "claude_code_hooks_daemon.handlers.session_start.gitignore_safety_checker.ProjectContext.project_root",
            side_effect=RuntimeError("not initialised"),
        ):
            result = handler._get_project_root()
        assert result is not None
        assert isinstance(result, Path)

    def test_get_cache_file_fallback_on_error(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Falls back to cwd/untracked/ when daemon_untracked_dir raises."""
        with patch(
            "claude_code_hooks_daemon.handlers.session_start.gitignore_safety_checker.ProjectContext.daemon_untracked_dir",
            side_effect=RuntimeError("no dir"),
        ):
            with patch(
                "claude_code_hooks_daemon.handlers.session_start.gitignore_safety_checker.Path.cwd",
                return_value=tmp_path,
            ):
                result = handler._get_cache_file()
        assert result.name == "gitignore_safety_cache.json"

    def test_compute_gitignore_hash_handles_read_error(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Hash computation skips files that exist but raise OSError on read."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("placeholder")
        with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            result = handler._compute_gitignore_hash(tmp_path)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_read_gitignore_lines_handles_read_error(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Skips files that exist but raise OSError on read."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("placeholder")
        with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            result = handler._read_gitignore_lines(tmp_path)
        assert result == set()

    def test_write_cache_handles_write_error(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Write failure is logged at debug level and does not raise."""
        cache_file = tmp_path / "cache.json"
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            handler._write_cache(cache_file, "abc123", [])  # should not raise

    def test_is_resume_session_handles_os_error(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """OSError from stat() → returns False (treat as new session)."""
        transcript = tmp_path / "t.json"
        transcript.write_text("x")
        with patch.object(Path, "stat", side_effect=OSError("stat failed")):
            result = handler._is_resume_session({"transcript_path": str(transcript)})
        assert result is False

    def test_handle_returns_allow_when_project_root_none(
        self, handler: GitignoreSafetyCheckerHandler
    ) -> None:
        """When _get_project_root returns None, handle returns ALLOW silently."""
        with patch.object(handler, "_get_project_root", return_value=None):
            result = handler.handle({})
        assert result.decision == "allow"
        assert result.context == []

    def test_handle_rescans_when_cache_valid_but_data_corrupt(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """If cache hash matches but data is None (corrupt), falls through to re-scan."""
        gitignore = tmp_path / ".gitignore"
        lines = [f"{root}\n" for root, _, _ in _REQUIRED_GITIGNORE_PATTERNS]
        gitignore.write_text("".join(lines))
        cache_file = tmp_path / "cache.json"

        with patch.object(handler, "_get_project_root", return_value=tmp_path):
            with patch.object(handler, "_get_cache_file", return_value=cache_file):
                with patch.object(handler, "_is_cache_valid", return_value=True):
                    with patch.object(handler, "_get_cached_missing_entries", return_value=None):
                        with patch.object(
                            handler, "_find_missing_entries", return_value=[]
                        ) as mock_find:
                            handler.handle({})
                            mock_find.assert_called_once()


class TestBuildResult:
    """Tests for _build_result edge cases."""

    @pytest.fixture
    def handler(self) -> GitignoreSafetyCheckerHandler:
        return GitignoreSafetyCheckerHandler()

    def test_build_result_skips_fix_hint_for_present_pattern(
        self, handler: GitignoreSafetyCheckerHandler
    ) -> None:
        """If missing list doesn't contain a pattern's description, its fix hint is omitted."""
        # Pass a description that doesn't match any pattern's exact description
        missing = ["some completely different missing entry"]
        result = handler._build_result(missing)
        assert result.decision == "allow"
        # Advisory context present
        assert len(result.context) > 0
        # But the fix hint for .claude/worktrees should NOT appear
        context_text = "\n".join(result.context)
        assert ".claude/worktrees/" not in context_text


class TestRequiredPatterns:
    """Validate _REQUIRED_GITIGNORE_PATTERNS constant structure."""

    def test_patterns_is_tuple(self) -> None:
        assert isinstance(_REQUIRED_GITIGNORE_PATTERNS, tuple)

    def test_each_entry_has_three_elements(self) -> None:
        for entry in _REQUIRED_GITIGNORE_PATTERNS:
            assert len(entry) == 3, f"Expected (root_pattern, scoped_pattern, description): {entry}"

    def test_contains_claude_worktrees_entry(self) -> None:
        root_patterns = [root for root, _, _ in _REQUIRED_GITIGNORE_PATTERNS]
        assert any(".claude/worktrees" in p for p in root_patterns)
