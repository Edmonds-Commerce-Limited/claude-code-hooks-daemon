"""Quoted text bash never globs is not treated as a glob by the secret guard
(ledger 00474 N269 and N256, issue #66 step 2).

The guard's glob heuristics (edge overlap, DP intersection, filesystem walk)
exist for a word bash will pathname-expand. A glob character inside quotes, or in
a quoted-delimiter heredoc body, is literal to bash, so where that text is an
operand of a pure text consumer (a grep/rg/awk pattern, echo/printf arguments, a
gh body, a heredoc fed to cat) it must not be judged as a glob. A program that
globs its own quoted argument, and every unquoted glob, must still be judged.

Protected names are assembled here so this file never spells one whole. The
process cwd is forced to ``/`` as the live daemon's is.
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
from claude_code_hooks_daemon.utils.shell_segmentation import shell_word_spans

_PROTECTED = "." + "vault" + "-pass"
_PREFIX = _PROTECTED[:-2]  # a truncation that globs to the protected name


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


_TEXT_OPERAND_COMMANDS = {
    "double-quoted grep -E alternation with a regex tail": (
        'grep -a -n -E "TimeoutExpired|timeout=|daemon_teardown|stop_verified|'
        'upgrade_version|^tests/.*py:[0-9]+" untracked/scratch/qa-n268.txt'
    ),
    "double-quoted grep -E with repetition counts": (
        'grep -a -n -E "FAILED|^.{0,40}_{5,} .* _{5,}" untracked/scratch/qa.txt'
    ),
    "double-quoted grep -o regex": 'grep -o ".*Error.*" somefile',
    "single-quoted grep -E character class": r"grep -E '[a-z_/]+\.py' foo.txt",
    "single-quoted grep -rn regex": r"grep -rn -E 'x[a-z_/]+\.py' src",
    "grep -e value": r"grep -e '.*\.py:[0-9]+' log.txt",
    "rg pattern": r"rg -n '^src/.*py:[0-9]+' log.txt",
    "issue 70 leading dot-star": r"grep '.*ErrorCount' f",
    "issue 70 leading dot-star version": r"grep '.*v3' f",
    "issue 70 dot-star then done": r"grep -n '.*v3\.6' CHANGELOG.md && echo done",
    "issue 70 rg dot-star": r"rg '.*Foo' src",
    "escaped dot-star with a character class": r"grep '\.\*[A-Za-z]' f",
    "rg -e escaped dot-star with a character class": r"rg -e '\.\*[A-Za-z]' src",
    "egrep escaped dot-star with a character class": r"egrep '\.\*[A-Za-z]' f",
    "grep -E anchored dot-star": r"grep -E '^\..*pass' f",
    "grep --regexp attached value": r"grep --regexp='\.\*[A-Za-z]' f",
    "grep --regexp separate value": r"grep --regexp '\.\*[A-Za-z]' f",
    "rg --regexp attached value": r"rg --regexp='.*Foo' src",
    "grep -e attached value": r"grep -e'\.\*[A-Za-z]' f",
    "git grep positional pattern": r"git grep -n '\.\*[A-Za-z]' -- src",
    "git grep -e pattern with an excluding pathspec": (
        r"git grep -n -e '\.\*[A-Za-z]' -- src ':!tests/fixtures/cyber-flag'"
    ),
    "git grep dot-star": r"git grep '.*ErrorCount' -- src",
    "git grep --regexp attached": r"git grep --regexp='.*Foo' -- src",
    "git grep -e attached": r"git grep -e'.*Foo' -- src",
    "git grep --regexp separate": r"git grep --regexp '.*Foo' -- src",
    "git grep after global options": r"git -C src -c color.ui=never grep -n '.*Foo' -- .",
    "git grep after context option value": r"git grep -C 3 '.*Foo' HEAD",
    "awk pattern": r"awk '/^tests\/.*py:[0-9]+/ {print $1}' log.txt",
    "printf with escaped backticks in a double-quoted body": (
        "printf '%s\\n' \"Triage: see (\\`CLAUDE/Plan/00472-model-tier/\\`, "
        '\\`untracked/**/x.md\\`, \\`src/*/*/y.py\\`)" > untracked/scratch/x.md'
    ),
    "echo of a path glob": "echo 'see src/foo/**/bar.py and *.py'",
    "gh comment body": "gh issue comment 66 --body 'fixed in src/**/x.py and tests/*/*/y.py'",
    "ANSI-C echo argument": "echo $'see src/**/x.py and ^tests/.*py:[0-9]+'",
    "gh attached body": "gh pr comment 3 --body='see src/**/x.py and ^tests/.*py:[0-9]+'",
    "quoted heredoc fed to cat": (
        "cat > untracked/scratch/x.md <<'EOF'\n"
        "globs such as src/**/*.py, tests/*/*/x[a-z_/]+.py and ^tests/.*py:[0-9]+\n"
        "EOF"
    ),
}


class TestShellWordSpans:
    def test_spans_are_exact_offsets_of_quote_aware_words(self) -> None:
        text = "grep -E 'a b' \"c d\" e"
        assert [text[start:end] for start, end in shell_word_spans(text)] == [
            "grep",
            "-E",
            "'a b'",
            '"c d"',
            "e",
        ]

    def test_the_stream_stops_at_a_word_a_substitution_hides(self) -> None:
        text = "echo 'a' $(cat x) 'b'"
        assert [text[start:end] for start, end in shell_word_spans(text)] == ["echo", "'a'"]


class TestTextOperandsAreNotJudgedAsGlobs:
    @pytest.mark.parametrize(
        "command", list(_TEXT_OPERAND_COMMANDS.values()), ids=list(_TEXT_OPERAND_COMMANDS)
    )
    def test_is_allowed(self, command: str, tmp_path: Path) -> None:
        decision, reason = _verdict(command, tmp_path)
        assert decision != Decision.DENY, reason

    def test_a_heredoc_truncation_of_a_protected_name_fed_to_cat_is_allowed(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / _PROTECTED).write_text("x")
        command = f"cat > out.md <<'EOF'\nsee {_PREFIX}*\nEOF"
        decision, reason = _verdict(command, tmp_path)
        assert decision != Decision.DENY, reason


class TestWhatStillDenies:
    """The other direction: the relaxation must not open these."""

    @pytest.mark.parametrize(
        "command",
        [
            f"cat '{_PROTECTED}'",
            f'grep x "{_PROTECTED}"',
            f"echo hi; cat '{_PROTECTED}'",
            f"cat <<'EOF' > out.md\nnote\nEOF\ncat '{_PROTECTED}'",
        ],
    )
    def test_a_quoted_word_naming_a_protected_path_is_denied(
        self, command: str, tmp_path: Path
    ) -> None:
        decision, _ = _verdict(command, tmp_path)
        assert decision == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            f"cat {_PREFIX}*",
            f"echo {_PREFIX}*",
            f"grep x {_PREFIX}*",
            f"cat {_PREFIX}'s'*",
            f'cat "{_PREFIX[:-1]}"*',
            f'echo "$(cat {_PREFIX}*)"',
            f"echo 'x' && cat {_PREFIX}*",
        ],
    )
    def test_an_unquoted_glob_is_still_expanded_and_denied(
        self, command: str, tmp_path: Path
    ) -> None:
        (tmp_path / _PROTECTED).write_text("x")
        decision, _ = _verdict(command, tmp_path)
        assert decision == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            f"python3 -c \"import glob; print(glob.glob('{_PREFIX}*'))\"",
            f"python3 -c 'import glob; print(glob.glob(\"{_PREFIX}*\"))'",
            f"bash -c 'cat {_PREFIX}*'",
            f'sh -c "ls {_PREFIX}*"',
            f"awk 'BEGIN {{ system(\"cat {_PREFIX}*\") }}'",
            f"bash <<'EOF'\ncat {_PREFIX}*\nEOF",
            f"cat $(echo {_PREFIX}*)",
        ],
    )
    def test_a_program_that_globs_its_own_quoted_text_is_still_denied(
        self, command: str, tmp_path: Path
    ) -> None:
        (tmp_path / _PROTECTED).write_text("x")
        decision, _ = _verdict(command, tmp_path)
        assert decision == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            f"grep x {_PREFIX}*",
            f"grep '.*x' {_PREFIX}*",
            f"grep --regexp='.*x' {_PREFIX}*",
            f"grep -e '\\.\\*[A-Za-z]' {_PREFIX}*",
            f"rg -e '.*Foo' {_PREFIX}*",
            f"grep x {_PROTECTED}.txt",
            f"grep -n '.*x' {_PROTECTED}",
            f"grep -r x . --include={_PREFIX}*",
            f"git grep x -- '{_PREFIX}*'",
            f"git grep x -- {_PREFIX}*",
            f"git grep x HEAD -- {_PROTECTED}.txt",
            f"git grep '.*x' -- '{_PREFIX}*'",
            f"git grep -e '.*x' -- '{_PREFIX}*'",
            f"git grep -e '.*x' '{_PREFIX}*'",
            f"git grep -n '.*x' HEAD '{_PREFIX}*'",
            f"git -C . grep '.*x' -- '{_PREFIX}*'",
        ],
    )
    def test_a_regex_pattern_does_not_excuse_the_file_operand(
        self, command: str, tmp_path: Path
    ) -> None:
        (tmp_path / _PROTECTED).write_text("x")
        decision, _ = _verdict(command, tmp_path)
        assert decision == Decision.DENY

    @pytest.mark.parametrize(
        "command",
        [
            f"grep -r --include '{_PREFIX}*' x .",
            f"grep -r --include='{_PREFIX}*' x .",
            f"rg -g '{_PREFIX}*' x .",
            f"rg -ng '{_PREFIX}*' x .",
            f"find . -name '{_PREFIX}*'",
        ],
    )
    def test_a_tool_glob_option_value_is_still_denied(self, command: str, tmp_path: Path) -> None:
        (tmp_path / _PROTECTED).write_text("x")
        decision, _ = _verdict(command, tmp_path)
        assert decision == Decision.DENY


_ANSI_C_PROTECTED = "".join(f"\\x{ord(char):02x}" for char in _PROTECTED)

_READS_A_PROTECTED_FILE = {
    "grep -f pattern file": f"grep -f {_PROTECTED} somefile",
    "grep --file= pattern file": f"grep --file={_PROTECTED} somefile",
    "grep --file pattern file": f"grep --file {_PROTECTED} somefile",
    "rg --pre with a protected operand": f"rg --pre cat x {_PROTECTED}",
    "rg --pre and --pre-glob with a protected operand": (
        f"rg --pre cat --pre-glob '*.txt' x {_PROTECTED}"
    ),
    "rg --ignore-file": f"rg --ignore-file {_PROTECTED} x .",
    "grep -e with a protected operand": f'grep -e "pat" {_PROTECTED}',
    "grep -- with a protected operand": f'grep -- "pat" {_PROTECTED}',
    "grep quoted pattern then protected operand": f'grep "pat" {_PROTECTED}',
    "quoted protected prefix with an unquoted glob tail": f"cat '{_PREFIX}'*",
    "double-quoted protected prefix with an unquoted glob tail": f'cat "{_PREFIX}"*',
    "grep over a quoted prefix with an unquoted glob tail": f"grep x '{_PREFIX}'*",
    "echo of a quoted prefix with an unquoted glob tail": f"echo '{_PREFIX}'*",
    "ANSI-C quoted protected name": f"cat $'{_PROTECTED}'",
    "ANSI-C hex-escaped protected name": f"cat $'{_ANSI_C_PROTECTED}'",
    "ANSI-C quoted protected name after a grep pattern": f"grep x $'{_PROTECTED}'",
    "here-string naming the protected file": f"cat <<< {_PROTECTED}",
    "here-string over a cat substitution": f'grep x <<< "$(cat {_PROTECTED})"',
    "env prefix": f"env grep x {_PROTECTED}",
    "command prefix": f"command cat {_PROTECTED}",
    "timeout prefix": f"timeout 5 cat {_PROTECTED}",
    "nice prefix": f"nice cat {_PROTECTED}",
    "full-path grep": f"/usr/bin/grep x {_PROTECTED}",
    "full-path cat": f"/bin/cat {_PROTECTED}",
    "unquoted glob echoed into xargs cat": f"echo {_PREFIX}* | xargs cat",
    "find -name glob with -exec cat": f"find . -name '{_PREFIX}*' -exec cat {{}} +",
    "awk -f program file": f"awk -f {_PROTECTED}",
    "awk getline in its while-loop spelling": (
        f"awk 'BEGIN {{ while ((getline line < \"{_PROTECTED}\") > 0) print line }}'"
    ),
    "awk print with a protected operand": f"awk '{{print}}' {_PROTECTED}",
    "gh --body-file": f"gh issue comment 1 --body-file {_PROTECTED}",
    "gh -F": f"gh issue comment 1 -F {_PROTECTED}",
    "bash heredoc body": f"bash <<'EOF'\ncat {_PROTECTED}\nEOF",
    "sh heredoc body": f"sh <<'EOF'\ncat {_PROTECTED}\nEOF",
    "python3 heredoc body opening the file": (
        f"python3 <<'EOF'\nprint(open('{_PROTECTED}').read())\nEOF"
    ),
    "python3 heredoc body globbing a prefix": (
        f"python3 <<'EOF'\nimport glob\nprint(glob.glob('{_PREFIX}*'))\nEOF"
    ),
}


class TestEveryFileReadingShapeIsStillDenied:
    """Each shape a reader might use to reach a protected file, with the file present.

    The relaxation for quoted text operands must not make any of them pass.
    """

    @pytest.mark.parametrize(
        "command", list(_READS_A_PROTECTED_FILE.values()), ids=list(_READS_A_PROTECTED_FILE)
    )
    def test_is_denied(self, command: str, tmp_path: Path) -> None:
        (tmp_path / _PROTECTED).write_text("x")
        decision, _ = _verdict(command, tmp_path)
        assert decision == Decision.DENY
