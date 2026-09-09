"""Tests for SensitiveContentHandler (Plan 00201).

Two independent sources: (a) configurable PUBLIC patterns, safe to name in
the deny reason; (b) a gitignored SECRET word list, whose matched term must
NEVER appear in the deny reason — only a 1-based index into the (gitignored,
hence meaningless-without-it) file.
"""

import re
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_code_hooks_daemon.constants.rule_ids import RuleID
from claude_code_hooks_daemon.constants.timeout import Timeout
from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.rule import Rule
from claude_code_hooks_daemon.handlers.pre_tool_use import (
    sensitive_content as sensitive_content_module,
)
from claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content import (
    SensitiveContentHandler,
)
from claude_code_hooks_daemon.utils import secret_redaction as sr


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> None:
    """Reset the shared DaemonDataLayer singleton around every test in this module."""
    reset_data_layer()
    yield
    reset_data_layer()


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


class TestFilePathIsCheckedNotJustContent:
    """An identifier in the FILE NAME leaks exactly as loudly as one in the body.

    The history rewrite of this repository needed ``--path-rename`` for three
    files whose NAMES carried an identifier - ``--replace-text`` never touches
    a filename. The write-time guard had the same blind spot: a file could be
    created with an identifier in its name and the content check would wave it
    through.

    The path is checked RELATIVE to the project root. Checking the absolute
    path would be catastrophic: a project living under a listed directory
    would have every single write denied.
    """

    def test_public_pattern_in_filename_matches(self) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "vhosts-path", "pattern": "secretpath", "description": "d"}]
        )
        hook_input = _write_input("/workspace/untracked/report-secretpath-v1.md", "clean body\n")
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content.resolve_project_root",
            return_value="/workspace",
        ):
            assert handler.matches(hook_input) is True

    def test_public_pattern_in_directory_name_matches(self) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "vhosts-path", "pattern": "secretpath", "description": "d"}]
        )
        hook_input = _write_input("/workspace/untracked/secretpath/notes.md", "clean body\n")
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content.resolve_project_root",
            return_value="/workspace",
        ):
            assert handler.matches(hook_input) is True

    def test_match_in_project_root_itself_is_ignored(self) -> None:
        """The killer false positive: root contains the term, so EVERY write would deny."""
        handler = _handler_with_public_patterns(
            [{"name": "home-path", "pattern": "secretpath", "description": "d"}]
        )
        hook_input = _write_input("/home/secretpath/project/src/app.py", "clean body\n")
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content.resolve_project_root",
            return_value="/home/secretpath/project",
        ):
            assert handler.matches(hook_input) is False

    def test_secret_term_in_filename_matches(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("zulu-host\n")
        handler = _handler_with_secret_file(secret_file)
        hook_input = _write_input("/workspace/untracked/zulu-host-report.md", "clean body\n")
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content.resolve_project_root",
            return_value="/workspace",
        ):
            assert handler.matches(hook_input) is True

    def test_secret_term_in_filename_deny_reason_never_names_it(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("zulu-host\n")
        handler = _handler_with_secret_file(secret_file)
        hook_input = _write_input("/workspace/untracked/zulu-host-report.md", "clean body\n")
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content.resolve_project_root",
            return_value="/workspace",
        ):
            result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "zulu-host" not in (result.reason or "")

    def test_clean_path_and_clean_content_does_not_match(self) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "x", "pattern": "secretpath", "description": "d"}]
        )
        hook_input = _write_input("/workspace/untracked/clean-name.md", "clean body\n")
        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content.resolve_project_root",
            return_value="/workspace",
        ):
            assert handler.matches(hook_input) is False


class TestInit:
    def test_identity(self) -> None:
        handler = SensitiveContentHandler()
        assert handler.name == "block-sensitive-content"
        assert handler.terminal is True

    def test_default_public_patterns_is_empty(self) -> None:
        handler = SensitiveContentHandler()
        assert handler._public_patterns == []


class TestMatchesIgnoresNonWriteEdit:
    def test_bash_command_that_writes_no_git_metadata_never_matches(self) -> None:
        """THE load-bearing negative control for the whole Bash surface.

        A term may legitimately appear in a command that writes nothing into
        the repository — grepping for it, running the redaction tooling,
        reading a file that contains it. Denying those would make the handler
        unusable and get it switched off, which is a worse outcome than the
        leak it prevents. Only commands that write git METADATA are candidates.
        """
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


def _bash_input(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


class TestGitMetadataSurfaces:
    """Five of the seven leak surfaces are git METADATA, and all enter via Bash.

    Cleaning this repository's own history needed four distinct
    ``git-filter-repo`` mechanisms, because ``--replace-text`` rewrites blob
    contents and nothing else. Contents and paths are guarded. Commit
    messages, author/committer identity, tag names, tag messages and branch
    names are not — so one ``git commit -m "<term>"`` re-contaminates a
    force-pushed-clean repository, and both guards then report all-clear.
    """

    @pytest.mark.parametrize(
        "command",
        [
            'git commit -m "alpha-term is fixed"',
            'git commit --message="alpha-term is fixed"',
            'git tag -a v1.0.0 -m "ships alpha-term"',
            "git tag alpha-term-release",
            "git branch alpha-term-work",
            "git checkout -b alpha-term-work",
            "git switch -c alpha-term-work",
            'git config user.name "alpha-term"',
            "git config user.email alpha-term@example.com",
            'git merge --no-ff -m "merge alpha-term" feature',
        ],
    )
    def test_term_in_git_metadata_write_is_denied(self, tmp_path: Path, command: str) -> None:
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("alpha-term\n")
        handler = _handler_with_secret_file(secret_file)

        assert handler.matches(_bash_input(command)) is True
        assert handler.handle(_bash_input(command)).decision == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "git log --oneline -20",
            "git show HEAD",
            "git status --porcelain",
            "git diff HEAD~1",
            'git commit -m "an ordinary message"',
            "git tag -l",
        ],
    )
    def test_clean_git_command_is_not_denied(self, tmp_path: Path, command: str) -> None:
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("alpha-term\n")
        handler = _handler_with_secret_file(secret_file)

        assert handler.matches(_bash_input(command)) is False

    @pytest.mark.parametrize(
        "command",
        [
            "grep -rn alpha-term /workspace/untracked",
            "cat /workspace/untracked/alpha-term-notes.md",
            "./untracked/rewrite/refresh.sh  # rewrites alpha-term out of history",
            "git log --grep=alpha-term",
            "git show alpha-term-tag",
            "git branch --list 'alpha-term*'",
            "git tag -l 'alpha-term*'",
        ],
    )
    def test_term_in_a_command_that_writes_no_metadata_is_allowed(
        self, tmp_path: Path, command: str
    ) -> None:
        """The false positive that would get this handler switched off.

        Reading, searching for, and REMOVING a term all legitimately put it on
        a command line. ``git log --grep`` and ``git show`` name a ref without
        creating one. Denying these would block the very work of cleaning a
        repository — including this project's own rewrite tooling.
        """
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("alpha-term\n")
        handler = _handler_with_secret_file(secret_file)

        assert handler.matches(_bash_input(command)) is False

    def test_public_pattern_in_git_metadata_write_is_denied(self) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "vhosts-path", "pattern": "/var/www/vhosts", "description": "server path"}]
        )
        command = 'git commit -m "deploy to /var/www/vhosts/site"'

        assert handler.matches(_bash_input(command)) is True
        result = handler.handle(_bash_input(command))
        assert result.decision == Decision.DENY
        assert "vhosts-path" in (result.reason or "")

    def test_deny_reason_never_echoes_the_term(self, tmp_path: Path) -> None:
        """The command is echoed back — so the command is itself an output surface.

        Exactly the defect the file-path work had to fix: the message
        announcing the block was printing the thing it exists to suppress.
        """
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("alpha-term\n")
        handler = _handler_with_secret_file(secret_file)

        result = handler.handle(_bash_input('git commit -m "alpha-term is fixed"'))

        # The WHOLE serialised result, not just `reason` — a term smuggled into
        # any other field is just as published.
        assert "alpha-term" not in result.model_dump_json()
        assert "entry 1 of 1" in (result.reason or "")

    def test_missing_command_field_is_not_denied(self, tmp_path: Path) -> None:
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("alpha-term\n")
        handler = _handler_with_secret_file(secret_file)

        assert handler.matches({"tool_name": "Bash", "tool_input": {}}) is False

    def test_non_git_command_naming_a_metadata_subcommand_is_allowed(self, tmp_path: Path) -> None:
        """``commit``/``tag``/``branch`` are ordinary English words.

        The gate is a git invocation, not the bare presence of a subcommand
        name, or any sentence mentioning a branch would be denied.
        """
        secret_file = tmp_path / "words.secret"
        secret_file.write_text("alpha-term\n")
        handler = _handler_with_secret_file(secret_file)

        assert handler.matches(_bash_input("echo 'commit the alpha-term branch tag'")) is False


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # nosec B603 B607 - trusted git binary, fixed argv, test fixture only
        ["git", "-C", str(repo), *args],
        capture_output=True,
        check=True,
        timeout=Timeout.GIT_CONTEXT,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A minimal git repo with one commit, ready to stage files into."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("# repo\n")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "T")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")
    return root


def _wordlist(tmp_path: Path, *terms: str) -> SensitiveContentHandler:
    wordlist_file = tmp_path / "wordlist.txt"
    wordlist_file.write_text("".join(f"{term}\n" for term in terms))
    return _handler_with_secret_file(wordlist_file)


def _commit_input(repo: Path, command: str = 'git commit -m "clean message"') -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo)}


def _stage(repo: Path, relpath: str, content: str | bytes) -> None:
    """Put a file in the index by the route no write-time hook sees.

    The bytes land on disk WITHOUT a Write/Edit (the real failure was a
    ``mv`` of a report into the plan folder), then ``git add`` stages them.
    """
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)
    _git(repo, "add", relpath)


class TestStagedContentSurface:
    """Plan 00252 Phase 3 / Plan 00362 D1: staged blob CONTENT is a leak surface.

    A file that arrives by ``mv``/``cp`` and is then staged never passed a
    ``Write``/``Edit``, so the content check never saw it. The commit is the
    gate: the moment content becomes history, and the last moment it can be
    stopped without a rewrite.
    """

    def test_staged_file_carrying_a_secret_term_denies_the_commit(
        self, repo: Path, tmp_path: Path
    ) -> None:
        handler = _wordlist(tmp_path, "alpha-term")
        _stage(repo, "notes/report.md", "the host is alpha-term in prod\n")

        hook_input = _commit_input(repo)
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY

    def test_deny_reason_names_the_path_and_index_but_never_the_line(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """Only the staged PATH and the entry index -- never the added line."""
        handler = _wordlist(tmp_path, "zulu-host", "alpha-term")
        _stage(repo, "notes/report.md", "the host is alpha-term in prod\n")

        result = handler.handle(_commit_input(repo))
        serialised = result.model_dump_json()
        assert "alpha-term" not in serialised
        assert "the host is" not in serialised
        assert "in prod" not in serialised
        assert "entry 2 of 2" in (result.reason or "")
        assert "notes/report.md" in (result.reason or "")

    def test_staged_public_pattern_is_denied_naming_the_match(self, repo: Path) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "vhosts-path", "pattern": "/var/www/vhosts", "description": "d"}]
        )
        _stage(repo, "deploy.txt", "target /var/www/vhosts/site\n")

        result = handler.handle(_commit_input(repo))
        assert result.decision == Decision.DENY
        assert "vhosts-path" in (result.reason or "")
        assert "deploy.txt" in (result.reason or "")

    def test_clean_staged_content_is_allowed(self, repo: Path, tmp_path: Path) -> None:
        handler = _wordlist(tmp_path, "alpha-term")
        _stage(repo, "notes/clean.md", "nothing to see\n")

        assert handler.matches(_commit_input(repo)) is False

    def test_only_added_lines_are_inspected(self, repo: Path, tmp_path: Path) -> None:
        """REMOVING a term must never be blocked -- the commit that cleans a file."""
        handler = _wordlist(tmp_path, "alpha-term")
        (repo / "dirty.md").write_text("alpha-term was here\n")
        _git(repo, "add", "dirty.md")
        _git(repo, "commit", "-q", "-m", "dirty")
        (repo / "dirty.md").write_text("cleaned\n")
        _git(repo, "add", "dirty.md")

        assert handler.matches(_commit_input(repo)) is False

    def test_unstaged_working_tree_content_is_not_inspected(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """Only what the commit would RECORD is judged, not the whole checkout."""
        handler = _wordlist(tmp_path, "alpha-term")
        (repo / "unstaged.md").write_text("alpha-term\n")

        assert handler.matches(_commit_input(repo)) is False

    def test_commit_all_flag_inspects_tracked_modifications(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """``git commit -a`` stages tracked changes AT commit time, so the
        index is not yet the truth -- the working tree is."""
        handler = _wordlist(tmp_path, "alpha-term")
        (repo / "README.md").write_text("# repo\nalpha-term\n")

        assert handler.matches(_commit_input(repo, 'git commit -a -m "x"')) is True
        assert handler.matches(_commit_input(repo, 'git commit -am "x"')) is True
        assert handler.matches(_commit_input(repo, 'git commit --all -m "x"')) is True

    def test_a_short_flag_quoted_in_the_message_does_not_diff_the_working_tree(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """A message is a VALUE, not the flags it happens to quote.

        Reading ``-a`` out of the message diffs against HEAD -- the whole
        dirty working tree -- so an UNSTAGED file denies a commit that never
        included it, naming a path the author cannot find in the index.
        """
        handler = _wordlist(tmp_path, "alpha-term")
        (repo / "README.md").write_text("# repo\nalpha-term\n")

        command = "git commit -m 'fix the -a flag handling'"
        assert handler.matches(_commit_input(repo, command)) is False

    def test_binary_blob_is_skipped(self, repo: Path, tmp_path: Path) -> None:
        handler = _wordlist(tmp_path, "alpha-term")
        _stage(repo, "blob.bin", b"\x00\x01alpha-term\x00\xff")

        assert handler.matches(_commit_input(repo)) is False

    def test_oversized_file_is_skipped_by_stated_bound(self, repo: Path, tmp_path: Path) -> None:
        """A file whose added lines exceed the per-file bound is stood down
        (logged), never scanned partially and never a timeout in the field."""
        handler = _wordlist(tmp_path, "alpha-term")
        filler = "x" * 100 + "\n"
        big = filler * (sensitive_content_module.MAX_STAGED_FILE_BYTES // len(filler) + 2)
        _stage(repo, "big.txt", big + "alpha-term\n")

        assert handler.matches(_commit_input(repo)) is False

    def test_a_non_ascii_staged_path_is_named_by_its_real_name(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """``core.quotePath`` defaults to true, so git C-quotes such a path."""
        handler = _wordlist(tmp_path, "alpha-term")
        _stage(repo, "notes/café.md", "alpha-term\n")

        result = handler.handle(_commit_input(repo))

        assert result.decision == Decision.DENY
        assert "notes/café.md" in (result.reason or "")
        assert "\\303" not in (result.reason or "")

    def test_an_excluded_non_ascii_path_is_still_excluded(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """The consequence of leaving the path encoded, and the reason it matters.

        The map key becomes ``repo_root / relpath``, so a key that kept its
        quotes and its ``b/`` prefix matches no exclude glob and no secret-list
        path: a project that exempted a fixture tree has that exemption
        silently bypassed for exactly the files whose NAMES carry a non-ASCII
        byte -- a property nobody would connect to an allowlist.
        """
        handler = _wordlist(tmp_path, "alpha-term")
        handler._exclude_paths = ["tests/fixtures/café.md"]
        _stage(repo, "tests/fixtures/café.md", "alpha-term\n")

        with patch(
            "claude_code_hooks_daemon.utils.path_exclusion.resolve_project_root",
            return_value=str(repo),
        ):
            assert handler.matches(_commit_input(repo)) is False

    def test_excluded_path_is_not_inspected(self, repo: Path, tmp_path: Path) -> None:
        handler = _wordlist(tmp_path, "alpha-term")
        handler._exclude_paths = ["tests/fixtures/**"]
        _stage(repo, "tests/fixtures/sample.txt", "alpha-term\n")

        with patch(
            "claude_code_hooks_daemon.utils.path_exclusion.resolve_project_root",
            return_value=str(repo),
        ):
            assert handler.matches(_commit_input(repo)) is False

    def test_commit_outside_any_repo_is_allowed(self, tmp_path: Path) -> None:
        handler = _wordlist(tmp_path, "alpha-term")
        plain = tmp_path / "plain"
        plain.mkdir()

        assert handler.matches(_commit_input(plain)) is False

    def test_git_push_is_not_a_content_surface(self, repo: Path, tmp_path: Path) -> None:
        """The commit is the gate. A push carries nothing the commit did not."""
        handler = _wordlist(tmp_path, "alpha-term")
        _stage(repo, "notes/report.md", "alpha-term\n")

        assert handler.matches(_commit_input(repo, "git push origin main")) is False

    def test_matches_and_handle_agree_on_one_diff_read(self, repo: Path, tmp_path: Path) -> None:
        """``matches()`` and ``handle()`` see the same hook_input; the diff is
        read ONCE per dispatch, so the two can never disagree."""
        handler = _wordlist(tmp_path, "alpha-term")
        _stage(repo, "notes/report.md", "alpha-term\n")
        hook_input = _commit_input(repo)

        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content.run_git",
            wraps=sensitive_content_module.run_git,
        ) as spy:
            assert handler.matches(hook_input) is True
            assert handler.handle(hook_input).decision == Decision.DENY
        diff_calls = [c for c in spy.call_args_list if "diff" in c.args]
        assert len(diff_calls) == 1


class TestQuotedDiffPathParsing:
    """git C-quotes a diff header path, and the quotes swallow the ``b/`` prefix.

    ``core.quotePath`` defaults to true, so any path with a non-ASCII byte, a
    quote, a backslash or a tab arrives as ``"b/caf\\303\\251.md"``.
    ``removeprefix("b/")`` cannot strip a prefix that sits INSIDE the opening
    quote, so the map key kept both -- and every path-based check downstream
    (exclusions, the secret-list self-exemption) stopped matching.
    """

    def test_a_non_ascii_path_is_decoded_back_to_the_real_name(self) -> None:
        diff = (
            'diff --git "a/caf\\303\\251.md" "b/caf\\303\\251.md"\n'
            "new file mode 100644\n"
            "--- /dev/null\n"
            '+++ "b/caf\\303\\251.md"\n'
            "@@ -0,0 +1 @@\n"
            "+alpha-term\n"
        )

        assert sensitive_content_module._added_lines_by_path(diff) == {"café.md": "alpha-term\n"}

    @pytest.mark.parametrize(
        ("quoted", "expected"),
        [
            ('"b/plain.md"', "plain.md"),
            ('"b/two\\twords.md"', "two\twords.md"),
            ('"b/say \\"hi\\".md"', 'say "hi".md'),
            ('"b/back\\\\slash.md"', "back\\slash.md"),
            ("b/unquoted.md", "unquoted.md"),
        ],
    )
    def test_each_escape_git_emits_is_decoded(self, quoted: str, expected: str) -> None:
        diff = f"diff --git x y\n+++ {quoted}\n@@ -0,0 +1 @@\n+line\n"

        assert list(sensitive_content_module._added_lines_by_path(diff)) == [expected]

    def test_an_unquoted_path_is_left_alone(self) -> None:
        """A backslash in an UNQUOTED header is a literal, not an escape."""
        diff = "diff --git x y\n+++ b/a\\tb.md\n@@ -0,0 +1 @@\n+line\n"

        assert list(sensitive_content_module._added_lines_by_path(diff)) == ["a\\tb.md"]


class TestCommitAllFlagParsing:
    """``_is_git_commit`` decides WHAT a commit would record, so it must read
    the command the way the shell does.

    ``-a``/``--all`` switches the staged-content scan from ``--cached`` (the
    index) to ``HEAD`` (the whole dirty working tree). A bare ``str.split()``
    cannot see quoting, so every whitespace-delimited word of a quoted message
    was read as an option: any word starting with one dash and containing an
    ``a`` turned the scan onto files the commit was never going to record.
    """

    @pytest.mark.parametrize(
        ("command", "expected_all"),
        [
            ("git commit -m 'fix the -a flag handling'", False),
            ('git commit -m "document -a and -am shorthands"', False),
            ("git commit -m 'plain message'", False),
            # A sticky short-option value: `-mall-fixed` is a MESSAGE, and the
            # letters after the `m` belong to it, not to another flag.
            ("git commit -m'add auth to the api'", False),
            ("git commit --message='refactor -a handling'", False),
            ("git commit -am 'genuine all'", True),
            ("git commit -a -m 'genuine all'", True),
            ("git commit --all -m 'genuine all'", True),
            # The flag can also FOLLOW the message, so the walk cannot simply
            # stop at the first `-m` and call the rest a value.
            ("git commit -m 'genuine all' -a", True),
            ("git -C /srv/project commit -am 'global option first'", True),
        ],
    )
    def test_commits_all_is_read_from_options_only(
        self, command: str, expected_all: bool
    ) -> None:
        is_commit, commits_all = sensitive_content_module._is_git_commit(command)
        assert is_commit is True
        assert commits_all is expected_all

    def test_unbalanced_quote_falls_back_to_whitespace_splitting(self) -> None:
        """A command the shell itself would reject still has to be judged.

        ``shlex`` raises on an unterminated quote; standing down entirely
        would drop the staged-content surface for it, so the naive split is
        the fallback -- over-reading a flag is the safe direction.
        """
        is_commit, _ = sensitive_content_module._is_git_commit("git commit -m 'unterminated")
        assert is_commit is True

    def test_a_non_commit_subcommand_is_not_a_commit(self) -> None:
        assert sensitive_content_module._is_git_commit("git tag -a v1 -m 'note'") == (False, False)

    def test_pathspecs_after_the_end_of_options_marker_are_not_flags(self) -> None:
        """After ``--`` git reads operands, so a file called ``-a`` is a file."""
        is_commit, commits_all = sensitive_content_module._is_git_commit(
            "git commit -m 'msg' -- -a"
        )
        assert (is_commit, commits_all) == (True, False)


class TestGhBodySurface:
    """Plan 00264 Question 7 / Plan 00362 D7: a ``gh`` body is more public than a commit.

    ``gh issue comment``/``gh pr comment``/``create``/``edit`` publish a body
    to GitHub, where no history rewrite can retract it. Inline bodies
    (``--body``/``-b``) are on the command line; ``--body-file``/``-F``
    bodies are read from the named file.
    """

    @pytest.mark.parametrize(
        "command",
        [
            'gh issue comment 12 --body "see alpha-term"',
            'gh issue comment 12 -b "see alpha-term"',
            'gh pr comment 12 --body="see alpha-term"',
            'gh issue create --title t --body "alpha-term"',
            'gh pr create --title t --body "alpha-term"',
            'gh issue edit 12 --body "alpha-term"',
            'gh pr edit 12 --body "alpha-term"',
        ],
    )
    def test_term_in_inline_gh_body_is_denied(self, tmp_path: Path, command: str) -> None:
        handler = _wordlist(tmp_path, "alpha-term")

        assert handler.matches(_bash_input(command)) is True
        result = handler.handle(_bash_input(command))
        assert result.decision == Decision.DENY
        assert "alpha-term" not in result.model_dump_json()
        assert "entry 1 of 1" in (result.reason or "")

    @pytest.mark.parametrize("flag", ["--body-file", "-F"])
    def test_term_in_gh_body_file_is_denied_naming_only_the_file(
        self, tmp_path: Path, flag: str
    ) -> None:
        handler = _wordlist(tmp_path, "alpha-term")
        body = tmp_path / "body.md"
        body.write_text("summary\n\nthe host alpha-term is down\n")

        hook_input = _bash_input(f"gh issue comment 12 {flag} {body}")
        assert handler.matches(hook_input) is True
        result = handler.handle(hook_input)
        assert result.decision == Decision.DENY
        assert "alpha-term" not in result.model_dump_json()
        assert "the host" not in (result.reason or "")
        assert str(body) in (result.reason or "")

    def test_relative_body_file_resolves_against_cwd(self, tmp_path: Path) -> None:
        handler = _wordlist(tmp_path, "alpha-term")
        (tmp_path / "body.md").write_text("alpha-term\n")

        hook_input = _bash_input("gh pr comment 3 --body-file body.md")
        hook_input["cwd"] = str(tmp_path)
        assert handler.matches(hook_input) is True

    def test_public_pattern_in_gh_body_is_denied(self) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "vhosts-path", "pattern": "/var/www/vhosts", "description": "d"}]
        )
        command = 'gh pr comment 3 --body "deployed to /var/www/vhosts/site"'
        result = handler.handle(_bash_input(command))
        assert result.decision == Decision.DENY
        assert "vhosts-path" in (result.reason or "")

    @pytest.mark.parametrize(
        "command",
        [
            "gh issue view 12 --comments",
            "gh pr view 12 --comments",
            "gh issue list --search alpha-term",
            "gh pr checkout 12",
            'gh issue comment 12 --body "an ordinary comment"',
            'gh api repos/o/r/issues -f body="alpha-term"',
        ],
    )
    def test_reads_and_clean_bodies_are_allowed(self, tmp_path: Path, command: str) -> None:
        """Reading GitHub, or posting a clean body, is never blocked. ``gh api``
        is deliberately outside this surface: ``-F`` means something else
        there and the body route is a generic field, so it is documented as
        uncovered rather than half-covered."""
        handler = _wordlist(tmp_path, "alpha-term")

        assert handler.matches(_bash_input(command)) is False

    def test_missing_body_file_is_allowed(self, tmp_path: Path) -> None:
        """An unreadable body file cannot be judged; gh itself fails on it."""
        handler = _wordlist(tmp_path, "alpha-term")

        hook_input = _bash_input(f"gh issue comment 12 --body-file {tmp_path / 'absent.md'}")
        assert handler.matches(hook_input) is False

    def test_stdin_body_file_is_allowed(self, tmp_path: Path) -> None:
        handler = _wordlist(tmp_path, "alpha-term")

        assert handler.matches(_bash_input("gh issue comment 12 --body-file -")) is False


class TestPerDispatchHaystackCache:
    """The ``matches()``->``handle()`` bridge must never answer one call from another's text.

    The cache exists so a staged diff (a subprocess) and a body file (a read)
    are paid for ONCE per dispatch. Keying it on ``id(hook_input)`` was wrong:
    ``id`` is unique only among LIVE objects, and the daemon frees each
    event's dict when the dispatch ends -- so a later dict allocated at that
    address compares EQUAL to the cached key and the handler answers the NEW
    event from the PREVIOUS event's haystacks. The daemon also dispatches on
    a thread pool, so one handler instance really is shared across
    concurrently allocating events.

    The failure is silent and bidirectional: a clean call denied on another
    call's match, or a dirty call allowed on another call's clean text. Every
    test here forces the address collision deterministically rather than
    waiting for the allocator to produce one.
    """

    @staticmethod
    def _force_one_address(monkeypatch: pytest.MonkeyPatch) -> None:
        """Make every ``id()`` in the handler module answer the same address.

        Shadowing the builtin in the module namespace reproduces an address
        collision exactly, with no dependence on CPython's allocator. Once
        the cache key is content-derived nothing in the module calls ``id``
        at all, which is precisely what these tests assert.
        """
        monkeypatch.setattr(sensitive_content_module, "id", lambda _object: 1, raising=False)

    def test_a_new_input_at_the_same_address_is_judged_on_its_own_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        handler = _wordlist(tmp_path, "alpha-term")
        self._force_one_address(monkeypatch)

        assert handler.matches(_bash_input('git tag -m "alpha-term" v1')) is True
        assert handler.matches(_bash_input('git tag -m "ordinary release note" v2')) is False

    def test_handle_does_not_deny_a_clean_call_on_the_previous_calls_match(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Direction one: a clean commit denied, naming another call's pattern."""
        handler = _wordlist(tmp_path, "alpha-term")
        self._force_one_address(monkeypatch)

        assert handler.matches(_bash_input('git tag -m "alpha-term" v1')) is True
        assert handler.handle(_bash_input('git tag -m "ordinary note" v2')).decision == (
            Decision.ALLOW
        )

    def test_a_term_is_not_waved_through_on_a_previous_clean_dispatch(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Direction two -- the one that matters: the term reaching the commit."""
        handler = _wordlist(tmp_path, "alpha-term")
        self._force_one_address(monkeypatch)

        assert handler.matches(_bash_input('git tag -m "ordinary note" v1')) is False
        dirty = _bash_input('git tag -m "alpha-term" v2')
        assert handler.matches(dirty) is True
        assert handler.handle(dirty).decision == Decision.DENY

    def test_the_same_command_in_another_repo_is_judged_against_that_repo(
        self, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The staged diff belongs to a repository, so ``cwd`` disambiguates too."""
        handler = _wordlist(tmp_path, "alpha-term")
        _stage(repo, "notes/report.md", "alpha-term\n")
        clean_repo = tmp_path / "clean-repo"
        clean_repo.mkdir()
        _git(clean_repo, "init", "-q")
        _git(clean_repo, "config", "user.email", "t@example.com")
        _git(clean_repo, "config", "user.name", "T")
        self._force_one_address(monkeypatch)

        assert handler.matches(_commit_input(repo)) is True
        assert handler.matches(_commit_input(clean_repo)) is False

    def test_handle_reuses_the_cache_for_the_call_matches_just_judged(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """The bridge still works: one staged-diff subprocess per dispatch.

        Same guarantee as ``test_matches_and_handle_agree_on_one_diff_read``,
        asserted here on the ALLOW path -- a clean commit must not pay for the
        diff twice either.
        """
        handler = _wordlist(tmp_path, "alpha-term")
        _stage(repo, "notes/clean.md", "nothing to see\n")
        hook_input = _commit_input(repo)

        with patch(
            "claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content.run_git",
            wraps=sensitive_content_module.run_git,
        ) as spy:
            assert handler.matches(hook_input) is False
            assert handler.handle(hook_input).decision == Decision.ALLOW
        assert len([call for call in spy.call_args_list if "diff" in call.args]) == 1

    def test_commit_side_effects_drops_the_retained_text(
        self, repo: Path, tmp_path: Path
    ) -> None:
        """Nothing a call introduced is kept on the shared instance afterwards.

        ``matches()`` can be the last method a dispatch calls (another
        terminal handler denies first), so the chain's post-decision hook is
        where the retained staged content -- which is exactly the text this
        handler exists to keep out of sight -- is released.
        """
        handler = _wordlist(tmp_path, "alpha-term")
        _stage(repo, "notes/report.md", "alpha-term\n")
        hook_input = _commit_input(repo)
        assert handler.matches(hook_input) is True

        handler.commit_side_effects(hook_input, Decision.DENY)

        assert handler._cached_dispatch is None


class TestGetClaudeMd:
    def test_guidance_names_the_staged_content_and_gh_body_surfaces(self) -> None:
        text = SensitiveContentHandler().get_claude_md() or ""
        assert "staged" in text.lower()
        assert "gh issue comment" in text
        assert "--body-file" in text

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

    def test_declares_a_staged_content_and_a_gh_body_probe(self) -> None:
        titles = [test.title for test in SensitiveContentHandler().get_acceptance_tests()]
        assert any("staged" in title for title in titles)
        assert any("gh" in title and "body" in title for title in titles)


class TestGetRules:
    """get_rules() declares the 2 Rule objects backing this handler (Plan 00116)."""

    def test_returns_two_rules(self) -> None:
        rules = SensitiveContentHandler().get_rules()
        assert len(rules) == 2
        assert all(isinstance(rule, Rule) for rule in rules)

    def test_rule_ids_match_constants(self) -> None:
        expected = {RuleID.SENSITIVE_PUBLIC_PATTERN, RuleID.SENSITIVE_SECRET_TERM}
        actual = {rule.rule_id for rule in SensitiveContentHandler().get_rules()}
        assert actual == expected

    def test_every_rule_has_non_empty_verbose(self) -> None:
        for rule in SensitiveContentHandler().get_rules():
            assert rule.verbose, f"{rule.rule_id} has empty verbose content"


class TestDisclosureLadder:
    """Verbose-first / terse-after per-agent disclosure ladder (Decision G)."""

    def test_public_pattern_first_fire_is_verbose(self) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "vhosts-path", "pattern": "/var/www/vhosts", "description": "server path"}]
        )
        hook_input = _write_input("/tmp/f.txt", "deploy to /var/www/vhosts/app")
        hook_input["transcript_path"] = "/tmp/agent-a/transcript.jsonl"
        result = handler.handle(hook_input)

        assert result.decision == Decision.DENY
        assert "safe to name in this reason" in (result.reason or "")
        assert "vhosts-path" in (result.reason or "")

    def test_public_pattern_second_fire_is_terse_but_still_names_the_match(self) -> None:
        handler = _handler_with_public_patterns(
            [
                {"name": "vhosts-path", "pattern": "/var/www/vhosts", "description": "d"},
                {"name": "etc-path", "pattern": "/etc/other", "description": "d"},
            ]
        )
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        first = _write_input("/tmp/f.txt", "deploy to /var/www/vhosts/app")
        first["transcript_path"] = transcript_path
        handler.handle(first)

        second = _write_input("/tmp/g.txt", "other at /etc/other/x")
        second["transcript_path"] = transcript_path
        result = handler.handle(second)

        assert result.decision == Decision.DENY
        assert "safe to name in this reason" not in (result.reason or "")
        assert "etc-path" in (result.reason or "")

    def test_public_pattern_terse_leads_with_rule_id(self) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "vhosts-path", "pattern": "/var/www/vhosts", "description": "d"}]
        )
        transcript_path = "/tmp/agent-a/transcript.jsonl"
        hook_input = _write_input("/tmp/f.txt", "deploy to /var/www/vhosts/app")
        hook_input["transcript_path"] = transcript_path
        handler.handle(hook_input)
        result = handler.handle(hook_input)

        assert result.reason.startswith(f"BLOCKED [{RuleID.SENSITIVE_PUBLIC_PATTERN}]")

    def test_secret_term_never_leaks_regardless_of_disclosure_state(self, tmp_path: Path) -> None:
        """The no-echo contract holds on BOTH the verbose and terse fire."""
        wordlist_file = tmp_path / "wordlist.txt"
        wordlist_file.write_text("zzqx-nonsense-term\n")
        handler = _handler_with_secret_file(wordlist_file)
        transcript_path = "/tmp/agent-a/transcript.jsonl"

        first = _write_input("/tmp/f.txt", "contains zzqx-nonsense-term here")
        first["transcript_path"] = transcript_path
        verbose_result = handler.handle(first)
        assert "zzqx-nonsense-term" not in (verbose_result.reason or "")
        assert "entry 1 of 1" in (verbose_result.reason or "")

        second = _write_input("/tmp/g.txt", "also has zzqx-nonsense-term inside")
        second["transcript_path"] = transcript_path
        terse_result = handler.handle(second)
        assert "zzqx-nonsense-term" not in (terse_result.reason or "")
        assert "entry 1 of 1" in (terse_result.reason or "")
        assert terse_result.reason.startswith(f"BLOCKED [{RuleID.SENSITIVE_SECRET_TERM}]")

    def test_missing_transcript_path_is_always_verbose(self) -> None:
        handler = _handler_with_public_patterns(
            [{"name": "vhosts-path", "pattern": "/var/www/vhosts", "description": "d"}]
        )
        hook_input = _write_input("/tmp/f.txt", "deploy to /var/www/vhosts/app")
        handler.handle(hook_input)
        result = handler.handle(hook_input)

        assert "safe to name in this reason" in (result.reason or "")


class TestDeclaredAcceptancePatternsAreProducible:
    """Every declared acceptance pattern must match the reason really produced.

    The release acceptance gate passes a test only when the handler's own
    ``expected_message_patterns`` match the live deny reason. A pattern left
    behind by a header change therefore makes the gate unpassable while the
    handler is behaving perfectly -- reporting a correct handler as a release
    blocker, and costing a FAIL-FAST cycle to work out that nothing is wrong.
    """

    def test_public_pattern_deny_reason_matches_its_declared_patterns(self) -> None:
        handler = _handler_with_public_patterns(
            [
                {
                    "name": "vhosts-path",
                    "pattern": "/var/www/vhosts",
                    "description": "employer/hosting-provider server path convention",
                }
            ]
        )
        reason = handler.handle(_write_input("/tmp/f.txt", "deploy to /var/www/vhosts/app")).reason
        declared = next(
            test
            for test in handler.get_acceptance_tests()
            if "blocks a configured public pattern" in test.title
        )
        for pattern in declared.expected_message_patterns:
            assert re.search(pattern, reason or ""), f"{pattern!r} no longer appears in: {reason}"

    def test_secret_term_deny_reason_matches_its_declared_patterns(self, tmp_path: Path) -> None:
        wordlist_file = tmp_path / "wordlist.txt"
        wordlist_file.write_text("zzqx-nonsense-term\n")
        handler = _handler_with_secret_file(wordlist_file)
        reason = handler.handle(
            _write_input("/tmp/f.txt", "contains zzqx-nonsense-term here")
        ).reason
        declared = next(
            test for test in handler.get_acceptance_tests() if "without revealing it" in test.title
        )
        for pattern in declared.expected_message_patterns:
            assert re.search(pattern, reason or ""), f"{pattern!r} no longer appears in: {reason}"

    def test_secret_term_commit_message_deny_reason_matches_declared_patterns_after_write_probe(
        self, tmp_path: Path
    ) -> None:
        """Plan 00319 Task 4.2: the two secret-term deny acceptance tests

        ("without revealing it" and "in a commit message") share ONE
        per-transcript verbose-disclosure budget for
        ``RuleID.SENSITIVE_SECRET_TERM``. A human tester runs a playbook
        top-to-bottom in ONE continuous session, so the Write probe fires
        first and spends that budget -- the commit-message probe that
        follows necessarily sees the TERSE form. Its declared patterns must
        hold under that realistic order, not only in isolation.
        """
        wordlist_file = tmp_path / "wordlist.txt"
        wordlist_file.write_text("zzqx-nonsense-term\n")
        handler = _handler_with_secret_file(wordlist_file)
        transcript_path = "/tmp/acceptance-transcript-shared.jsonl"

        write_input = _write_input(str(tmp_path / "probe.txt"), "contains zzqx-nonsense-term here")
        write_input["transcript_path"] = transcript_path
        handler.handle(write_input)  # spends the verbose budget, as the real first test does

        commit_input = {
            "tool_name": "Bash",
            "tool_input": {"command": 'git commit -m "zzqx-nonsense-term"'},
            "transcript_path": transcript_path,
        }
        reason = handler.handle(commit_input).reason

        declared = next(
            test for test in handler.get_acceptance_tests() if "in a commit message" in test.title
        )
        for pattern in declared.expected_message_patterns:
            assert re.search(pattern, reason or ""), f"{pattern!r} no longer appears in: {reason}"
        assert "zzqx-nonsense-term" not in (reason or "")
