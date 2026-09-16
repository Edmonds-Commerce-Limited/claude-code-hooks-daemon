"""Tests for GitignoreSafetyCheckerHandler."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.core.project_context import ProjectContext
from claude_code_hooks_daemon.handlers.session_start.gitignore_safety_checker import (
    GitignoreSafetyCheckerHandler,
    _required_gitignore_patterns,
)
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.secret_file_matching import DEFAULT_PROTECTED_PATTERNS


def _write_all_required(project_root: Path, *, omitting: str = "") -> None:
    """A `.gitignore` satisfying every required entry, optionally minus one.

    Derived from the constant rather than spelled out: the required list is
    itself derived from the protected globs, and restating them in a test
    would recreate the third copy Plan 00412 F-HYG-1 exists to remove.
    """
    lines = [
        f"{root}\n"
        for root, _, _ in _required_gitignore_patterns()
        if not omitting or root != omitting
    ]
    (project_root / ".gitignore").write_text("".join(lines))


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
        lines = [f"{root}\n" for root, _, _ in _required_gitignore_patterns()]
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
        scoped_lines = [f"{scoped}\n" for _, scoped, _ in _required_gitignore_patterns() if scoped]
        claude_gitignore.write_text("".join(scoped_lines))
        # Patterns with empty scoped_pattern must be in root .gitignore
        root_only = [
            f"{root}\n" for root, scoped, _ in _required_gitignore_patterns() if not scoped
        ]
        if root_only:
            (tmp_path / ".gitignore").write_text("".join(root_only))
        assert handler._find_missing_entries(tmp_path) == []

    def test_returns_descriptions_for_missing_entries(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Missing entries → returns list of descriptions."""
        # No gitignore files at all
        missing = handler._find_missing_entries(tmp_path)
        assert len(missing) == len(_required_gitignore_patterns())
        for _, _, description in _required_gitignore_patterns():
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
        _write_all_required(tmp_path)
        missing = handler._find_missing_entries(tmp_path)
        assert missing == []

    def test_scheduled_tasks_lock_pattern_is_required(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Regression: .claude/scheduled_tasks.lock must be in required patterns."""
        # Only worktrees + pre-inject covered, scheduled_tasks.lock missing
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".claude/worktrees/\n.CLAUDE.md.pre-inject\n")
        missing = handler._find_missing_entries(tmp_path)
        assert any("scheduled_tasks.lock" in m for m in missing)

    def test_scheduled_tasks_lock_satisfied_in_root_gitignore(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """scheduled_tasks.lock entry in root .gitignore satisfies requirement."""
        _write_all_required(tmp_path)
        missing = handler._find_missing_entries(tmp_path)
        assert missing == []

    def test_secret_glob_pattern_is_required(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Regression: *.secret must be in required patterns (sensitive_content secret list)."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(
            ".claude/worktrees/\n.CLAUDE.md.pre-inject\n.claude/scheduled_tasks.lock\n"
        )
        missing = handler._find_missing_entries(tmp_path)
        assert any("*.secret" in m for m in missing)

    @pytest.mark.parametrize("protected", DEFAULT_PROTECTED_PATTERNS)
    def test_each_protected_glob_is_required_individually(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path, protected: str
    ) -> None:
        """Every protected glob, one at a time, with the rest satisfied.

        Parametrised over the constant so a pattern ADDED to the protected
        list arrives here already covered — the previous pair of hand-written
        cases could not, which is how the two lists drifted apart.
        """
        _write_all_required(tmp_path, omitting=protected)

        missing = handler._find_missing_entries(tmp_path)

        assert any(protected in entry for entry in missing)

    def test_secret_patterns_satisfied_in_root_gitignore(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Every required entry present in root .gitignore satisfies the check."""
        _write_all_required(tmp_path)
        missing = handler._find_missing_entries(tmp_path)
        assert missing == []

    def test_ignores_commented_lines(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Commented-out entries should not count as present."""
        gitignore = tmp_path / ".gitignore"
        root_pattern = _required_gitignore_patterns()[0][0]
        gitignore.write_text(f"# {root_pattern}\n")
        missing = handler._find_missing_entries(tmp_path)
        # Still missing since it's a comment
        assert any(_required_gitignore_patterns()[0][2] in m for m in missing)

    def test_handles_missing_gitignore_files_gracefully(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """No gitignore files → all entries missing, no crash."""
        missing = handler._find_missing_entries(tmp_path)
        assert isinstance(missing, list)

    def test_negation_line_does_not_satisfy_requirement(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """A '!'-negation line containing the pattern must NOT mark it covered.

        '!.claude/worktrees' un-ignores the path, so the requirement is unmet —
        substring matching wrongly treated it as satisfied.
        """
        worktrees_desc = _required_gitignore_patterns()[0][2]
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(
            "!.claude/worktrees\n.CLAUDE.md.pre-inject\n.claude/scheduled_tasks.lock\n"
        )
        missing = handler._find_missing_entries(tmp_path)
        assert worktrees_desc in missing

    def test_unrelated_substring_line_does_not_satisfy_requirement(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """An unrelated line that merely contains the pattern as a substring is not coverage.

        '.claude/worktrees-archive/' does not ignore '.claude/worktrees', so the
        worktrees requirement must still be reported missing.
        """
        worktrees_desc = _required_gitignore_patterns()[0][2]
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(
            ".claude/worktrees-archive/\n.CLAUDE.md.pre-inject\n.claude/scheduled_tasks.lock\n"
        )
        missing = handler._find_missing_entries(tmp_path)
        assert worktrees_desc in missing

    def test_directory_prefix_entry_covers_nested_pattern(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """An ancestor-directory ignore entry covers a nested required path.

        '.claude/' ignores everything under .claude including the worktrees path,
        so the worktrees requirement is satisfied by the directory entry.
        """
        worktrees_desc = _required_gitignore_patterns()[0][2]
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".claude/\n.CLAUDE.md.pre-inject\n.claude/scheduled_tasks.lock\n")
        missing = handler._find_missing_entries(tmp_path)
        assert worktrees_desc not in missing


class TestEffectiveProtectedPatternsDeterminesRequiredEntries:
    """D1: the never-commit list must track the project's EFFECTIVE protected set.

    `secret_file_guard.options.protected_paths` merges onto the shipped
    defaults (additive is the default mode) -- a glob added there must show up
    here too, or a file the guard refuses to READ stays perfectly committable.
    """

    def setup_method(self) -> None:
        sfm.reset_configured_patterns_cache()

    def teardown_method(self) -> None:
        sfm.reset_configured_patterns_cache()

    def test_a_project_configured_protected_glob_is_required(self, tmp_path: Path) -> None:
        handler = GitignoreSafetyCheckerHandler()
        config_path = tmp_path / "hooks-daemon.yaml"
        config_path.write_text(
            "version: '2.0'\n"
            "handlers:\n"
            "  pre_tool_use:\n"
            "    secret_file_guard:\n"
            "      options:\n"
            "        protected_paths:\n"
            "          - '*.creds'\n"
        )

        with (
            patch.object(ProjectContext, "is_initialized", return_value=True),
            patch.object(ProjectContext, "config_path", return_value=config_path),
        ):
            missing = handler._find_missing_entries(tmp_path)

        assert any("*.creds" in entry for entry in missing)


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
        lines = [f"{root}\n" for root, _, _ in _required_gitignore_patterns()]
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
        assert _required_gitignore_patterns()[0][2] in context_text

    def test_handle_uses_cache_on_second_call(
        self, handler: GitignoreSafetyCheckerHandler, tmp_path: Path
    ) -> None:
        """Second call with same gitignore → reads from cache, no re-scan."""
        gitignore = tmp_path / ".gitignore"
        lines = [f"{root}\n" for root, _, _ in _required_gitignore_patterns()]
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
                lines = [f"{root}\n" for root, _, _ in _required_gitignore_patterns()]
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
        lines = [f"{root}\n" for root, _, _ in _required_gitignore_patterns()]
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
    """Validate _required_gitignore_patterns() constant structure."""

    def test_patterns_is_tuple(self) -> None:
        assert isinstance(_required_gitignore_patterns(), tuple)

    def test_each_entry_has_three_elements(self) -> None:
        for entry in _required_gitignore_patterns():
            assert len(entry) == 3, f"Expected (root_pattern, scoped_pattern, description): {entry}"

    def test_contains_claude_worktrees_entry(self) -> None:
        root_patterns = [root for root, _, _ in _required_gitignore_patterns()]
        assert any(".claude/worktrees" in p for p in root_patterns)


class TestEveryProtectedPatternIsAlsoGitignored:
    """Plan 00412 F-HYG-1: two lists answering one question, worded differently.

    `secret_file_matching.DEFAULT_PROTECTED_PATTERNS` decides which files must
    never be READ. This handler decided, separately and by hand, which must
    never be COMMITTED. A file whose contents may not enter context certainly
    may not enter git history, so the second list must cover the first — and it
    did not: it carried two hand-written approximations of one protected glob
    and none of the vault-password or SSH-key shapes.

    The approximation was the sharp end. A `.gitignore` line matching only the
    exact suffix does NOT match a `.bak` beside it, so a project that fully
    satisfied the advisory still committed a file this daemon refuses to read.

    Asserted against the constant rather than against spelled-out globs, on
    purpose: restating them here would recreate the second copy this test
    exists to forbid — and `secret_file_guard` denies authoring them anyway,
    which is the daemon making the same point mechanically.
    """

    def test_the_required_list_covers_every_protected_pattern(self) -> None:
        required = {root for root, _, _ in _required_gitignore_patterns()}

        assert set(DEFAULT_PROTECTED_PATTERNS) <= required

    def test_each_derived_entry_carries_a_description(self) -> None:
        """The advisory names what it is asking for; a bare glob explains nothing."""
        for root, _, description in _required_gitignore_patterns():
            if root in set(DEFAULT_PROTECTED_PATTERNS):
                assert description.strip(), root

    def test_a_project_ignoring_none_of_them_is_told_about_every_one(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("build/\n")
        handler = GitignoreSafetyCheckerHandler()

        missing = handler._find_missing_entries(tmp_path)

        assert len(missing) == len(_required_gitignore_patterns())

    def test_the_static_daemon_artefacts_are_still_required(self) -> None:
        """Deriving the protected globs must not drop what was already there."""
        required = {root for root, _, _ in _required_gitignore_patterns()}

        assert ".claude/worktrees" in required
        assert ".CLAUDE.md.pre-inject" in required
        assert ".claude/scheduled_tasks.lock" in required
