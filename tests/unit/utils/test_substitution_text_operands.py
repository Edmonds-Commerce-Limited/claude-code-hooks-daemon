"""A command inside a substitution is judged like the same command at top level
(ledger 00474 N291).

N269 made a quoted word received by a pure text consumer (a grep/rg/awk pattern,
echo/printf arguments) a literal, never a glob. That exemption keyed on the
command word of each separator-delimited segment, and a command substitution, a
backtick pair or a process substitution opens no segment, so an assignment of a
grep substitution named the assignment as its command and the regex was judged
as a glob.

Every reader of a protected file stays denied inside a substitution exactly as
at top level. Protected names are assembled here so this file never spells one
whole. The process cwd is forced to ``/`` as the live daemon's is. Unterminated
substitutions are assembled from pieces so this file stays readable to the guard.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.chain import HandlerChain
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils.shell_segmentation import (
    UnplaceableSubstitutionError,
    substitution_inner_spans,
)

_PROTECTED = "." + "vault" + "-pass"
_PREFIX = _PROTECTED[:-2]  # a truncation that globs to the protected name

_REGEX = r"^tests/.*test_.*\.py$"

_SUBST_OPEN = "$" + "("
_TICK = chr(96)
_PROC_OPEN = "<" + "("

#: Ways to put a command inside a substitution.
_WRAPPERS = {
    "assignment": 'x=$({inner}); echo "$x"',
    "bare substitution": "echo $({inner})",
    "double-quoted substitution": 'echo "$({inner})"',
    "backticks": "x=" + _TICK + "{inner}" + _TICK + '; echo "$x"',
    "process substitution": "diff <({inner}) other.txt",
    "nested substitution": 'x=$(echo $({inner})); echo "$x"',
    "after a separator inside": 'x=$(cd d; {inner}); echo "$x"',
    "piped inside": 'x=$(cat f | {inner}); echo "$x"',
}


@pytest.fixture(autouse=True)
def _daemon_like_process(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    reset_data_layer()
    monkeypatch.chdir("/")
    yield
    reset_data_layer()


def _verdict(command: str, cwd: Path) -> tuple[Decision, str]:
    chain = HandlerChain()
    chain.add(SecretFileGuardHandler())
    hook_input: dict[str, Any] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    result = chain.execute(hook_input, strict_mode=False)
    return result.result.decision, result.result.reason or ""


def _inner_texts(text: str) -> list[str]:
    return [text[start:end] for start, end in substitution_inner_spans(text)]


_TEXT_CONSUMERS = {
    "double-quoted grep regex": f'grep "{_REGEX}" untracked/scratch/list.txt',
    "single-quoted grep regex": f"grep '{_REGEX}' untracked/scratch/list.txt",
    "grep -E alternation": 'grep -E "a|^tests/.*py:[0-9]+" untracked/scratch/list.txt',
}

#: A substitution's OUTPUT becomes words of the outer command, and an unquoted
#: result is glob-expanded, so a consumer that echoes its operand must not be
#: relaxed inside one. The protected prefix is a truncation that globs to it.
_ECHOING_CONSUMERS = {
    "echo": f"echo '{_PREFIX}*'",
    "printf": f"printf '%s' '{_PREFIX}*'",
    "echo -n": f"echo -n '{_PREFIX}*'",
    "rg replacement": f"rg -r '{_PREFIX}*' x f",
    "awk program literal": f"awk 'BEGIN {{ print \"{_PREFIX}*\" }}'",
}
_OUTER_CONSUMERS = {
    "cat of a bare substitution": "cat $({inner})",
    "cat of a double-quoted substitution": 'cat "$({inner})"',
    "cat of backticks": "cat " + _TICK + "{inner}" + _TICK,
    "cat of an assigned result": "x=$({inner}); cat $x",
    "cat of a result assigned after a separator": "x=$(true; {inner}); cat $x",
    "cat of a process substitution": "cat <({inner})",
    "cat of a nested substitution": "cat $(echo $({inner}))",
}


class TestAnEchoingConsumerIsNotRelaxedInsideASubstitution:
    @pytest.mark.parametrize("outer", list(_OUTER_CONSUMERS.values()), ids=list(_OUTER_CONSUMERS))
    @pytest.mark.parametrize(
        "inner", list(_ECHOING_CONSUMERS.values()), ids=list(_ECHOING_CONSUMERS)
    )
    def test_is_denied(self, outer: str, inner: str, tmp_path: Path) -> None:
        (tmp_path / _PROTECTED).write_text("x")
        decision, _ = _verdict(outer.format(inner=inner), tmp_path)
        assert decision == Decision.DENY

    @pytest.mark.parametrize(
        "inner", list(_ECHOING_CONSUMERS.values()), ids=list(_ECHOING_CONSUMERS)
    )
    def test_the_top_level_text_operand_is_still_allowed(self, inner: str, tmp_path: Path) -> None:
        """N269 on main: the same command outside a substitution prints its text."""
        (tmp_path / _PROTECTED).write_text("x")
        decision, reason = _verdict(inner, tmp_path)
        assert decision != Decision.DENY, reason


class TestTextConsumerInsideASubstitutionIsAllowed:
    def test_the_bare_command_is_allowed(self, tmp_path: Path) -> None:
        decision, reason = _verdict(f'grep "{_REGEX}" untracked/scratch/list.txt', tmp_path)
        assert decision != Decision.DENY, reason

    @pytest.mark.parametrize("wrapper", list(_WRAPPERS.values()), ids=list(_WRAPPERS))
    @pytest.mark.parametrize("inner", list(_TEXT_CONSUMERS.values()), ids=list(_TEXT_CONSUMERS))
    def test_is_allowed(self, wrapper: str, inner: str, tmp_path: Path) -> None:
        decision, reason = _verdict(wrapper.format(inner=inner), tmp_path)
        assert decision != Decision.DENY, reason

    def test_the_n291_reproduction_is_allowed(self, tmp_path: Path) -> None:
        command = f"x=$(grep '{_REGEX}' untracked/scratch/p479-py.txt); echo \"$x\""
        decision, reason = _verdict(command, tmp_path)
        assert decision != Decision.DENY, reason


_READERS = {
    "cat of the file": f"cat {_PROTECTED}",
    "cat of the quoted file": f"cat '{_PROTECTED}'",
    "grep over the file": f"grep foo {_PROTECTED}",
    "grep with a quoted pattern over the file": f'grep "pat" {_PROTECTED}',
    "grep -f the file": f"grep -f {_PROTECTED} somefile",
    "grep --file= the file": f"grep --file={_PROTECTED} somefile",
    "rg --pre": f"rg --pre cat x {_PROTECTED}",
    "rg --ignore-file": f"rg --ignore-file {_PROTECTED} x .",
    "awk -f the file": f"awk -f {_PROTECTED}",
    "awk over the file": f"awk '{{print}}' {_PROTECTED}",
    "unquoted glob": f"cat {_PREFIX}*",
    "grep over an unquoted glob": f"grep x {_PREFIX}*",
    "grep over a quoted prefix with a glob tail": f"grep x '{_PREFIX}'*",
    "find -name glob": f"find . -name '{_PREFIX}*'",
    "grep --include glob": f"grep -r --include '{_PREFIX}*' x .",
    "rg -g glob": f"rg -g '{_PREFIX}*' x .",
    "python glob": f"python3 -c \"import glob; print(glob.glob('{_PREFIX}*'))\"",
    "bash -c glob": f"bash -c 'cat {_PREFIX}*'",
}


class TestEveryReaderStaysDeniedAtTopLevelAndInsideASubstitution:
    @pytest.mark.parametrize("inner", list(_READERS.values()), ids=list(_READERS))
    def test_top_level_is_denied(self, inner: str, tmp_path: Path) -> None:
        (tmp_path / _PROTECTED).write_text("x")
        decision, _ = _verdict(inner, tmp_path)
        assert decision == Decision.DENY

    @pytest.mark.parametrize("wrapper", list(_WRAPPERS.values()), ids=list(_WRAPPERS))
    @pytest.mark.parametrize("inner", list(_READERS.values()), ids=list(_READERS))
    def test_inside_a_substitution_is_denied(
        self, wrapper: str, inner: str, tmp_path: Path
    ) -> None:
        (tmp_path / _PROTECTED).write_text("x")
        decision, _ = _verdict(wrapper.format(inner=inner), tmp_path)
        assert decision == Decision.DENY


class TestTheExemptionDoesNotLeakOutOfTheSubstitution:
    """Only words the inner consumer receives are relaxed."""

    @pytest.mark.parametrize(
        "command",
        [
            f"x=$(grep 'a' f) cat {_PREFIX}*",
            f"x=$(grep 'a' f); cat {_PREFIX}*",
            f"find $(grep 'a' f) -name '{_PREFIX}*'",
            f"echo $(grep 'a' f) && cat {_PROTECTED}",
            "x=" + _TICK + "grep 'a' f" + _TICK + f" cat '{_PREFIX}'*",
            f"python3 -c 'print(\"$(grep a f)\")'; cat {_PROTECTED}",
        ],
    )
    def test_is_denied(self, command: str, tmp_path: Path) -> None:
        (tmp_path / _PROTECTED).write_text("x")
        decision, _ = _verdict(command, tmp_path)
        assert decision == Decision.DENY

    def test_a_substitution_inside_single_quotes_is_literal_text(self, tmp_path: Path) -> None:
        """``find`` globs its own -name value; a grep substitution spelled inside
        single quotes is not a command, so nothing there may be relaxed."""
        (tmp_path / _PROTECTED).write_text("x")
        command = f"find . -name '$(grep {_PREFIX}* f)'"
        decision, _ = _verdict(command, tmp_path)
        assert decision == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            "x=" + _SUBST_OPEN + f"grep '{_REGEX}' f",
            "x=" + _TICK + f"grep '{_REGEX}' f",
            "diff " + _PROC_OPEN + f"grep '{_REGEX}' f",
            "x=" + _SUBST_OPEN + f'grep "{_REGEX}" f',
        ],
    )
    def test_an_unterminated_substitution_keeps_being_judged_as_before(
        self, command: str, tmp_path: Path
    ) -> None:
        """A span the scanner cannot close is not relaxed (fail closed)."""
        decision, _ = _verdict(command, tmp_path)
        assert decision == Decision.DENY


class TestSubstitutionInnerSpans:
    def test_dollar_paren_span_excludes_the_delimiters(self) -> None:
        assert _inner_texts("x=$(grep a f); echo") == ["grep a f"]

    def test_backtick_span(self) -> None:
        assert _inner_texts("x=" + _TICK + "grep a f" + _TICK + "; echo") == ["grep a f"]

    def test_process_substitution_spans(self) -> None:
        assert _inner_texts("diff <(a b) >(c d)") == ["a b", "c d"]

    def test_nested_spans_are_all_reported(self) -> None:
        assert sorted(_inner_texts("x=$(a $(b c) d)")) == ["a $(b c) d", "b c"]

    def test_a_close_paren_inside_quotes_does_not_end_the_span(self) -> None:
        assert _inner_texts("x=$(grep ')' f \"(\")") == ["grep ')' f \"(\""]

    def test_an_opener_inside_single_quotes_is_not_one(self) -> None:
        assert _inner_texts("echo '$(x)'") == []

    def test_an_opener_inside_double_quotes_is_one(self) -> None:
        assert _inner_texts('echo "$(x y)"') == ["x y"]

    def test_a_subshell_group_inside_does_not_end_the_span(self) -> None:
        assert _inner_texts("x=$( (a b) c )") == [" (a b) c "]

    def test_an_escaped_opener_is_not_one(self) -> None:
        assert _inner_texts("echo \\$(x)") == []

    def test_text_with_no_substitution_has_no_spans(self) -> None:
        assert _inner_texts("grep a f") == []

    @pytest.mark.parametrize(
        "text",
        [
            "x=" + _SUBST_OPEN + "grep a f",
            "x=" + _TICK + "grep a f",
            "diff " + _PROC_OPEN + "a b",
            "echo 'unterminated",
            'echo "unterminated',
            'echo "' + _SUBST_OPEN + "a b",
        ],
    )
    def test_an_unterminated_construct_is_unplaceable(self, text: str) -> None:
        with pytest.raises(UnplaceableSubstitutionError):
            substitution_inner_spans(text)

    def test_excessive_nesting_is_unplaceable(self) -> None:
        text = _SUBST_OPEN * 200 + "x" + ")" * 200
        with pytest.raises(UnplaceableSubstitutionError):
            substitution_inner_spans(text)
