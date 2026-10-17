"""A message or body FILE written earlier in the same command is still judged.

``git commit -F m.txt`` and ``gh pr create --body-file b.md`` read a file the
handler cannot find on disk at PreToolUse time when an earlier segment of the
same command creates it. Judging only the recording segment (ledger 00474 N364)
dropped the text that carries the term, so the commit message or the published
body reached history unexamined. The segment that writes the file named by a
recording command's ``-F``/``--file``/``--body-file`` is judged with it, while
an unrelated segment (``cd /tmp/<term>``) still is not.

The term is a public pattern fixture; no real secret term is used.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.handlers.pre_tool_use.sensitive_content import (
    SensitiveContentHandler,
)
from claude_code_hooks_daemon.utils import secret_redaction as sr

_TERM = "ZZPROBETERMZZ"


@pytest.fixture(autouse=True)
def _reset_caches() -> Iterator[None]:
    reset_data_layer()
    sr.reset_terms_cache()
    sr.reset_active_path_cache()
    yield
    reset_data_layer()
    sr.reset_terms_cache()
    sr.reset_active_path_cache()


@pytest.fixture()
def handler() -> SensitiveContentHandler:
    gate = SensitiveContentHandler()
    gate._public_patterns = [{"name": "probe", "pattern": _TERM, "description": "d"}]
    return gate


def _input(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


class TestFileWrittenThenConsumed:
    @pytest.mark.parametrize(
        "command",
        [
            f"cat > m.txt <<'EOF'\n{_TERM}\nEOF\ngit commit -F m.txt",
            f"printf '{_TERM}' > m.txt && git commit -F m.txt",
            f"echo {_TERM} > m.txt; git commit -F m.txt",
            f"cat > b.md <<'EOF'\n{_TERM}\nEOF\ngh pr create --title t --body-file b.md",
            f"echo {_TERM} > m.txt && git commit --file=m.txt",
            f"echo {_TERM} > sub/m.txt && git commit -F ./sub/m.txt",
        ],
    )
    def test_term_in_the_file_written_by_the_same_command_is_denied(
        self, handler: SensitiveContentHandler, tmp_path: Path, command: str
    ) -> None:
        hook_input = _input(command, tmp_path)

        assert handler.matches(hook_input) is True
        assert handler.handle(hook_input).decision == Decision.DENY

    def test_clean_file_written_by_the_same_command_is_allowed(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        command = "cat > m.txt <<'EOF'\nordinary message\nEOF\ngit commit -F m.txt"

        assert handler.matches(_input(command, tmp_path)) is False

    def test_term_in_a_file_the_command_does_not_consume_is_allowed(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        command = f"echo {_TERM} > notes.txt && git commit -F m.txt"

        assert handler.matches(_input(command, tmp_path)) is False


class TestNarrowingStillHolds:
    def test_term_in_an_unrelated_cd_is_allowed(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        command = f"cd /tmp/{_TERM} && git switch -c clean"

        assert handler.matches(_input(command, tmp_path)) is False

    def test_unrelated_cd_beside_a_clean_message_file_is_allowed(
        self, handler: SensitiveContentHandler, tmp_path: Path
    ) -> None:
        command = f"cd /tmp/{_TERM} && echo ok > m.txt && git commit -F m.txt"

        assert handler.matches(_input(command, tmp_path)) is False
