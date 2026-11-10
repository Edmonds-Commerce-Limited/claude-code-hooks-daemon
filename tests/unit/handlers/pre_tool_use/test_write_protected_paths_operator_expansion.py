"""write_protected_paths: an operator-form `${...}` operand is judged like `$NAME` (Plan 00478).

Task 2.2f review, Critical 1 and Important 2. The shared word scanner ended the
word stream at an operator expansion (`${PWD:-.}`, `${HOME#x}`, `${x:+a}`), so
every verb lost that operand and every word after it. The scanner now reads a
brace-balanced `${...}` as part of the current word, an unresolved expansion
exactly like `$PWD`, so each verb judges `${PWD:-.}/protected/x` the way it
judges `$PWD/protected/x`, and a literal protected operand after it is seen.
"""

from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.write_protected_paths import (
    WriteProtectedPathsHandler,
)
from claude_code_hooks_daemon.handlers.registry import apply_handler_options

_LISTED = ["protected/**"]

#: Each verb, with ``{op}`` where the operand under test goes.
_VERB_SHAPES = [
    "rm {op}",
    "cp src.txt {op}",
    "mv src.txt {op}",
    "echo hi | tee {op}",
    "echo hi > {op}",
    "truncate -s0 {op}",
    "sed -i s/a/b/ {op}",
    "awk '{{print > FILENAME}}' {op}",
]

#: Operator forms, each paired with the plain-parameter form it must match.
_OPERATOR_FORMS = [
    ("${PWD:-.}/protected/x", "$PWD/protected/x"),
    ('"${PWD:-.}"/protected/x', '"$PWD"/protected/x'),
    ("${HOME#x}/protected/x", "$HOME/protected/x"),
    ("${x:+a}/protected/x", "$x/protected/x"),
]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / ".claude" / "ccy").mkdir(parents=True)
    (tmp_path / "protected").mkdir()
    return tmp_path


@pytest.fixture
def guard(root: Path) -> WriteProtectedPathsHandler:
    handler = WriteProtectedPathsHandler(project_root=root)
    apply_handler_options(handler, {"paths": _LISTED})
    return handler


def _bash(root: Path, command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(root)}


def _verdict(guard: WriteProtectedPathsHandler, root: Path, command: str) -> str:
    event = _bash(root, command)
    if not guard.matches(event):
        return "nomatch"
    return guard.handle(event).decision.value


class TestAnOperatorOperandIsJudgedLikeAPlainParameter:
    """Consistency is the bar: the operator form gets the `$NAME` form's verdict."""

    @pytest.mark.parametrize("shape", _VERB_SHAPES)
    @pytest.mark.parametrize(("operator_form", "plain_form"), _OPERATOR_FORMS)
    def test_same_verdict_as_the_plain_parameter(
        self,
        guard: WriteProtectedPathsHandler,
        root: Path,
        shape: str,
        operator_form: str,
        plain_form: str,
    ) -> None:
        expected = _verdict(guard, root, shape.format(op=plain_form))
        actual = _verdict(guard, root, shape.format(op=operator_form))
        assert actual == expected, shape.format(op=operator_form)

    @pytest.mark.parametrize("shape", _VERB_SHAPES)
    def test_the_operator_form_under_the_listed_glob_denies(
        self, guard: WriteProtectedPathsHandler, root: Path, shape: str
    ) -> None:
        """The literal `/protected/x` part names the listed directory."""
        assert _verdict(guard, root, shape.format(op="${PWD:-.}/protected/x")) == "deny"


class TestALiteralProtectedOperandAfterAnOperatorOperand:
    """Critical 1: a later literal protected operand is seen and judged."""

    @pytest.mark.parametrize(
        "command",
        [
            "awk '{print > FILENAME}' \"${IN:-a.txt}\" protected/x",
            "awk '{print > FILENAME}' ${IN:-a.txt} protected/x",
            "awk '{print > FILENAME}' ${IN:-a.txt} \"$PWD\"/protected/x",
            "awk '{print > FILENAME}' \"${PWD:-.}\" ./protected/x",
            "awk '{print > FILENAME}' \"${IN:-a.txt}\" ./protected/x",
        ],
    )
    def test_denies(self, guard: WriteProtectedPathsHandler, root: Path, command: str) -> None:
        assert _verdict(guard, root, command) == "deny"

    def test_a_decoy_echo_of_the_same_text_does_not_hide_the_real_command(
        self, guard: WriteProtectedPathsHandler, root: Path
    ) -> None:
        command = "echo awk '{print > FILENAME}' x; awk '{print > FILENAME}' ${PWD:-.}/protected/x"
        assert _verdict(guard, root, command) == "deny"

    def test_an_operator_operand_elsewhere_stays_allowed(
        self, guard: WriteProtectedPathsHandler, root: Path
    ) -> None:
        command = "awk '{print > FILENAME}' ${IN:-a.txt} ${PWD:-.}/other/y"
        assert _verdict(guard, root, command) != "deny"
