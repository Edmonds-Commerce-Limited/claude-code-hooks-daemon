"""Tests for security strategy common utilities."""

import pytest

from claude_code_hooks_daemon.strategies.security.common import (
    SKIP_PATTERNS,
    UNIVERSAL_EXTENSION,
    should_skip,
)


class TestShouldSkip:
    """Test should_skip() function."""

    def test_skips_vendor_directory(self):
        assert should_skip("/workspace/vendor/lib/auth.php") is True

    def test_skips_node_modules(self):
        assert should_skip("/workspace/node_modules/pkg/index.js") is True

    def test_skips_test_fixtures(self):
        assert should_skip("/workspace/tests/fixtures/payload.php") is True

    def test_skips_test_assets(self):
        assert should_skip("/workspace/tests/assets/payload.js") is True

    def test_skips_env_example(self):
        assert should_skip("/workspace/.env.example") is True

    def test_skips_docs(self):
        assert should_skip("/workspace/docs/security.md") is True

    def test_skips_claude_dir(self):
        assert should_skip("/workspace/CLAUDE/notes.md") is True

    def test_skips_eslint_rules(self):
        assert should_skip("/workspace/eslint-rules/no-eval.js") is True

    def test_skips_phpstan_rules(self):
        assert should_skip("/workspace/tests/PHPStan/rules/test.php") is True

    def test_allows_source_file(self):
        assert should_skip("/workspace/src/config.ts") is False

    def test_allows_root_file(self):
        assert should_skip("/workspace/app.php") is False

    def test_a_directory_merely_ending_in_vendor_is_not_skipped(self):
        """``myvendor/`` merely ends in ``vendor/`` -- not a skip match."""
        assert should_skip("/workspace/myvendor/lib/x.py") is False

    def test_a_directory_merely_ending_in_docs_is_not_skipped(self):
        """``autodocs/`` merely ends in ``docs/`` -- not a skip match."""
        assert should_skip("/workspace/autodocs/x.py") is False

    def test_worktree_named_with_a_vendor_suffix_is_not_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """00422 N20's reproduction, for security_antipattern's own list."""
        from pathlib import Path

        from claude_code_hooks_daemon.core import project_context as pc

        root = "/workspace/untracked/worktrees/worktree-issue-53-vendor"
        monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
        monkeypatch.setattr(
            pc.ProjectContext, "project_root", classmethod(lambda cls: Path(root)), raising=False
        )

        assert should_skip(f"{root}/src/app.py") is False

    def test_vendor_directly_under_the_project_root_is_still_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pathlib import Path

        from claude_code_hooks_daemon.core import project_context as pc

        monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
        monkeypatch.setattr(
            pc.ProjectContext,
            "project_root",
            classmethod(lambda cls: Path("/workspace")),
            raising=False,
        )

        assert should_skip("/workspace/vendor/lib/auth.php") is True

    def test_a_project_living_under_a_directory_named_vendor_is_still_guarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from pathlib import Path

        from claude_code_hooks_daemon.core import project_context as pc

        root = "/home/dev/vendor/proj"
        monkeypatch.setattr(pc.ProjectContext, "_initialized", True, raising=False)
        monkeypatch.setattr(
            pc.ProjectContext, "project_root", classmethod(lambda cls: Path(root)), raising=False
        )

        assert should_skip(f"{root}/src/app.py") is False


class TestEverySkipPatternEntry:
    """Every entry of SKIP_PATTERNS, not just vendor/docs -- per review
    feedback on Plan 00458: the bare substring bug applied identically to
    every entry, and a fix proven against one does not prove it against the
    others."""

    @pytest.mark.parametrize("entry", SKIP_PATTERNS)
    def test_a_path_merely_ending_in_the_entry_is_not_skipped(self, entry: str) -> None:
        # "x" prefixed directly onto the entry: the whole entry string is
        # still present as a substring, but its start is preceded by "x",
        # not "/" -- the exact boundary a bare `in` test cannot see.
        collision = f"x{entry}".rstrip("/")
        assert should_skip(f"/workspace/{collision}/thing.py") is False

    @pytest.mark.parametrize("entry", SKIP_PATTERNS)
    def test_the_entry_directly_under_the_project_root_is_still_skipped(self, entry: str) -> None:
        assert should_skip(f"/workspace/{entry}thing.py") is True


class TestConstants:
    """Test module-level constants."""

    def test_skip_patterns_is_tuple(self):
        assert isinstance(SKIP_PATTERNS, tuple)

    def test_skip_patterns_not_empty(self):
        assert len(SKIP_PATTERNS) > 0

    def test_universal_extension_is_star(self):
        assert UNIVERSAL_EXTENSION == "*"
