"""Older holes in the secret guard's search-option reading (Plan 00618 Task 2.1).

``deep/`` holds an indexed protected file; ``sub/`` holds none; ``_ABSENT`` is a
name only a protected glob matches. Every shape here is judged by the guard
end to end, with the twins that must stay allowed beside the ones that must deny.
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
_PROTECTED = f"demo.{_SUFFIX}"
_ABSENT = f"absent.{_SUFFIX}"


@pytest.fixture()
def project(tmp_path: Path) -> Iterator[Path]:
    """A project whose root and ``deep`` hold a protected file; ``sub`` holds none."""
    root = tmp_path / "project"
    root.mkdir()
    (root / _PROTECTED).write_bytes(b"not-a-real-secret\n")
    (root / "sub").mkdir()
    (root / "sub" / "plain.txt").write_bytes(b"hello\n")
    (root / "deep").mkdir()
    (root / "deep" / f"key.{_SUFFIX}").write_bytes(b"not-a-real-secret\n")
    protected_file_index.reset_index_cache()
    with patch.object(guard_module, "resolve_project_root", return_value=str(root)):
        index_project(root, SecretFileGuardHandler()._patterns())
        yield root
    protected_file_index.reset_index_cache()


def _verdict(root: Path, command: str, cwd: Path | None = None) -> Decision:
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd or root),
    }
    handler = SecretFileGuardHandler()
    if not handler.matches(hook_input):
        return Decision.ALLOW
    return handler.handle(hook_input).decision


class TestUnit1SearchOptionGrammar:
    """scan_options fails closed: a pattern option it cannot place never hides a directory."""

    @pytest.mark.parametrize(
        "command",
        [
            # RED: GNU long-option abbreviations of --regexp / --file.
            "grep -r --regex=. deep /dev/null",
            "command grep -r --regex=. deep /dev/null",
            "/usr/bin/grep -r --regex=. deep /dev/null",
            "egrep -r --rege=. deep /dev/null",
            "grep -r --fi=pats deep /dev/null",
            "grep -r --reg=zz deep sub",
            # RED: ugrep --and supplies the pattern.
            "grep -r --and=. deep sub",
            "grep -r --and=. deep /dev/null",
            # RED: -T / separate --color take no value in GNU grep and ugrep.
            "grep -rT x deep sub",
            "grep -r --color x deep sub",
            # REGRESSION (already denied): exact spellings.
            "grep -r --regexp=zz deep sub",
            "grep -r -e zz deep sub",
            "grep -r zz deep",
            "grep -r zz sub deep",
        ],
    )
    def test_directory_holding_a_protected_file_is_denied(
        self, project: Path, command: str
    ) -> None:
        assert _verdict(project, command) is Decision.DENY

    def test_valueless_misread_with_relative_root_from_a_subdirectory(self, project: Path) -> None:
        assert _verdict(project, "grep -rT x ../deep", cwd=project / "sub") is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "grep -r zz sub",
            "grep -rn zz sub",
            "grep -r --line-number zz sub",
            "grep -r --line-n zz sub",
            "rg -n zz sub",
            "rg --color never zz sub",
            "grep -rT x sub",
            "grep -r --color x sub",
            "grep -r -e zz sub",
            "grep -r --regexp=zz sub",
            "grep -r --regex=zz sub",
            "grep -r --and=zz sub",
            f"grep -r {_ABSENT} sub",
        ],
    )
    def test_twin_over_a_clean_directory_stays_allowed(self, project: Path, command: str) -> None:
        assert _verdict(project, command) is Decision.ALLOW


class TestUnit2BareNameAsPatternOrFile:
    """A bare unindexed name after grep is a file unless positively the pattern operand.

    The whole segment is judged, not the words before the name: a pattern option
    given after the name, in a cluster, abbreviated, or by ugrep, leaves the name a file.
    """

    @pytest.mark.parametrize(
        "template",
        [
            "grep -ezz {A}",
            "grep --regexp=zz {A}",
            "grep --reg=zz {A}",
            "grep -iezz {A}",
            "grep -fzz {A}",
            "grep --and=zz {A}",
            "rg -ezz {A}",
            "egrep -ezz {A}",
            "ag -ezz {A}",
            "grep {A} -e zz",
            "grep {A} -ezz",
            "rg {A} -ezz",
            "ugrep zz {A}",
            "ug zz {A}",
            "grep -- -e {A}",
            "grep zz {A}",
            "grep -e zz {A}",
            "cat {A}",
        ],
    )
    def test_name_that_is_a_file_is_denied(self, project: Path, template: str) -> None:
        assert _verdict(project, template.format(A=_ABSENT)) is Decision.DENY

    @pytest.mark.parametrize(
        "template",
        [
            "grep zz sub/plain.txt",
            "grep -e zz sub/plain.txt",
            "grep {A} sub/plain.txt",
            "grep -n {A} sub/plain.txt",
            "grep -i {A} sub/plain.txt",
            "rg {A} sub",
            "rg -n {A} sub",
            "ugrep {A} sub/plain.txt",
        ],
    )
    def test_pattern_spelling_the_name_with_no_file_open_stays_allowed(
        self, project: Path, template: str
    ) -> None:
        assert _verdict(project, template.format(A=_ABSENT)) is Decision.ALLOW


class TestUnit3RipgrepConfigPath:
    """RIPGREP_CONFIG_PATH names a file that may hold ``--regexp=...``: no rg operand is the pattern."""

    @pytest.mark.parametrize(
        "command",
        [
            "RIPGREP_CONFIG_PATH=cfg rg deep sub -g '*'",
            "export RIPGREP_CONFIG_PATH=cfg; rg deep sub -g '*'",
            "export RIPGREP_CONFIG_PATH=cfg && rg deep sub",
            "RIPGREP_CONFIG_PATH=cfg rg deep sub",
            "env RIPGREP_CONFIG_PATH=cfg rg deep sub",
            f"env RIPGREP_CONFIG_PATH=cfg rg zz {_ABSENT}",
            f"RIPGREP_CONFIG_PATH=cfg rg {_ABSENT}",
            "declare -x RIPGREP_CONFIG_PATH=cfg; rg deep sub",
            "RIPGREP_CONFIG_PATH=cfg; rg deep sub",
        ],
    )
    def test_first_operand_is_judged_as_a_path(self, project: Path, command: str) -> None:
        assert _verdict(project, command) is Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "rg zz sub",
            "rg deep sub -g '*'",
            "RIPGREP_CONFIG_PATH=cfg rg zz sub",
            "RIPGREP_CONFIG_PATH=cfg grep -r zz sub",
            "RIPGREP_CONFIG_PATH=cfg rg -n zz sub",
            f"rg {_ABSENT} sub",
        ],
    )
    def test_twin_over_clean_paths_stays_allowed(self, project: Path, command: str) -> None:
        assert _verdict(project, command) is Decision.ALLOW


class TestUnit5CommandWordIndirection:
    """A command word the text scan cannot name (eval, a substitution) may open the bare name."""

    @pytest.mark.parametrize(
        "template",
        [
            "eval cat {A}",
            "eval git blame -S {A} f",
            "eval grep zz {A}",
            "$(echo cat) {A}",
            "git $(echo blame) -S {A} f",
            "sudo $(echo cat) {A}",
            "grep $(echo x) {A}",
            "x=1 $(echo cat) {A}",
            "true && $(echo cat) {A}",
            "$(echo $(echo cat)) {A}",
            # An assignment in front is no command word (found while fixing this unit).
            "FOO=1 cat {A}",
            'FOO="a b" cat {A}',
            "FOO=1 BAR=2 grep zz {A}",
            # Already denied: the backtick form leaves no command word.
            "`echo cat` {A}",
            "cat {A}",
        ],
    )
    def test_indirect_command_with_the_name_is_denied(self, project: Path, template: str) -> None:
        assert _verdict(project, template.format(A=_ABSENT)) is Decision.DENY

    @pytest.mark.parametrize(
        "template",
        [
            "echo $(date) {A}",
            "echo {A}",
            "x=$(echo hi); echo {A}",
            "echo $(echo hi) $(echo there) {A}",
            "grep {A} sub/plain.txt",
            "git log -S {A}",
            "echo ')' {A}",
            "FOO=1 echo {A}",
            "FOO=1 grep {A} sub/plain.txt",
        ],
    )
    def test_twin_where_the_name_is_an_argument_of_a_plain_command_stays_allowed(
        self, project: Path, template: str
    ) -> None:
        assert _verdict(project, template.format(A=_ABSENT)) is Decision.ALLOW
