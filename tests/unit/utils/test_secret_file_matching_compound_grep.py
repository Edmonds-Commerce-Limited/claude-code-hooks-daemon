"""A grep-pattern-only mention stays exempt as one statement of a compound command.

Issue #144 (niggle N559): a pattern-only search was allowed alone but denied
once ``; echo done`` followed it, although the trailing statement opens no file.
A compound command is judged statement by statement: it is exempt only when
every statement either carries no protected mention or is itself a
grep-pattern-only mention. Expansion characters stay a whole-command refusal.
"""

import pytest

from claude_code_hooks_daemon.utils import secret_file_matching as sfm

# Assembled so this file never spells the protected name itself.
K = "id_" + "rsa"


def _grep_ok(command: str) -> bool:
    return sfm.is_grep_pattern_only_mention(command, sfm.DEFAULT_PROTECTED_PATTERNS)


class TestCompoundCommandWithGrepPatternOnlyIsAllowed:
    """The reported false positive and its siblings."""

    @pytest.mark.parametrize(
        "command",
        [
            f"grep -rn '{K}' dir; echo done",
            f"grep -rn '{K}' dir && echo ok",
            f"grep -rn '{K}' dir || echo none",
            f"echo start; grep -rn '{K}' dir",
            f"echo start && grep {K} dir.txt && echo done",
            f"grep {K} a.txt; grep -e {K} b.txt",
            f"grep {K} a.txt;",
        ],
    )
    def test_every_statement_is_clean_or_pattern_only(self, command: str) -> None:
        assert _grep_ok(command)

    def test_newline_separated_statements_without_heredoc(self) -> None:
        assert _grep_ok(f"grep -rn '{K}' dir\necho done")
        assert _grep_ok(f"echo start\n\ngrep -rn '{K}' dir\n")

    def test_newline_after_a_list_operator_continues_the_line(self) -> None:
        assert _grep_ok(f"grep -rn '{K}' dir &&\necho ok")


class TestCompoundCommandStaysDenied:
    """Every statement that could read the protected file keeps the deny."""

    @pytest.mark.parametrize(
        "command",
        [
            f"grep '{K}' d; cat {K}",
            f"cat {K}; grep '{K}' d",
            f"grep '{K}' d && cat {K}",
            f"echo hi; cat ~/.ssh/{K}",
            "grep 'x' d | xargs cat",
            f"grep '{K}' d | xargs cat",
            f"grep -f {K} d",
            f"grep -f {K} d; echo done",
            f"grep '{K}' d; grep -f {K} d",
            f"p={K}; cat $p",
            f"p={K}; grep $p d",
            f"grep '{K}' d > {K}",
            f"grep '{K}' d; echo hi > {K}",
            f"grep '{K}' d & cat {K}",
            f"grep '{K}' d; bash -c 'cat {K}'",
            f"grep '{K}' d; (cat {K})",
            f"grep '{K}' d; grep foo {K}",
        ],
    )
    def test_denied(self, command: str) -> None:
        assert not _grep_ok(command)

    def test_no_grep_and_no_mention_is_not_an_exemption(self) -> None:
        assert not _grep_ok("echo a; echo b")


class TestNewlinesFailClosedWhereTheyCannotBeSplit:
    """A heredoc body or a quoted newline is never read as statements."""

    def test_heredoc_with_newlines_stays_denied(self) -> None:
        assert not _grep_ok(f"grep {K} dir; cat <<EOF\n{K}\nEOF")
        assert not _grep_ok(f"grep {K} dir\ncat <<'EOF'\nbody\nEOF")

    def test_newline_inside_double_quotes_stays_denied(self) -> None:
        assert not _grep_ok(f'grep "{K}\nx" dir')

    def test_newline_then_reader_stays_denied(self) -> None:
        assert not _grep_ok(f"grep '{K}' d\ncat {K}")

    def test_carriage_return_stays_denied(self) -> None:
        assert not _grep_ok(f"grep '{K}' d\r\necho done")

    def test_line_continuation_stays_denied(self) -> None:
        assert not _grep_ok(f"grep '{K}' d \\\n  && echo ok")
