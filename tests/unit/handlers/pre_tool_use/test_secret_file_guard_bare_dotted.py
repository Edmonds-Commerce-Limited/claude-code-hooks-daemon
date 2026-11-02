"""A bare dotted word that is not a path is not a mention of a protected file.

Issues #145 (a dotted setting key used as a positional argument) and #143 (a
dotted module path inside a Python string literal).
Option (b): a token counts only when it is path-like, names an existing or
indexed file, or is the operand of a file-opening command or call. Every
true-positive shape stays denied, and each has a test here.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from tests.indexed_project import index_project

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use import secret_file_guard as guard_module
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import protected_file_index

# Assembled so this file never spells a protected name itself.
_SUFFIX = "sec" + "ret"
_REAL = f"app.{_SUFFIX}"
_GONE = f"gone.{_SUFFIX}"
_KEY = f"vpn.{_SUFFIX}s"
_MODULE = f"pkg.{_SUFFIX}_file_guard"
_TARGET = f"{_MODULE}.thing"


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Path]:
    """A project root holding one real protected file at its top level."""
    root = tmp_path / "project"
    root.mkdir()
    (root / _REAL).write_bytes(b"not-a-real-secret\n")
    (root / "conf").mkdir()
    protected_file_index.reset_index_cache()
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        index_project(root, SecretFileGuardHandler()._patterns())
        yield root
    protected_file_index.reset_index_cache()


def _decide(root: Path, tool_name: str, tool_input: dict[str, Any]) -> Decision:
    hook_input: dict[str, Any] = {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "cwd": str(root),
    }
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


def _bash(root: Path, command: str) -> Decision:
    return _decide(root, "Bash", {"command": command})


def _write(root: Path, name: str, content: str) -> Decision:
    return _decide(root, "Write", {"file_path": str(root / name), "content": content})


class TestBashSettingKeyIsAllowed:
    """#145: a bare dotted word handed to a command that does not open files."""

    @pytest.mark.parametrize(
        "command",
        [
            f"nmcli connection modify office {_KEY} 'x'",
            f"nmcli connection modify office {_KEY}",
            f"nmcli -s connection show office | grep {_KEY}",
            f'nmcli connection modify office "{_KEY}" x',
            f"git config remote.origin.{_SUFFIX}s value",
            f"echo {_KEY}",
            f"echo 'set {_KEY} first'",
        ],
    )
    def test_a_setting_key_naming_no_file_is_allowed(self, project: Path, command: str) -> None:
        assert _bash(project, command) == Decision.ALLOW

    def test_a_shell_script_carrying_the_setting_key_is_allowed(self, project: Path) -> None:
        content = f"#!/bin/bash\nnmcli connection modify office {_KEY} 'x'\n"
        assert _write(project, "setup.sh", content) == Decision.ALLOW


class TestBashRealFileShapesStayDenied:
    """The owner's condition: every shape that can reach a file still denies."""

    @pytest.mark.parametrize(
        "command",
        [
            f"cat {_REAL}",
            f"echo {_REAL}",
            f"nmcli connection modify office {_REAL}",
            f"cat {_GONE}",
            f"less {_GONE}",
            f"more {_GONE}",
            f"head {_GONE}",
            f"tail {_GONE}",
            f"cp {_GONE} /tmp/out",
            f"cp /tmp/in {_GONE}",
            f"mv {_GONE} /tmp/out",
            f"source {_GONE}",
            f". {_GONE}",
            f"bash {_GONE}",
            f"python3 {_GONE}",
            f"grep x {_GONE}",
            f"awk 1 {_GONE}",
            f"sudo cat {_GONE}",
            f"env cat {_GONE}",
            f"xargs cat {_GONE}",
            f"echo x > {_GONE}",
            f"echo x >> {_GONE}",
            f"cat < {_GONE}",
            f"cat <{_GONE}",
            f"cat >{_GONE}",
            f"true && cat {_GONE}",
            f"echo hi; cat {_GONE}",
            f"echo hi | cat {_GONE}",
            f"cat {_GONE} {_KEY}",
            f"$(cat {_GONE})",
            f"echo `cat {_GONE}`",
            f"bash -c 'cat {_GONE}'",
            f"python3 -c \"open('{_GONE}')\"",
            f"somecmd --file={_GONE}",
            f"git show HEAD:{_GONE}",
            f"scp host:{_GONE} .",
            f"{_GONE}",
        ],
    )
    def test_file_opening_and_embedded_shapes_deny(self, project: Path, command: str) -> None:
        assert _bash(project, command) == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            f"cat ./{_GONE}",
            f"cat conf/{_GONE}",
            f"cat ~/x.{_SUFFIX}",
            f"nmcli connection modify office ./{_GONE}",
            f"nmcli connection modify office conf/{_GONE}",
            f"nmcli connection modify office ~/{_GONE}",
            f"nmcli connection modify office $HOME/{_GONE}",
            f"nmcli connection modify office $D/{_GONE}",
            f"nmcli connection modify office $X.{_SUFFIX}",
            f"nmcli connection modify office .{_SUFFIX}",
            f"nmcli connection modify office *.{_SUFFIX}",
            f"nmcli connection modify office app.{_SUFFIX[:3]}*",
            f"nmcli connection modify office app.{{{_SUFFIX},x}}",
            f"ls *.{_SUFFIX}",
        ],
    )
    def test_path_variable_and_glob_shapes_deny(self, project: Path, command: str) -> None:
        assert _bash(project, command) == Decision.DENY

    def test_a_relative_bare_name_of_an_existing_file_denies_for_any_command(
        self, project: Path
    ) -> None:
        assert _bash(project, f"somecmd {_REAL}") == Decision.DENY

    def test_a_name_in_the_protected_file_index_denies(self, project: Path) -> None:
        (project / "conf" / _GONE).write_bytes(b"x\n")
        index_project(project, SecretFileGuardHandler()._patterns())
        hook_input: dict[str, Any] = {
            "tool_name": "Bash",
            "tool_input": {"command": f"somecmd {_GONE}"},
            "cwd": str(project),
        }
        assert SecretFileGuardHandler().matches(hook_input)

    def test_a_name_that_exists_after_a_cd_denies(self, project: Path) -> None:
        (project / "conf" / _GONE).write_bytes(b"x\n")
        assert _bash(project, f"cd conf && somecmd {_GONE}") == Decision.DENY


class TestPythonModuleStringsAreAllowed:
    """#143: a dotted module path handed to a module-name API."""

    @pytest.mark.parametrize(
        "line",
        [
            f'importlib.import_module("{_MODULE}")',
            f"importlib.import_module('{_MODULE}')",
            f'module = import_module("{_MODULE}")',
            f'importlib.util.find_spec("{_MODULE}")',
            f'runpy.run_module("{_MODULE}")',
            f'mock.patch("{_TARGET}")',
            f'patch("{_TARGET}", autospec=True)',
            f'with patch("{_TARGET}"):',
            f'logger = logging.getLogger("{_MODULE}")',
            f"logger = logging.getLogger('{_MODULE}')",
        ],
    )
    def test_a_module_name_api_first_argument_is_allowed(self, project: Path, line: str) -> None:
        assert _write(project, "helper.py", f"import importlib\n{line}\n") == Decision.ALLOW

    def test_an_attribute_chain_in_code_is_allowed(self, project: Path) -> None:
        content = f"value = settings.{_SUFFIX}s\nprint(config.{_SUFFIX}_store.get('k'))\n"
        assert _write(project, "helper.py", content) == Decision.ALLOW


class TestPythonRealFileShapesStayDenied:
    """N557: a string that can name a file denies unless a module API receives it."""

    @pytest.mark.parametrize(
        "line",
        [
            f'open("{_GONE}")',
            f"open('{_GONE}')",
            f'Path("{_GONE}")',
            f'Path("{_GONE}").read_text()',
            f'data = Path("{_GONE}").read_bytes()',
            f'os.path.join(base, "{_GONE}")',
            f'other_call("{_MODULE}")',
            f'open("{_MODULE}")',
            f'Path("{_MODULE}").read_text()',
            f'KEY = "{_MODULE}"',
            f'patch.object(target, "{_GONE}")',
            f'importlib.import_module("{_MODULE}", "{_GONE}")',
            f'open("conf/{_GONE}")',
            f'open("./{_GONE}")',
            f'open(os.environ["HOME"] + "/{_GONE}")',
            f'open(f"{{base}}/{_GONE}")',
        ],
    )
    def test_a_file_shaped_string_denies(self, project: Path, line: str) -> None:
        assert _write(project, "helper.py", f"{line}\n") == Decision.DENY

    @pytest.mark.parametrize("name", [_MODULE, _REAL])
    def test_a_module_shaped_string_that_names_a_real_file_denies(
        self, project: Path, name: str
    ) -> None:
        """N557's warning: module shape is not evidence, the file existing is."""
        (project / name).write_bytes(b"x\n")
        content = f'importlib.import_module("{name}")\n'
        assert _write(project, "helper.py", content) == Decision.DENY
