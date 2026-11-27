"""Ledger 00474 N744 (reopened) and N760: the teamchat message-verb sink.

A teamchat message verb (say, reply, report, thread, ask-human, close,
retitle) reads its text on stdin, so every real send goes through a quoted
heredoc, a here-string or a pipe from one literal printf/echo. That text is
posted, never opened or run, so it is not judged as a path mention; the
teamchat words (a ``--ref path:...``, a member name) still are, and every other
shape is judged exactly as before.

Also pinned here: underscore-pattern words are judged as on main (N749 stays
open), and a quoted multi-word argument whose whole text names a present file
is a mention.

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


#: A directory change hidden where the guard cannot follow it (review 2 finding 1).
_HIDDEN_MOVES: tuple[str, ...] = (
    "source ./go.sh && ",
    ". ./go.sh; ",
    'eval "$(cat go.sh)" && ',
    "function f { cd ../ext; }; f; ",
    "source <(echo cd ../ext); ",
    "shopt -s expand_aliases; alias go='cd ../ext'\ngo\n",
    'cd "$(echo ../ext)" && ',
    "CDPATH=.. cd ext && ",
    'cd "$D" && ',
    "cd - && ",
)


class TestUnderscoreNamesAreJudgedAsOnMain:
    """N749 stays open: the narrowing was built, leaked twice under review, and was withdrawn.

    A word matching an underscore pattern is judged by the pattern alone, exactly as
    on main, wherever it sits and however the command moves first.
    """

    @pytest.fixture
    def outside(self, project: Project) -> Path:
        outside = project.root.parent / "ext"
        outside.mkdir(exist_ok=True)
        (outside / ("ext_" + _VAULT_STEM)).write_bytes(b"DUMMY\n")
        (project.root / "go.sh").write_text("cd ../ext\n", encoding="utf-8")
        return outside

    @pytest.mark.parametrize("move", ["", *_HIDDEN_MOVES])
    def test_a_bare_underscore_name_is_denied(
        self, project: Project, outside: Path, move: str
    ) -> None:
        command = f"{move}pr ext_{_VAULT_STEM}"
        assert _bash(command, project.root).decision == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [f"echo add {_IDENTIFIER}", f"echo 'add {_IDENTIFIER} now'", f"echo 'add {_IDENTIFIER}'"],
    )
    def test_an_identifier_printed_by_echo_is_denied(self, project: Project, command: str) -> None:
        assert _bash(command, project.root).decision == Decision.DENY

    @pytest.mark.parametrize(
        ("relative", "content"),
        [
            ("w10.sh", f"#!/usr/bin/env bash\npr ext_{_VAULT_STEM}\n"),
            ("w9.sh", f"#!/usr/bin/env bash\npr gone_{_VAULT_STEM}\n"),
            ("Makefile", f"all:\n\tpr ext_{_VAULT_STEM}\n"),
            ("test_x.py", f"def {_IDENTIFIER}() -> None:\n    assert True\n"),
        ],
    )
    def test_an_authored_file_naming_one_is_denied(
        self, project: Project, relative: str, content: str
    ) -> None:
        assert _write(project.root / relative, content).decision == Decision.DENY

    def test_find_by_that_name_then_exec_is_denied(self, project: Project, outside: Path) -> None:
        """Review 2 minor 3: pinned on its own, not only through another check."""
        command = f"find .. -name ext_{_VAULT_STEM} -exec pr {{}} +"
        assert _bash(command, project.root).decision == Decision.DENY


class TestASpacedProtectedNameIsAMention:
    """Review 1 blocker 1: the WHOLE quoted word names a file, whatever its single words do."""

    @pytest.mark.parametrize(
        "name",
        [
            "add kept2_" + _VAULT_STEM,
            "kept2_" + _VAULT_STEM + " more",
            "add z" + _SUFFIX + ".key",
            "z" + _SUFFIX + ".key more",
            "two words" + _SUFFIX,
            "mid z" + _SUFFIX + ".key dle",
            "add" + chr(0x00A0) + "z" + _SUFFIX + ".key",
        ],
    )
    @pytest.mark.parametrize("reader", ["pr", "expand", "nice pr", "command pr", "iconv -f utf-8"])
    @pytest.mark.parametrize("quote", ["'", '"'])
    def test_a_spaced_protected_name_that_exists_is_denied(
        self, project: Project, name: str, reader: str, quote: str
    ) -> None:
        (project.root / name).write_bytes(b"DUMMY\n")
        command = f"{reader} {quote}{name}{quote}"
        assert _bash(command, project.root).decision == Decision.DENY

    def test_a_dotted_word_in_the_middle_of_prose_is_still_gated(self, project: Project) -> None:
        """No such file exists, so the whole-name check adds nothing to plain prose."""
        dotted = "cfg" + _SUFFIX + ".key"
        assert _bash(f"echo 'see {dotted} now'", project.root).decision == Decision.ALLOW
