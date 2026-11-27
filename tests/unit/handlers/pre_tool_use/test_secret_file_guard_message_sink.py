"""Ledger 00474 N744 (reopened) and N760: the teamchat message-verb sink.

A teamchat message verb (say, reply, report, thread, ask-human, close,
retitle) reads its text on stdin, so every real send goes through a quoted
heredoc, a here-string or a pipe from one literal printf/echo. That text is
posted, never opened or run, so it is not judged as a path mention; the
teamchat words (a ``--ref path:...``, a member name) still are, and every other
shape is judged exactly as before.

Also pinned here: N749's narrowing of the underscore patterns (an identifier
with no slash and no leading dot counts only when it names a file that exists,
is indexed, or is opened), and the deny's position of the matched word inside
a long quoted token.

Synthetic fixtures only: the protected files live in ``tmp_path`` and their
names are assembled so this file never spells one.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.indexed_project import index_project

from claude_code_hooks_daemon.constants.tools import ToolName
from claude_code_hooks_daemon.core import Decision, GatingResult
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import link_index, path_exclusion, protected_file_index
from claude_code_hooks_daemon.utils import secret_file_matching as sfm
from claude_code_hooks_daemon.utils.shell_snapshot import reset_snapshot_cache

_SUFFIX = ".sec" + "ret"
_PROTECTED_NAME = "app" + _SUFFIX
_SECRET_GLOB = "*" + _SUFFIX + "*"
_SG = _SECRET_GLOB
#: An underscore-pattern word, assembled: ``x_`` + the vault-password stem.
_VAULT_STEM = "vault" + "_pass"
_IDENTIFIER = "test_a_missing_" + _VAULT_STEM + "word_file_is_tool_unavailable"
_EXISTING_IDENT = "kept_" + _VAULT_STEM
_HEREDOC = "<<'EOF'"


@dataclass(frozen=True)
class Project:
    root: Path
    vault: Path
    protected: Path


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Project]:
    base = tmp_path.resolve()
    (base / "home").mkdir()
    config = base / "claude-config"
    config.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    root = base / "proj"
    vault = root / "vault"
    vault.mkdir(parents=True)
    protected = vault / _PROTECTED_NAME
    protected.write_bytes(b"DUMMY\n")
    (root / _EXISTING_IDENT).write_bytes(b"DUMMY\n")
    monkeypatch.chdir("/")
    monkeypatch.setenv("HOME", str(base / "home"))
    reset_snapshot_cache()
    protected_file_index.reset_index_cache()
    link_index.reset_link_indexes()
    with (
        patch.object(guard_module, "resolve_project_root", return_value=str(root)),
        patch.object(sfm, "resolve_project_root", return_value=str(root)),
        patch.object(path_exclusion, "resolve_project_root", return_value=str(root)),
    ):
        index_project(root, SecretFileGuardHandler()._patterns())
        link_index.prewarm(str(root))
        link_index.wait_for_link_index(60.0)
        yield Project(root=root, vault=vault, protected=protected)
    link_index.reset_link_indexes()
    protected_file_index.reset_index_cache()
    reset_snapshot_cache()


def _run(hook_input: dict[str, Any]) -> GatingResult:
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return GatingResult(decision=Decision.ALLOW)
    return handler.handle(hook_input)


def _bash(command: str, cwd: Path) -> GatingResult:
    return _run({"tool_name": ToolName.BASH, "tool_input": {"command": command}, "cwd": str(cwd)})


def _write(path: Path, content: str) -> GatingResult:
    return _run(
        {
            "tool_name": ToolName.WRITE,
            "tool_input": {"file_path": str(path), "content": content},
            "cwd": str(path.parent),
        }
    )


def _heredoc(head: str, body: str) -> str:
    return f"{head} {_HEREDOC}\n{body}\nEOF"


#: Message text that names, globs or spells every protected class.
_BODIES: tuple[str, ...] = (
    f"the deny `Bash(cat {_SG})` is in force over vault/**",
    "see vault/" + _PROTECTED_NAME + " for the reason",
    f"do not repeat {_SG} or cat vault/* in a command",
    f"the test {_IDENTIFIER} now passes",
)

_SINK_HEADS: tuple[str, ...] = (
    "teamchat say --to lead",
    "teamchat reply ev1",
    "teamchat report",
    "teamchat thread Q3",
    "teamchat ask-human --for owner",
    "teamchat close Q1",
    "teamchat retitle Q2",
)


class TestAMessageOnStdinIsNotAMention:
    @pytest.mark.parametrize("head", _SINK_HEADS)
    @pytest.mark.parametrize("body", _BODIES)
    def test_heredoc(self, project: Project, head: str, body: str) -> None:
        assert _bash(_heredoc(head, body), project.root).decision == Decision.ALLOW

    @pytest.mark.parametrize("body", _BODIES)
    def test_printf_pipe(self, project: Project, body: str) -> None:
        command = f"printf '%s\\n' 'headline' '{body}' | teamchat report"
        assert _bash(command, project.vault).decision == Decision.ALLOW

    @pytest.mark.parametrize("body", _BODIES)
    def test_echo_pipe(self, project: Project, body: str) -> None:
        assert _bash(f"echo '{body}' | teamchat say --to lead", project.vault).decision == (
            Decision.ALLOW
        )

    @pytest.mark.parametrize("body", _BODIES)
    def test_here_string(self, project: Project, body: str) -> None:
        assert _bash(f"teamchat report <<< '{body}'", project.vault).decision == Decision.ALLOW


#: Each must stay DENY: it opens, runs, writes or names a protected path outside
#: the posted text, or is not exactly one plain message-verb statement.
_DANGEROUS: tuple[str, ...] = (
    # The teamchat words themselves are still judged.
    _heredoc("teamchat reply ev1 --verb done --ref path:o/r@a:vault/" + _PROTECTED_NAME, "ok"),
    _heredoc("teamchat say --to vault/" + _PROTECTED_NAME, "ok"),
    _heredoc(f"teamchat say --to 'vault/{_SG}'", "ok"),
    # A producer that opens the file.
    "cat vault/" + _PROTECTED_NAME + " | teamchat report",
    f"cat vault/{_SG} | teamchat report",
    "teamchat report < vault/" + _PROTECTED_NAME,
    "head -c9 vault/* | teamchat report",
    f"cat {_HEREDOC} | teamchat report\nvault/{_PROTECTED_NAME}\nEOF",
    # A substitution or an unquoted heredoc expands the body.
    f'printf "%s" "$(cat vault/{_PROTECTED_NAME})" | teamchat report',
    f"teamchat report <<EOF\n$(cat vault/{_PROTECTED_NAME})\nEOF",
    f'teamchat report <<< "$(cat vault/{_PROTECTED_NAME})"',
    # The text is also run, written or sent on.
    f"printf 'cat vault/{_SG}' | teamchat report | bash",
    f"printf 'cat vault/{_SG}' | bash",
    f"printf 'cat vault/{_SG}' | tee run.sh",
    f"printf 'cat vault/{_SG}' > run.sh",
    f"printf 'cat vault/{_SG}' | teamchat report > run.sh",
    f"printf 'cat vault/{_SG}' | tee vault/{_PROTECTED_NAME}",
    f"tee vault/{_PROTECTED_NAME} {_HEREDOC}\nx\nEOF",
    f"cat > run.sh {_HEREDOC}\ncat vault/{_SG}\nEOF",
    _heredoc("teamchat report", f"cat vault/{_SG}") + '\nbash -c "$(teamchat history)"',
    _heredoc("teamchat report", "x") + f"\ncat vault/{_PROTECTED_NAME}",
    f"teamchat report {_HEREDOC} && cat vault/{_PROTECTED_NAME}\nx\nEOF",
    # Not a message verb.
    _heredoc("teamchat run --plain --kind other -- bash", f"cat vault/{_SG}"),
    _heredoc("teamchat send general", f"cat vault/{_SG}"),
    f"teamchat send general 'vault/{_SG}'",
    _heredoc("bash", f"cat vault/{_SG}"),
    # A wrapper, an assignment or an unknown flag in front of the verb.
    _heredoc("X=1 teamchat report", "vault/" + _PROTECTED_NAME),
    _heredoc("command teamchat report", "vault/" + _PROTECTED_NAME),
    _heredoc("teamchat report --file x", "vault/" + _PROTECTED_NAME),
    # A function or alias named like the sink.
    "teamchat() { cat $1; }; " + _heredoc("teamchat report", "vault/" + _PROTECTED_NAME),
    "alias teamchat=cat; " + _heredoc("teamchat report", "vault/" + _PROTECTED_NAME),
    # Plain reads, as on main.
    "cat vault/" + _PROTECTED_NAME,
    f"cat vault/{_SG}",
    "echo vault/" + _PROTECTED_NAME,
)


class TestEverythingElseIsJudgedAsBefore:
    @pytest.mark.parametrize("command", _DANGEROUS)
    def test_shape_is_denied(self, project: Project, command: str) -> None:
        assert _bash(command, project.root).decision == Decision.DENY

    def test_authored_script_holding_a_sink_statement_is_judged_whole(
        self, project: Project
    ) -> None:
        """A script is RUN; the sink relaxes Bash tool commands only."""
        content = "#!/usr/bin/env bash\n" + _heredoc("teamchat report", f"cat vault/{_SG}")
        content += "\ncat vault/" + _PROTECTED_NAME + "\n"
        assert _write(project.root / "send.bash", content).decision == Decision.DENY


class TestUnderscoreIdentifierNarrowing:
    """N749: an identifier-shaped word counts for an underscore pattern only when it is a file."""

    def test_python_test_name_is_allowed_in_authored_source(self, project: Project) -> None:
        content = f"def {_IDENTIFIER}() -> None:\n    assert True\n"
        assert _write(project.root / "test_x.py", content).decision == Decision.ALLOW

    @pytest.mark.parametrize("quote", ["", "'"])
    def test_identifier_printed_by_echo_is_allowed(self, project: Project, quote: str) -> None:
        command = f"echo {quote}add {_IDENTIFIER}{quote}"
        assert _bash(command, project.root).decision == Decision.ALLOW

    def test_the_last_quoted_word_is_placed_like_any_other(self, project: Project) -> None:
        """A bare dotted word ending a quoted string is gated as one in the middle is."""
        dotted = "cfg" + _SUFFIX + ".key"
        assert _bash(f"echo 'see {dotted}'", project.root).decision == Decision.ALLOW
        assert _bash(f"cat 'see {dotted}'", project.root).decision == Decision.DENY
        assert _bash(f"echo 'see {dotted}' > out", project.root).decision == Decision.ALLOW

    def test_identifier_as_a_commit_message_is_still_judged_as_a_pathspec(
        self, project: Project
    ) -> None:
        """As for a bare dotted word, git is a file-opening head (its pathspecs)."""
        command = f"git commit -m 'add {_IDENTIFIER}'"
        assert _bash(command, project.root).decision == Decision.DENY

    def test_an_existing_file_of_that_name_still_denies(self, project: Project) -> None:
        assert _bash(f"ls {_EXISTING_IDENT}", project.root).decision == Decision.DENY

    def test_an_opened_identifier_still_denies(self, project: Project) -> None:
        assert _bash(f"cat other_{_VAULT_STEM}", project.root).decision == Decision.DENY

    def test_an_identifier_passed_to_open_still_denies(self, project: Project) -> None:
        content = f"data = open('other_{_VAULT_STEM}').read()\n"
        assert _write(project.root / "reader.py", content).decision == Decision.DENY

    @pytest.mark.parametrize("prefix", ["./", "/", "~/", "."])
    def test_a_path_shaped_word_is_judged_by_the_pattern_alone(
        self, project: Project, prefix: str
    ) -> None:
        command = f"echo {prefix}other_{_VAULT_STEM}"
        assert _bash(command, project.root).decision == Decision.DENY


class TestDenyPlacesTheWordInsideALongToken:
    """N760: a deny on a long quoted token says WHICH word in it matched, by position."""

    def test_the_word_number_and_place_are_reported(self, project: Project) -> None:
        token = f"notes and more {_SG} words"
        haystack = f"x\nprintf '{token}'"
        line = guard_module._word_in_token(haystack, token, _SECRET_GLOB)
        assert line == "The matched word is word 4 of that token, at line 2, column 24."
        assert _SECRET_GLOB not in (line or "")

    def test_a_token_the_input_does_not_hold_verbatim_gets_the_number_only(
        self, project: Project
    ) -> None:
        line = guard_module._word_in_token("other", f"a {_SG}", _SECRET_GLOB)
        assert line == "The matched word is word 2 of that token."

    @pytest.mark.parametrize("token", ["vault/" + _PROTECTED_NAME, "a b c"])
    def test_no_line_for_one_word_or_no_matching_word(self, project: Project, token: str) -> None:
        assert guard_module._word_in_token(token, token, _SECRET_GLOB) is None

    def test_a_deny_on_a_one_word_token_carries_no_word_line(self, project: Project) -> None:
        result = _bash("cat 'vault/" + _PROTECTED_NAME + "'", project.root)
        assert result.decision == Decision.DENY
        assert "The matched word is" not in (result.reason or "")

    def test_the_deny_appends_the_word_line_for_a_long_token(
        self, project: Project, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole-token report N760 saw, forced: the ordinary stream names one word first."""
        token = f"notes and more vault/{_PROTECTED_NAME} words"
        handler = SecretFileGuardHandler()
        monkeypatch.setattr(
            handler, "_take_cached_matched", lambda _hook_input: (_SECRET_GLOB, token, "bash")
        )
        hook_input = {
            "tool_name": ToolName.BASH,
            "tool_input": {"command": f"printf '{token}'"},
            "cwd": str(project.root),
        }
        reason = handler.handle(hook_input).reason or ""
        assert "The matched word is word 4 of that token, at line 1, column 24." in reason
        assert _SECRET_GLOB not in reason
