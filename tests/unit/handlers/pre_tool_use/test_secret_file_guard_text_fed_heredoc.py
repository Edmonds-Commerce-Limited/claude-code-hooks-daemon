"""secret_file_guard and heredoc bodies fed to TEXT readers (Plan 00474 N256).

Bash hands a quoted-delimiter heredoc body to its receiver verbatim. When the
receiver only reads it as text (the `git commit -F -` message idiom,
`cat > notes.md`, `grep`, `tee`) no word in it is a path anything opens, so it
is neither judged nor glob-walked: markdown bold such as `**Task**` in a commit
message used to walk the tree, and a prose mention of a protected name denied
the commit. Every receiver that DOES open or run the body's words keeps it.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.secret_file_guard import (
    SecretFileGuardHandler,
)
from claude_code_hooks_daemon.utils import secret_file_matching as sfm

# Spelled in pieces so this file does not itself name a protected path or
# carry shell syntax a scan of the file's text would try to read.
_P = "." + "vault-" + "pass"
_SUB = "$" + "("
_PROC_OUT = ">" + "("
_OPEN = "<<'EOF'"
_BOLD = "Fix the scan\n\n**Task** done: see **Status**: and **/vendor excludes."
_PROSE = f"Rotate the key kept in {_P}"
_BRACE_SPELLED = "cat /proj/" + _P[:-2] + "{s,x}s"


def _matches(command: str) -> bool:
    handler = SecretFileGuardHandler()
    return handler.matches({"tool_name": "Bash", "tool_input": {"command": command}})


def _fed(head: str, body: str, opener: str = _OPEN) -> str:
    return f"{head} {opener}\n{body}\nEOF"


@pytest.fixture
def walked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every word that reaches a filesystem glob walk."""
    seen: list[str] = []
    real = sfm._expand_glob_token

    def _spy(token: str, *args: Any, **kwargs: Any) -> str | None:
        seen.append(token)
        return real(token, *args, **kwargs)

    monkeypatch.setattr(sfm, "_expand_glob_token", _spy)
    return seen


_TEXT_READERS = [
    "git commit -F -",
    "git commit -q -F -",
    "git -C /repo commit --file=-",
    "git tag -a v1 -F -",
    "cat",
    "tee",
    "grep -c Task",
    "wc -l",
    "sort -u",
]


class TestATextFedBodyIsData:
    @pytest.mark.parametrize("head", _TEXT_READERS)
    def test_a_prose_mention_of_a_protected_name_is_allowed(self, head: str) -> None:
        assert not _matches(_fed(head, _PROSE))

    @pytest.mark.parametrize("head", _TEXT_READERS)
    def test_markdown_bold_is_not_glob_walked(self, head: str, walked: list[str]) -> None:
        assert not _matches(_fed(head, _BOLD))
        assert walked == []

    def test_a_pipeline_of_text_readers_is_data(self) -> None:
        assert not _matches(f"cat {_OPEN} | sort -u | wc -l\n{_PROSE}\nEOF")

    def test_the_double_quoted_delimiter_is_data(self) -> None:
        assert not _matches(_fed("git commit -F -", _PROSE, opener='<<"EOF"'))


class TestAGlobBehindAnOverLongNameIsNotAGuardDefect:
    """Plan 00474 N255: a commit message holding two apostrophes
    (`someone's` ... `N5's`) quotes the prose between them into ONE shell
    word. When that word held `CLAUDE/core/*.core.md` behind a component past
    the name limit, Python 3.11's ``Path.glob`` raised ENAMETOOLONG and the
    guard denied `git commit -F - <<'EOF'` as R-SECRET-EVALUATION-ERROR. The
    body is judged here through a receiver that is NOT a text reader, so the
    word really reaches the glob walk."""

    _LONG = "and the rest of this paragraph just keeps going " * 8
    _PROSE_WITH_GLOB = (
        f"discarding someone's edits\n{_LONG}\nleft CLAUDE/core/*.core.md stale. N5's body"
    )

    @pytest.mark.parametrize("head", ["awk 1", "git commit -F -", "cat"])
    def test_the_message_is_allowed(self, head: str) -> None:
        handler = SecretFileGuardHandler()
        hook_input = {
            "tool_name": "Bash",
            "tool_input": {"command": _fed(head, self._PROSE_WITH_GLOB)},
        }
        assert not handler.matches(hook_input)


class TestWhatTheBodyStillCannotHide:
    def test_the_command_part_is_still_judged(self) -> None:
        assert _matches(_fed(f"cat {_P}", _BOLD))

    def test_a_redirect_target_is_still_judged(self) -> None:
        assert _matches(f"cat {_OPEN} > {_P}\n{_BOLD}\nEOF")

    def test_a_command_after_the_closer_is_still_judged(self) -> None:
        assert _matches(_fed("cat", _BOLD) + f"\ncat {_P}")

    def test_the_second_heredoc_is_judged_on_its_own_receiver(self) -> None:
        command = f"cat <<'A' > a.md\n{_PROSE}\nA\nbash <<'B'\ncat {_P}\nB"
        assert _matches(command)


class TestAReceiverThatOpensOrRunsTheBodyKeepsIt:
    @pytest.mark.parametrize(
        "command",
        [
            _fed("bash", f"cat {_P}"),
            _fed("sh -s", f"cat {_P}"),
            f"cat {_OPEN} | bash\ncat {_P}\nEOF",
            _fed(f"tee {_PROC_OUT}bash)", f"cat {_P}"),
            _fed("xargs cat", _P),
            _fed("git update-index --add --stdin", _P),
            _fed("git cat-file --batch", _P),
            _fed("git commit --pathspec-from-file=-", _P),
            _fed("git commit -F - --pathspec-from-file=-", _P),
            _fed("git commit -m message", _P),
            _fed("patch -p1", _P),
            _fed("jq .", _P),
            # A body written to a file is a script someone runs later.
            _fed("cat > run.sh", f"cat {_P}"),
            _fed("cat >> run.sh", f"cat {_P}"),
            _fed("tee run.sh", f"cat {_P}"),
            f"cat {_OPEN} | tee run.sh\ncat {_P}\nEOF",
            _fed("cat > run.sh", _BRACE_SPELLED),
            _fed("git commit -F -", f"{_SUB}cat {_P})", opener="<<EOF"),
            f'git commit -m "{_SUB}cat {_OPEN}\n{_P}\nEOF\n)"',
        ],
    )
    def test_a_mention_in_the_body_is_still_denied(self, command: str) -> None:
        assert _matches(command)
