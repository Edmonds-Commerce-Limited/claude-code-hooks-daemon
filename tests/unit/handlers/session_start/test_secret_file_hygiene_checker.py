"""Tests for the secret-file hygiene SessionStart advisory (Plan 00272 Task 6.1).

The SessionStart advisory half of Task 6.1: for each configured protected
path that EXISTS, advise (never block) when it is (a) not gitignored,
(b) git-tracked, or (c) group/world-readable. Metadata only -- content is
never read.
"""

from __future__ import annotations

import stat
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants import HandlerID, Priority
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.session_start import (
    secret_file_hygiene_checker as hygiene_module,
)

_PATTERNS = ("*.dummy-fixture-glob",)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 - trusted git binary, fixed argv, test fixture only
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


def _patched_root(root: Path) -> Any:
    return patch.object(hygiene_module.ProjectContext, "project_root", return_value=root)


def _patched_patterns(patterns: tuple[str, ...] = _PATTERNS) -> Any:
    return patch.object(hygiene_module.sfm, "resolve_configured_patterns", return_value=patterns)


@pytest.fixture()
def handler() -> Any:
    return hygiene_module.SecretFileHygieneCheckerHandler()


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("# repo\n")
    _git(root, "init")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "initial")
    return root


class TestInitialisation:
    def test_handler_id_and_priority(self, handler: Any) -> None:
        assert handler.handler_id == HandlerID.SECRET_FILE_HYGIENE_CHECKER
        assert handler.priority == Priority.SECRET_FILE_HYGIENE_CHECKER
        assert handler.terminal is False


class TestMatches:
    def test_matches_new_session(self, handler: Any, tmp_path: Path) -> None:
        transcript = tmp_path / "transcript.json"
        transcript.write_text("{}")
        assert handler.matches({"transcript_path": str(transcript)}) is True

    def test_does_not_match_resume_session(self, handler: Any, tmp_path: Path) -> None:
        transcript = tmp_path / "transcript.json"
        transcript.write_text("x" * 200)
        assert handler.matches({"transcript_path": str(transcript)}) is False


class TestHandle:
    def test_no_protected_files_present_is_silent(self, handler: Any, repo: Path) -> None:
        with _patched_root(repo), _patched_patterns():
            result = handler.handle({"source": "startup"})
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_gitignored_tracked_and_safe_permissions_is_silent(
        self, handler: Any, repo: Path
    ) -> None:
        target = repo / "fixture.dummy-fixture-glob"
        target.write_text("x")
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
        (repo / ".gitignore").write_text("*.dummy-fixture-glob\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-m", "ignore")

        with _patched_root(repo), _patched_patterns():
            result = handler.handle({"source": "startup"})
        assert result.decision == Decision.ALLOW
        assert not result.context

    def test_not_gitignored_is_flagged(self, handler: Any, repo: Path) -> None:
        target = repo / "fixture.dummy-fixture-glob"
        target.write_text("x")
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)

        with _patched_root(repo), _patched_patterns():
            result = handler.handle({"source": "startup"})
        assert result.decision == Decision.ALLOW
        rendered = " ".join(result.context)
        assert "fixture.dummy-fixture-glob" in rendered
        assert "gitignore" in rendered.lower()

    def test_tracked_file_is_flagged(self, handler: Any, repo: Path) -> None:
        target = repo / "fixture.dummy-fixture-glob"
        target.write_text("x")
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)
        (repo / ".gitignore").write_text("*.dummy-fixture-glob\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "add", "-f", "fixture.dummy-fixture-glob")
        _git(repo, "commit", "-m", "oops tracked")

        with _patched_root(repo), _patched_patterns():
            result = handler.handle({"source": "startup"})
        assert result.decision == Decision.ALLOW
        rendered = " ".join(result.context)
        assert "fixture.dummy-fixture-glob" in rendered
        assert "untrack" in rendered.lower()

    def test_group_readable_permissions_is_flagged(self, handler: Any, repo: Path) -> None:
        target = repo / "fixture.dummy-fixture-glob"
        target.write_text("x")
        target.chmod(0o640)
        (repo / ".gitignore").write_text("*.dummy-fixture-glob\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-m", "ignore")

        with _patched_root(repo), _patched_patterns():
            result = handler.handle({"source": "startup"})
        assert result.decision == Decision.ALLOW
        rendered = " ".join(result.context)
        assert "fixture.dummy-fixture-glob" in rendered
        assert "chmod 600" in rendered

    def test_never_reads_file_content(self, handler: Any, repo: Path) -> None:
        """The advisory reports metadata only -- content never enters the result."""
        target = repo / "fixture.dummy-fixture-glob"
        target.write_text("do-not-leak-this-content")
        target.chmod(0o640)

        with _patched_root(repo), _patched_patterns():
            result = handler.handle({"source": "startup"})
        rendered = " ".join(result.context)
        assert "do-not-leak-this-content" not in rendered

    def test_decision_never_denies(self, handler: Any, repo: Path) -> None:
        target = repo / "fixture.dummy-fixture-glob"
        target.write_text("x")
        target.chmod(0o666)

        with _patched_root(repo), _patched_patterns():
            result = handler.handle({"source": "startup"})
        assert result.decision == Decision.ALLOW


class TestResidentGuidance:
    def test_get_claude_md_returns_content(self, handler: Any) -> None:
        assert handler.get_claude_md() is not None


class TestAcceptanceTests:
    def test_returns_at_least_one_test(self, handler: Any) -> None:
        tests = handler.get_acceptance_tests()
        assert len(tests) >= 1
