"""Tests for the secret-file hygiene SessionStart advisory (Plan 00272 Task 6.1).

The SessionStart advisory half of Task 6.1: for each configured protected
path that EXISTS, advise (never block) when it is (a) not gitignored,
(b) git-tracked, or (c) group/world-readable. Metadata only -- content is
never read.
"""

from __future__ import annotations

import io
import os
import stat
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.vault_payloads import inline_vault_yaml, vault_file_bytes

from claude_code_hooks_daemon.config.models import Config
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


@pytest.fixture(autouse=True)
def _no_project_config() -> Any:
    """Keep every test off the real project config and the real absence cache.

    The declared-absent check (Plan 00414) reads config through
    ``ProjectContext``, which another test may have initialised against this
    repository. Tests of that check patch ``_load_config`` themselves.
    """
    with patch.object(
        hygiene_module.SecretFileHygieneCheckerHandler, "_load_config", return_value=None
    ):
        yield


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


class TestNonGitFallback:
    """Plan 00272 code review: a non-repo directory must never silently
    read as 'nothing is ignored' -- gitignore/tracked checks are skipped
    outright, permissions are still checked, and the skip is stated."""

    def test_not_a_repo_notice_when_clean(self, handler: Any, tmp_path: Path) -> None:
        not_a_repo = tmp_path / "plain-dir"
        not_a_repo.mkdir()

        with _patched_root(not_a_repo), _patched_patterns():
            result = handler.handle({"source": "startup"})
        assert result.decision == Decision.ALLOW
        rendered = " ".join(result.context)
        assert "not a git repository" in rendered

    def test_permissions_still_checked_outside_a_repo(self, handler: Any, tmp_path: Path) -> None:
        not_a_repo = tmp_path / "plain-dir"
        not_a_repo.mkdir()
        target = not_a_repo / "fixture.dummy-fixture-glob"
        target.write_text("x")
        target.chmod(0o640)

        with _patched_root(not_a_repo), _patched_patterns():
            result = handler.handle({"source": "startup"})
        rendered = " ".join(result.context)
        assert "fixture.dummy-fixture-glob" in rendered
        assert "chmod 600" in rendered
        # per-file gitignore/tracked findings are meaningless without git and
        # must not appear (the module-level notice mentioning "gitignore" in
        # passing is fine and is asserted separately).
        assert hygiene_module._ISSUE_NOT_GITIGNORED not in rendered
        assert "untrack" not in rendered.lower()

    def test_never_reads_content_outside_a_repo(self, handler: Any, tmp_path: Path) -> None:
        not_a_repo = tmp_path / "plain-dir"
        not_a_repo.mkdir()
        target = not_a_repo / "fixture.dummy-fixture-glob"
        target.write_text("do-not-leak-this-content")
        target.chmod(0o640)

        with _patched_root(not_a_repo), _patched_patterns():
            result = handler.handle({"source": "startup"})
        rendered = " ".join(result.context)
        assert "do-not-leak-this-content" not in rendered

    def test_truncated_fallback_scan_says_so(self, handler: Any, tmp_path: Path) -> None:
        """A capped non-git walk must report the cap, never a silent clean bill."""
        not_a_repo = tmp_path / "plain-dir"
        not_a_repo.mkdir()
        (not_a_repo / "some_unrelated_file.txt").write_text("x")

        with (
            _patched_root(not_a_repo),
            _patched_patterns(),
            patch.object(hygiene_module.sfm, "DIRECTORY_SCAN_MAX_ENTRIES", 0),
        ):
            result = handler.handle({"source": "startup"})
        assert result.decision == Decision.ALLOW
        rendered = " ".join(result.context)
        assert "INCOMPLETE" in rendered


class TestEncryptedAtRest:
    """Plan 00459: an encrypted file is tracked on purpose; never tell a
    project to untrack it."""

    def _tracked(self, repo: Path, name: str, data: bytes, mode: int = 0o644) -> Path:
        target = repo / name
        target.write_bytes(data)
        target.chmod(mode)
        _git(repo, "add", name)
        _git(repo, "commit", "-m", f"add {name}")
        return target

    def _rendered(self, handler: Any, repo: Path) -> str:
        with _patched_root(repo), _patched_patterns():
            result = handler.handle({"source": "startup"})
        assert result.decision == Decision.ALLOW
        return "\n".join(result.context)

    def test_encrypted_tracked_file_alone_is_silent(self, handler: Any, repo: Path) -> None:
        """The owner's report: the warning should simply stop."""
        self._tracked(repo, "vars.dummy-fixture-glob", vault_file_bytes())
        assert self._rendered(handler, repo) == ""

    def test_encrypted_file_is_listed_as_fine_beside_a_real_finding(
        self, handler: Any, repo: Path
    ) -> None:
        self._tracked(repo, "vars.dummy-fixture-glob", vault_file_bytes())
        self._tracked(repo, "plain.dummy-fixture-glob", b"not-a-real-secret\n", 0o600)
        rendered = self._rendered(handler, repo)
        assert hygiene_module._ENCRYPTED_HEADING in rendered
        assert "vars.dummy-fixture-glob" in rendered
        # Exactly one file gets the untrack advice: the plaintext one.
        assert rendered.count("git rm --cached") == 1
        assert rendered.index("plain.dummy-fixture-glob") < rendered.index(
            hygiene_module._ENCRYPTED_HEADING
        )

    def test_decrypted_in_place_gets_the_advice_back(self, handler: Any, repo: Path) -> None:
        target = self._tracked(repo, "vars.dummy-fixture-glob", vault_file_bytes())
        assert self._rendered(handler, repo) == ""
        target.write_bytes(b"db_password: not-a-real-secret\n")
        rendered = self._rendered(handler, repo)
        assert "vars.dummy-fixture-glob" in rendered
        assert "git rm --cached" in rendered
        assert hygiene_module._ENCRYPTED_HEADING not in rendered

    def test_inline_vault_values_get_the_conditional_statement(
        self, handler: Any, repo: Path
    ) -> None:
        self._tracked(repo, "vars.dummy-fixture-glob", inline_vault_yaml(), 0o600)
        rendered = self._rendered(handler, repo)
        assert hygiene_module._ISSUE_INLINE_VAULT in rendered
        assert "git rm --cached" not in rendered
        assert hygiene_module._ISSUE_NOT_GITIGNORED not in rendered

    def test_inline_vault_file_gitignored_and_untracked_is_silent(
        self, handler: Any, repo: Path
    ) -> None:
        target = repo / "vars.dummy-fixture-glob"
        target.write_bytes(inline_vault_yaml())
        target.chmod(0o600)
        (repo / ".gitignore").write_text("*.dummy-fixture-glob\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-m", "ignore")
        assert self._rendered(handler, repo) == ""

    def test_encrypted_file_outside_a_repo_gets_no_permissions_finding(
        self, handler: Any, tmp_path: Path
    ) -> None:
        not_a_repo = tmp_path / "plain-dir"
        not_a_repo.mkdir()
        target = not_a_repo / "vars.dummy-fixture-glob"
        target.write_bytes(vault_file_bytes())
        target.chmod(0o644)
        with _patched_root(not_a_repo), _patched_patterns():
            result = handler.handle({"source": "startup"})
        rendered = "\n".join(result.context)
        assert "chmod 600" not in rendered
        assert "not a git repository" in rendered

    def test_armour_never_reaches_the_advisory(self, handler: Any, repo: Path) -> None:
        self._tracked(repo, "vars.dummy-fixture-glob", vault_file_bytes())
        self._tracked(repo, "plain.dummy-fixture-glob", b"do-not-leak-this-content\n")
        rendered = self._rendered(handler, repo)
        assert "ANSIBLE_VAULT" not in rendered
        assert "do-not-leak-this-content" not in rendered

    def test_guidance_explains_encrypted_files(self, handler: Any) -> None:
        text = handler.get_claude_md()
        assert "encrypted at rest" in text.lower()


class TestEncryptedFileRecovery:
    """Plan 00459 (b): a project that FOLLOWED the old untrack advice is told
    how to put its ciphertext back under version control."""

    _NAME = "vars.dummy-fixture-glob"

    def _rendered(self, handler: Any, repo: Path) -> str:
        with _patched_root(repo), _patched_patterns():
            result = handler.handle({"source": "startup"})
        assert result.decision == Decision.ALLOW
        return "\n".join(result.context)

    def _ignore(self, repo: Path) -> None:
        (repo / ".gitignore").write_text("*.dummy-fixture-glob\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-m", "ignore")

    def test_ignored_and_untracked_ciphertext_is_told_to_come_back(
        self, handler: Any, repo: Path
    ) -> None:
        """Exactly the state the old advice left behind."""
        self._ignore(repo)
        (repo / self._NAME).write_bytes(vault_file_bytes())
        rendered = self._rendered(handler, repo)
        assert hygiene_module._ENCRYPTED_SHOULD_BE_TRACKED in rendered
        assert f"!/{self._NAME}" in rendered
        assert f"git add {self._NAME}" in rendered
        assert "git rm --cached" not in rendered

    def test_untracked_but_not_ignored_ciphertext_is_told_to_add_it(
        self, handler: Any, repo: Path
    ) -> None:
        (repo / self._NAME).write_bytes(vault_file_bytes())
        rendered = self._rendered(handler, repo)
        assert hygiene_module._ENCRYPTED_SHOULD_BE_TRACKED in rendered
        assert f"git add {self._NAME}" in rendered
        assert f"!/{self._NAME}" not in rendered

    def test_tracked_ciphertext_matched_by_an_ignore_rule_needs_a_negation(
        self, handler: Any, repo: Path
    ) -> None:
        target = repo / self._NAME
        target.write_bytes(vault_file_bytes())
        _git(repo, "add", self._NAME)
        _git(repo, "commit", "-m", "vault")
        self._ignore(repo)
        rendered = self._rendered(handler, repo)
        assert f"!/{self._NAME}" in rendered
        assert f"git add {self._NAME}" not in rendered

    def test_a_negation_in_place_makes_it_silent(self, handler: Any, repo: Path) -> None:
        target = repo / self._NAME
        target.write_bytes(vault_file_bytes())
        _git(repo, "add", self._NAME)
        _git(repo, "commit", "-m", "vault")
        (repo / ".gitignore").write_text(f"*.dummy-fixture-glob\n!/{self._NAME}\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-m", "negate")
        assert self._rendered(handler, repo) == ""

    def test_nested_path_is_anchored_from_the_root(self, handler: Any, repo: Path) -> None:
        self._ignore(repo)
        nested = repo / "group" / "all" / self._NAME
        nested.parent.mkdir(parents=True)
        nested.write_bytes(vault_file_bytes())
        rendered = self._rendered(handler, repo)
        assert f"!/group/all/{self._NAME}" in rendered
        assert f"git add group/all/{self._NAME}" in rendered


class TestGitNativeEnumeration:
    """The enumeration route itself: git-native, not a blind ``os.walk``."""

    def test_finds_a_protected_file_nested_deep_in_a_large_sibling_tree(
        self, handler: Any, repo: Path
    ) -> None:
        """A blind capped walk can exhaust its cap in an unrelated subtree
        before ever reaching the protected file -- the git-native route must
        not have that failure mode."""
        noise_dir = repo / "unrelated_bulk"
        noise_dir.mkdir()
        for index in range(50):
            (noise_dir / f"file_{index}.txt").write_text("noise\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-m", "bulk noise")

        target = repo / "fixture.dummy-fixture-glob"
        target.write_text("x")
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)

        with (
            _patched_root(repo),
            _patched_patterns(),
            patch.object(hygiene_module.sfm, "DIRECTORY_SCAN_MAX_ENTRIES", 10),
        ):
            result = handler.handle({"source": "startup"})
        # The git-native route ignores the walk-only bound entirely.
        rendered = " ".join(result.context)
        assert "fixture.dummy-fixture-glob" in rendered
        assert "gitignore" in rendered.lower()


# ── Plan 00414: a protected path the config names, but which is absent ─────

_WORD_LIST = ".claude/word-list.dummy-fixture-glob"
_GUARDED = "keys/deploy.dummy-fixture-glob"


def _config(
    *,
    word_list: str | None = None,
    word_list_enabled: bool = True,
    protected_paths: list[str] | None = None,
    guard_enabled: bool = True,
) -> Config:
    pre_tool_use: dict[str, Any] = {}
    if word_list is not None:
        pre_tool_use["sensitive_content"] = {
            "enabled": word_list_enabled,
            "options": {"secret_word_list_path": word_list},
        }
    if protected_paths is not None:
        pre_tool_use["secret_file_guard"] = {
            "enabled": guard_enabled,
            "options": {"protected_paths": protected_paths},
        }
    return Config.model_validate({"handlers": {"pre_tool_use": pre_tool_use}})


class TestAbsentDeclaredPath:
    """A declared-but-absent protected path is told once; health stays silent."""

    @pytest.fixture()
    def cache_file(self, tmp_path: Path) -> Path:
        return tmp_path / "daemon-untracked" / "absence-cache.json"

    def _run(self, handler: Any, root: Path, config: Config | None, cache_file: Path) -> list[str]:
        cls = hygiene_module.SecretFileHygieneCheckerHandler
        with (
            _patched_root(root),
            _patched_patterns(),
            patch.object(cls, "_load_config", return_value=config),
            patch.object(cls, "_absence_cache_file", return_value=cache_file),
        ):
            result = handler.handle({"source": "startup"})
        assert result.decision == Decision.ALLOW
        return list(result.context)

    def _healthy(self, repo: Path, relpath: str) -> None:
        target = repo / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")
        target.chmod(0o600)
        (repo / ".gitignore").write_text("*.dummy-fixture-glob\n")
        _git(repo, "add", ".gitignore")
        _git(repo, "commit", "-m", "ignore")

    def test_declared_word_list_absent_is_reported_naming_the_inert_guard(
        self, handler: Any, repo: Path, cache_file: Path
    ) -> None:
        rendered = " ".join(self._run(handler, repo, _config(word_list=_WORD_LIST), cache_file))

        assert _WORD_LIST in rendered
        assert "ABSENT" in rendered
        assert "sensitive_content" in rendered
        assert "inert" in rendered.lower()

    def test_declared_word_list_present_and_healthy_is_silent(
        self, handler: Any, repo: Path, cache_file: Path
    ) -> None:
        self._healthy(repo, _WORD_LIST)

        assert self._run(handler, repo, _config(word_list=_WORD_LIST), cache_file) == []

    def test_undeclared_default_word_list_absent_is_silent(
        self, handler: Any, repo: Path, cache_file: Path
    ) -> None:
        """No declaration, no gap: a project that never configured a list is not told."""
        assert self._run(handler, repo, _config(), cache_file) == []

    def test_disabled_guard_is_not_reported_as_inert(
        self, handler: Any, repo: Path, cache_file: Path
    ) -> None:
        config = _config(word_list=_WORD_LIST, word_list_enabled=False)

        assert self._run(handler, repo, config, cache_file) == []

    def test_no_loadable_config_is_silent(self, handler: Any, repo: Path, cache_file: Path) -> None:
        assert self._run(handler, repo, None, cache_file) == []

    def test_literal_guarded_path_absent_is_reported(
        self, handler: Any, repo: Path, cache_file: Path
    ) -> None:
        config = _config(protected_paths=[_GUARDED])

        rendered = " ".join(self._run(handler, repo, config, cache_file))

        assert _GUARDED in rendered
        assert "secret_file_guard" in rendered

    def test_glob_and_bare_name_entries_are_patterns_not_declared_paths(
        self, handler: Any, repo: Path, cache_file: Path
    ) -> None:
        """A glob or a bare basename matches anywhere; it names no one path."""
        config = _config(protected_paths=["keys/*.dummy-fixture-glob", "deploy.dummy-fixture-glob"])

        assert self._run(handler, repo, config, cache_file) == []

    def test_disabled_secret_file_guard_is_not_reported(
        self, handler: Any, repo: Path, cache_file: Path
    ) -> None:
        config = _config(protected_paths=[_GUARDED], guard_enabled=False)

        assert self._run(handler, repo, config, cache_file) == []

    def test_dangling_symlink_counts_as_absent(
        self, handler: Any, repo: Path, cache_file: Path
    ) -> None:
        """A worktree seeds the list as a symlink; a dead one leaves the guard inert."""
        link = repo / _WORD_LIST
        link.parent.mkdir(parents=True)
        link.symlink_to(repo / "gone.dummy-fixture-glob")

        rendered = " ".join(self._run(handler, repo, _config(word_list=_WORD_LIST), cache_file))

        assert _WORD_LIST in rendered

    def test_reported_once_not_every_session(
        self, handler: Any, repo: Path, cache_file: Path
    ) -> None:
        config = _config(word_list=_WORD_LIST)

        assert self._run(handler, repo, config, cache_file) != []
        assert self._run(handler, repo, config, cache_file) == []
        assert self._run(handler, repo, config, cache_file) == []

    def test_a_config_change_reports_again(
        self, handler: Any, repo: Path, cache_file: Path
    ) -> None:
        assert self._run(handler, repo, _config(word_list=_WORD_LIST), cache_file) != []

        moved = ".claude/other-list.dummy-fixture-glob"
        rendered = " ".join(self._run(handler, repo, _config(word_list=moved), cache_file))

        assert moved in rendered

    def test_a_presence_change_reports_again(
        self, handler: Any, repo: Path, cache_file: Path
    ) -> None:
        """Created (silent), then lost again (told again)."""
        config = _config(word_list=_WORD_LIST)
        assert self._run(handler, repo, config, cache_file) != []

        self._healthy(repo, _WORD_LIST)
        assert self._run(handler, repo, config, cache_file) == []

        (repo / _WORD_LIST).unlink()
        assert _WORD_LIST in " ".join(self._run(handler, repo, config, cache_file))

    def test_unwritable_cache_still_reports_and_never_raises(
        self, handler: Any, repo: Path, tmp_path: Path
    ) -> None:
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x")
        cache_file = blocker / "absence-cache.json"

        rendered = " ".join(self._run(handler, repo, _config(word_list=_WORD_LIST), cache_file))

        assert _WORD_LIST in rendered

    def test_existing_findings_and_absence_are_both_reported(
        self, handler: Any, repo: Path, cache_file: Path
    ) -> None:
        loose = repo / "fixture.dummy-fixture-glob"
        loose.write_text("x")
        loose.chmod(0o600)

        rendered = " ".join(self._run(handler, repo, _config(word_list=_WORD_LIST), cache_file))

        assert "fixture.dummy-fixture-glob" in rendered
        assert hygiene_module._ISSUE_NOT_GITIGNORED in rendered
        assert _WORD_LIST in rendered

    def test_absence_is_reported_outside_a_git_repository(
        self, handler: Any, tmp_path: Path, cache_file: Path
    ) -> None:
        not_a_repo = tmp_path / "plain-dir"
        not_a_repo.mkdir()

        rendered = " ".join(
            self._run(handler, not_a_repo, _config(word_list=_WORD_LIST), cache_file)
        )

        assert "not a git repository" in rendered
        assert _WORD_LIST in rendered

    def test_no_code_path_opens_a_protected_file(
        self, handler: Any, repo: Path, cache_file: Path
    ) -> None:
        """Metadata only: the absence check stats paths and opens none of them.

        One declared path is present (healthy), one absent, so both branches
        run. ``classify_at_rest`` is the pre-existing, sanctioned in-daemon
        format check (Plan 00459) and is stubbed so that any remaining open
        of a protected path could only come from new code.
        """
        self._healthy(repo, _GUARDED)
        config = _config(word_list=_WORD_LIST, protected_paths=[_GUARDED])
        opened: list[str] = []
        real_open = io.open
        real_os_open = os.open

        def recording_open(file: Any, *args: Any, **kwargs: Any) -> Any:
            opened.append(str(file))
            return real_open(file, *args, **kwargs)

        def recording_os_open(path: Any, *args: Any, **kwargs: Any) -> Any:
            opened.append(str(path))
            return real_os_open(path, *args, **kwargs)

        with (
            patch.object(hygiene_module, "classify_at_rest", return_value=None),
            patch("builtins.open", recording_open),
            patch("io.open", recording_open),
            patch("os.open", recording_os_open),
        ):
            rendered = " ".join(self._run(handler, repo, config, cache_file))

        assert _WORD_LIST in rendered
        touched = {Path(p).resolve() for p in opened}
        assert (repo / _GUARDED).resolve() not in touched
        assert (repo / _WORD_LIST).resolve() not in touched
