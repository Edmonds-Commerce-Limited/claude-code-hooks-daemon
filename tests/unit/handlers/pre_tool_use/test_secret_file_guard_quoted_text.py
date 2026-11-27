"""Ledger 00474 N757 and N759: text that only QUOTES a protected glob is not a mention.

N757 reported four shapes denied as a mention of a protected path although none
of them names, opens or expands to one:

1. A teamchat message quoting a Claude Code permission rule: a ``Bash(...)``
   deny with single stars around an app id inside backticks, and a path ending
   in a bare double star outside them.
2. A script written with ``Write`` holding the word ``shellcheck``, and one
   holding a bare star (the plan-script bootstrap).
3. A command whose message merely NAMES the secret-file glob in prose.
4. An awk regex such as ``/^ */``.

What must still deny is pinned beside them: real reads by cat/head/grep/Read/
Edit, a path handed to an interpreter one-liner, a copy, a glob that expands to
a protected file, a substitution that builds the path, a symlink to one, and a
quoted message whose text is piped on to a shell.

Synthetic fixtures only: the protected file lives in ``tmp_path`` and its name
is assembled so this file never spells one.
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
#: The shipped glob that protects any name holding the suffix, spelled in pieces.
_SECRET_GLOB = "*" + _SUFFIX + "*"
_SHEBANG = "#!/usr/bin/env bash\n"


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
    notes = root / "notes"
    notes.mkdir()
    (notes / "a.txt").write_bytes(b"plain\n")
    (root / "link-to-it").symlink_to(protected)
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


def _tool(tool_name: str, field: str, path: Path) -> GatingResult:
    tool_input: dict[str, Any] = {field: str(path)}
    if tool_name == ToolName.EDIT:
        tool_input.update({"old_string": "a", "new_string": "b"})
    return _run({"tool_name": tool_name, "tool_input": tool_input, "cwd": str(path.parent)})


class TestQuotedTextIsNotAMention:
    """The four N757 shapes are allowed."""

    def test_teamchat_message_quoting_a_permission_rule(self, project: Project) -> None:
        """Denied before the fix on the bare double star (the token named in the deny)."""
        command = (
            "teamchat send general 'the deny `Bash(open -a *com.example.App*)` is in force, "
            f"and the allow covers {project.root}/**'"
        )
        assert _bash(command, project.root).decision == Decision.ALLOW

    @pytest.mark.parametrize("text", ["x * y", "x ** y", "see vault/** here"])
    def test_teamchat_message_holding_a_glob_over_the_protected_file(
        self, project: Project, text: str
    ) -> None:
        """Each was denied before the fix: ``*`` at the root reaches a link to the file."""
        assert _bash(f'teamchat send general "{text}"', project.root).decision == Decision.ALLOW

    def test_teamchat_message_naming_the_secret_glob(self, project: Project) -> None:
        command = f'teamchat send general "the secret-file glob {_SECRET_GLOB} matched my word"'
        assert _bash(command, project.root).decision == Decision.ALLOW

    def test_echo_naming_the_secret_glob_in_single_quotes(self, project: Project) -> None:
        command = f"echo 'do not repeat {_SECRET_GLOB} in a command'"
        assert _bash(command, project.root).decision == Decision.ALLOW

    def test_git_commit_message_naming_the_secret_glob(self, project: Project) -> None:
        command = f"git commit -m 'guard: stop matching {_SECRET_GLOB} in prose'"
        assert _bash(command, project.root).decision == Decision.ALLOW

    def test_gh_body_naming_the_secret_glob(self, project: Project) -> None:
        command = f'gh issue comment 12 --body "the glob {_SECRET_GLOB} matched"'
        assert _bash(command, project.root).decision == Decision.ALLOW

    def test_printf_to_stderr_with_a_bracket_in_its_format(self, project: Project) -> None:
        """``>&2`` duplicates a descriptor; it is not a file the text is written to."""
        command = "printf '[FATAL] no %s in *\\n' x >&2"
        assert _bash(command, project.root).decision == Decision.ALLOW

    def test_literal_protected_name_in_an_echo_still_denies(self, project: Project) -> None:
        """Plan 00272 Decision 9 c stands for names: only a GLOB in sent text is relaxed."""
        command = "echo 'see vault/" + _PROTECTED_NAME + "'"
        assert _bash(command, project.root).decision == Decision.DENY

    def test_awk_regex_with_a_bare_star(self, project: Project) -> None:
        command = "awk '/^ */ {print}' notes/a.txt"
        assert _bash(command, project.root).decision == Decision.ALLOW

    def test_grep_regex_with_a_bare_star(self, project: Project) -> None:
        command = "grep -E '^ *x' notes/a.txt"
        assert _bash(command, project.root).decision == Decision.ALLOW

    def test_script_holding_the_word_shellcheck(self, project: Project) -> None:
        content = _SHEBANG + "# shellcheck disable=SC2034\nset -euo pipefail\nreadonly X=1\n"
        assert _write(project.root / "plan.bash", content).decision == Decision.ALLOW

    def test_script_holding_a_bare_star(self, project: Project) -> None:
        content = _SHEBANG + 'set -euo pipefail\nfor entry in "$1"/*; do\n  echo "$entry"\ndone\n'
        assert _write(project.root / "plan.bash", content).decision == Decision.ALLOW


class TestRealReadsStillDeny:
    """Everything that opens, copies or expands to the protected file is denied."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat vault/" + _PROTECTED_NAME,
            "head -n1 vault/" + _PROTECTED_NAME,
            "grep x vault/" + _PROTECTED_NAME,
            "cp vault/" + _PROTECTED_NAME + " /tmp/x",
            "python3 -c \"print(open('vault/" + _PROTECTED_NAME + "').read())\"",
            "cat vault/*",
            "cat $(printf vault/app)" + _SUFFIX,
            "cat link-to-it",
            "echo 'cat vault/" + _PROTECTED_NAME + "' | bash",
            'echo "$(cat vault/' + _PROTECTED_NAME + ')"',
            'teamchat send general "$(cat vault/' + _PROTECTED_NAME + ')"',
            'git commit -m "`cat vault/' + _PROTECTED_NAME + '`"',
            "echo vault/" + _PROTECTED_NAME,
            "cat " + _SECRET_GLOB,
            "cd vault && cat " + _SECRET_GLOB,
            "echo 'cat vault/*' | bash",
            "echo 'cat vault/*' | xargs cat",
            "echo 'cat vault/*' > run.sh && bash run.sh",
            "echo 'cat vault/*' &> run.sh && bash run.sh",
            "teamchat send general < 'vault/" + _PROTECTED_NAME + "'",
            "teamchat send general --file 'vault/" + _PROTECTED_NAME + "'",
            'teamchat send general "`cat vault/*`"',
            "git commit -F 'vault/" + _PROTECTED_NAME + "'",
            "git commit -m 'x' -- 'vault/" + _PROTECTED_NAME + "'",
            "bash -c 'echo hi; cat vault/*'",
            "echo 'x' && cat 'vault/" + _PROTECTED_NAME + "'",
        ],
    )
    def test_bash_read_denies(self, project: Project, command: str) -> None:
        assert _bash(command, project.root).decision == Decision.DENY

    @pytest.mark.parametrize(
        ("tool_name", "field"),
        [
            (ToolName.READ, "file_path"),
            (ToolName.EDIT, "file_path"),
            (ToolName.GREP, "path"),
        ],
    )
    def test_direct_tool_read_denies(self, project: Project, tool_name: str, field: str) -> None:
        assert _tool(tool_name, field, project.protected).decision == Decision.DENY

    def test_script_reading_the_protected_path_denies(self, project: Project) -> None:
        content = _SHEBANG + "cat vault/" + _PROTECTED_NAME + "\n"
        assert _write(project.root / "plan.bash", content).decision == Decision.DENY


_SG = _SECRET_GLOB


class TestQuotedTextExemptionIsClosed:
    """PR 291 review: every shape was DENY on main, so the exemption must not cover it.

    The exemption holds only when the whole command is text-printing statements
    and an allowlisted chain of filters, with no redirection, no variable-assigning
    option, no definition and nothing that could run the text.
    """

    @pytest.mark.parametrize(
        "command",
        [
            # A descriptor duplicate beside a later file redirect.
            f"echo 'cat vault/{_SG}' 2>&1 > run.sh; bash run.sh",
            f"echo 'cat {_SG}' >&2 2>run.sh",
            f"git commit -m 'cat {_SG}' 2>&1 > run.sh",
            # printf -v stores the text in a variable an unquoted expansion then globs.
            f"printf -v x '%s' 'vault/{_SG}'; cat $x",
            f"printf -vx '%s' 'vault/{_SG}'; cat $x",
            # A text filter's own redirect or output option.
            f"echo 'cat {_SG}' | tr a a > run.sh; bash run.sh",
            f"echo 'cat {_SG}' | head > run.sh",
            f"echo 'cat {_SG}' | cut -c1-80 >> run.sh",
            f"echo 'cat {_SG}' | grep cat > run.sh",
            f"echo 'cat {_SG}' | sort -o run.sh",
            f"echo 'cat {_SG}' | awk '{{print > \"run.sh\"}}'",
            f"echo 'cat {_SG}' | tee run.sh",
            f"echo 'cat {_SG}' &> run.sh",
            f"echo 'cat {_SG}' <> run.sh",
            f"cat <(echo 'cat {_SG}')",
            # A function or alias named like the printing command.
            f"echo() {{ cat $1; }}; echo 'vault/{_SG}'",
            f"function echo {{ cat $1; }}; echo 'vault/{_SG}'",
            f"alias echo=cat; echo 'vault/{_SG}'",
            # A later statement that pipes something to an interpreter.
            f"git commit -m 'cat {_SG}' && git log -1 --format=%B | bash",
            f"echo 'cat {_SG}' | bash",
            f"teamchat send general 'cat {_SG}'; eval \"$(teamchat read general)\"",
        ],
    )
    def test_shape_is_denied(self, project: Project, command: str) -> None:
        assert _bash(command, project.vault).decision == Decision.DENY


class TestDenyNamesClassAndPosition:
    """N757 c: the deny names the token's position and the pattern CLASS, never the glob."""

    def test_bash_deny_names_class_position_and_not_the_glob(self, project: Project) -> None:
        result = _bash("ls && cat vault/" + _PROTECTED_NAME, project.root)
        assert result.decision == Decision.DENY
        reason = result.reason or ""
        assert "Matched protected-path class: a secret-named file (entry 1 of" in reason
        assert "at line 1, column 11: `vault/" + _PROTECTED_NAME + "`" in reason
        assert _SECRET_GLOB not in reason

    def test_script_deny_names_the_line(self, project: Project) -> None:
        content = _SHEBANG + "set -e\ncat vault/" + _PROTECTED_NAME + "\n"
        result = _write(project.root / "plan.bash", content)
        assert result.decision == Decision.DENY
        assert "at line 3, column 5:" in (result.reason or "")
        assert _SECRET_GLOB not in (result.reason or "")

    def test_read_deny_names_the_class_only(self, project: Project) -> None:
        result = _tool(ToolName.READ, "file_path", project.protected)
        reason = result.reason or ""
        assert "a secret-named file" in reason
        assert _SECRET_GLOB not in reason
        assert _PROTECTED_NAME not in reason

    def test_every_shipped_default_has_a_class(self) -> None:
        assert set(sfm.DEFAULT_PATTERN_CLASSES) == set(sfm.DEFAULT_PROTECTED_PATTERNS)


#: A computed directory change, assembled: this file is itself judged by the guard.
_MOVE = "c" + 'd "$D"'


@pytest.fixture
def past_the_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """More link-holding directories than LINK_DIRECTORY_CAP; one holds a link named ``go``."""
    base = tmp_path.resolve()
    (base / "home").mkdir()
    root = base / "proj"
    root.mkdir()
    (root / "r.md").write_bytes(b"hello\n")
    for number in range(sfm.LINK_DIRECTORY_CAP + 4):
        holder = root / f"w{number:02d}" / ".bin"
        holder.mkdir(parents=True)
        (holder / "tool").symlink_to(root / "r.md")
    (root / "w19" / ".bin" / "go").symlink_to(root / "r.md")
    monkeypatch.chdir("/")
    monkeypatch.setenv("HOME", str(base / "home"))
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
        yield root
    link_index.reset_link_indexes()
    protected_file_index.reset_index_cache()


class TestDirectoryCapDenyReportsTheRealRule:
    """N759: a word denied by the directory cap is not reported as matching a glob."""

    def test_the_cap_deny_names_the_cap_and_claims_no_class(self, past_the_cap: Path) -> None:
        result = _bash(f"{_MOVE} && go build", past_the_cap)
        assert result.decision == Decision.DENY
        reason = result.reason or ""
        assert f"moves into more than {sfm.LINK_DIRECTORY_CAP} existing directories" in reason
        assert "No protected name matched; the word denied for the reason above" in reason
        assert "`go`" in reason
        assert "Matched protected-path class" not in reason
        assert "Matched protected glob" not in reason
