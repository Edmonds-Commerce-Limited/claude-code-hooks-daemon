"""sensitive_content judges the metadata VALUE being recorded, not the whole command line.

Ledger 00474 N364 and N341. The handler's guidance says only commands that WRITE
git metadata (or publish a ``gh`` body) are candidates and reading is never
blocked. Two over-reaches broke that:

* ``git config`` was treated as an identity write even for ``--get-regexp``,
  ``--get-all``, ``--show-origin`` and a bare ``git config user.name`` read.
* Once ONE metadata surface was present the whole command line was scanned, so a
  term in an unrelated ``cd <path>`` or a separate command denied it.

The word list is a fixture in ``tmp_path``; no real list is opened.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content import (
    SensitiveContentHandler,
)
from claude_code_hooks_daemon.utils import secret_redaction as sr

_TERM = "alpha-term"


@pytest.fixture(autouse=True)
def _reset_caches() -> Iterator[None]:
    reset_data_layer()
    sr.reset_terms_cache()
    sr.reset_active_path_cache()
    yield
    reset_data_layer()
    sr.reset_terms_cache()
    sr.reset_active_path_cache()


@pytest.fixture()
def handler(tmp_path: Path) -> SensitiveContentHandler:
    wordlist = tmp_path / "wordlist.txt"
    wordlist.write_text(f"{_TERM}\n")
    gate = SensitiveContentHandler()
    gate._secret_word_list_path = wordlist.name
    gate._project_root_override = wordlist.parent
    return gate


def _input(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


class TestConfigReadsAreNotIdentityWrites:
    """N364: a ``git config`` that assigns nothing records nothing."""

    @pytest.mark.parametrize(
        "command",
        [
            f"git config --get-regexp '^user\\.name$' {_TERM}",
            f"git config --get-all user.name {_TERM}",
            f"git config --show-origin --get-regexp '^(user\\.name|{_TERM})$'",
            f"git config --list --show-origin # {_TERM}",
            "git config user.name",
            f"git config --global user.name; echo {_TERM}",
            f"cd /x/{_TERM} && git config --show-origin --get-regexp '^user\\.name$'; git log",
        ],
    )
    def test_config_read_is_allowed(
        self, handler: SensitiveContentHandler, tmp_path: Path, command: str
    ) -> None:
        assert handler.matches(_input(command, tmp_path)) is False

    @pytest.mark.parametrize(
        "command",
        [
            f'git config user.name "{_TERM}"',
            f"git config user.email {_TERM}@example.com",
            f"git config --global user.name {_TERM}",
            f"git config --add user.name {_TERM}",
            f"git config --replace-all user.name {_TERM}",
        ],
    )
    def test_config_assignment_is_still_denied(
        self, handler: SensitiveContentHandler, tmp_path: Path, command: str
    ) -> None:
        assert handler.matches(_input(command, tmp_path)) is True
        assert handler.handle(_input(command, tmp_path)).decision == Decision.DENY


class TestOnlyTheMetadataCommandIsScanned:
    """N364 second shape and N341: a term in an unrelated part of the line is not metadata."""

    @pytest.mark.parametrize(
        "command",
        [
            f"cd /home/{_TERM}/clone && git switch -c fix/ordinary-name origin/main",
            f"cd /home/{_TERM}/.. && git worktree remove wt && git branch -d fix/ordinary",
            f"cd /home/{_TERM}/clone && git tag v1.0.0",
            f"grep {_TERM} f; git commit -m 'ordinary message'",
            f"echo {_TERM} && git checkout -b fix/ordinary",
            f"git branch -d {_TERM}-old",
            f"git branch -D {_TERM}-old",
            f"git branch --delete {_TERM}-old",
        ],
    )
    def test_term_outside_the_metadata_value_is_allowed(
        self, handler: SensitiveContentHandler, tmp_path: Path, command: str
    ) -> None:
        assert handler.matches(_input(command, tmp_path)) is False

    @pytest.mark.parametrize(
        "command",
        [
            f"cd /x && git switch -c fix/{_TERM}-thing origin/main",
            f"ls && git commit -m 'about {_TERM}'",
            f"cd /x; git tag -a v1 -m '{_TERM}'",
            f"git status\ngit branch {_TERM}-work",
            f"git fetch && git merge --no-ff -m 'merge {_TERM}' feature",
            f"echo hi | git commit -m '{_TERM}'",
        ],
    )
    def test_term_in_the_metadata_value_of_a_compound_command_is_denied(
        self, handler: SensitiveContentHandler, tmp_path: Path, command: str
    ) -> None:
        assert handler.matches(_input(command, tmp_path)) is True
        assert handler.handle(_input(command, tmp_path)).decision == Decision.DENY

    def test_a_flag_word_inside_a_message_does_not_exempt_the_commit(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        command = f"git commit -m 'add --list flag for {_TERM}'"

        assert handler.matches(_input(command, tmp_path)) is True

    def test_a_heredoc_message_of_the_commit_is_still_scanned(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        command = f"cd /x && git commit -F - <<'EOF'\nabout {_TERM}\nEOF"

        assert handler.matches(_input(command, tmp_path)) is True

    def test_a_heredoc_of_an_unrelated_command_is_not_scanned(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        command = f"cat > notes.txt <<'EOF'\nabout {_TERM}\nEOF\ngit tag v1"

        assert handler.matches(_input(command, tmp_path)) is False


class TestReadingCommandsStayAllowed:
    @pytest.mark.parametrize(
        "command",
        [
            f"grep {_TERM} f",
            f"git log --grep={_TERM}",
            f"git show {_TERM}-tag",
            f"git branch --list '{_TERM}*'",
            f"git tag -l '{_TERM}*'",
        ],
    )
    def test_reading_is_allowed(
        self, handler: SensitiveContentHandler, tmp_path: Path, command: str
    ) -> None:
        assert handler.matches(_input(command, tmp_path)) is False


class TestGhBodyScope:
    def test_gh_body_in_a_compound_command_is_denied(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        command = f"cd /x && gh issue comment 5 --body 'see {_TERM}'"

        assert handler.matches(_input(command, tmp_path)) is True

    def test_term_in_an_unrelated_part_of_a_gh_command_line_is_allowed(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        command = f"cd /x/{_TERM} && gh issue comment 5 --body 'fine'"

        assert handler.matches(_input(command, tmp_path)) is False

    def test_gh_body_file_is_still_read(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        body = tmp_path / "body.md"
        body.write_text(f"mentions {_TERM}\n")
        command = f"cd /x && gh pr create --title t --body-file {body}"

        assert handler.matches(_input(command, tmp_path)) is True

    def test_commit_message_file_is_still_read(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        message = tmp_path / "msg.txt"
        message.write_text(f"mentions {_TERM}\n")
        command = f"cd /x && git commit -F {message}"

        assert handler.matches(_input(command, tmp_path)) is True
