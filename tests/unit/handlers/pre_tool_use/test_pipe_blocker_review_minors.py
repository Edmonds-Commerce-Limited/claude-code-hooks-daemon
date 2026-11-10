"""pipe_blocker: Task 2.2f review minors (heredoc-authored script, py.test)."""

from typing import Any

import pytest
from tests.support.unknown_verdict_asserts import assert_unknown_verdict

from claude_code_hooks_daemon.core import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.pipe_blocker import PipeBlockerHandler

_GUARD = "pipe_blocker"


def _event(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


@pytest.fixture
def handler() -> PipeBlockerHandler:
    return PipeBlockerHandler()


class TestHeredocAuthoredScriptRunInSameCommand:
    """A script written by heredoc and run in the same command names its producer."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat > t.sh <<'EOF'\npytest -q\nEOF\nbash t.sh | tail -5",
            "cat > t.sh <<'EOF'\npytest -q tests/\nEOF\nbash t.sh 2>&1 | tail -20",
            "tee t.sh <<'EOF'\npytest -q\nEOF\nsh t.sh | tail",
        ],
    )
    def test_denies(self, handler: PipeBlockerHandler, command: str) -> None:
        assert handler.matches(_event(command))
        assert handler.handle(_event(command)).decision == Decision.DENY

    def test_heredoc_without_blacklisted_name_keeps_allowing(
        self, handler: PipeBlockerHandler
    ) -> None:
        command = "cat > t.sh <<'EOF'\necho hello\nEOF\nbash t.sh | tail -5"
        assert handler.handle(_event(command)).decision == Decision.ALLOW


class TestLegacyPyTestEntryPoint:
    """`py.test` is pytest."""

    @pytest.mark.parametrize(
        "command",
        [
            "py.test | tail",
            "python -m py.test | tail",
            "uv run py.test | tail",
            "py.test tests/ 2>&1 | head -5",
        ],
    )
    def test_denies(self, handler: PipeBlockerHandler, command: str) -> None:
        assert handler.handle(_event(command)).decision == Decision.DENY


class TestHeredocBodyNothingRunsIsNotScanned:
    """Review Minor-3: a body written to markdown or fed to a message is prose."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat > notes.md <<'EOF'\nrun pytest | tail\nEOF\ndocker ps | tail -1",
            "cat <<'EOF' > notes.md\nrun pytest\nEOF\ndocker ps | tail -1",
            "tee notes.md <<'EOF'\nrun pytest\nEOF\ndocker ps | tail -1",
            "git commit -F - <<'EOF'\nfix pytest\nEOF\ndocker ps | tail -1",
            "gh pr create --title t --body-file - <<'EOF'\nfix pytest\nEOF\ndocker ps | tail -1",
            "gh issue comment 5 --body-file - <<'EOF'\nfix pytest\nEOF\ndocker ps | tail -1",
        ],
    )
    def test_allows_with_the_unknown_advisory(
        self, handler: PipeBlockerHandler, command: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        result = handler.handle(_event(command))
        assert_unknown_verdict(result, caplog, _GUARD, "docker")

    @pytest.mark.parametrize(
        "command",
        [
            "cat > t.sh <<'EOF'\nrun pytest\nEOF\ndocker ps | tail -1",
            "tee notes.md t.sh <<'EOF'\nrun pytest\nEOF\ndocker ps | tail -1",
            "cat > notes.md <<EOF\nrun pytest\nEOF\ndocker ps | tail -1",
            "cat <<'EOF' | bash\nrun pytest\nEOF\ndocker ps | tail -1",
            "bash <<'EOF'\nrun pytest\nEOF\ndocker ps | tail -1",
        ],
    )
    def test_a_body_something_may_run_still_denies(
        self, handler: PipeBlockerHandler, command: str
    ) -> None:
        assert handler.handle(_event(command)).decision == Decision.DENY


class TestHeredocShapesThatRunAScript:
    """Review Minor-5: the heredoc forms bash accepts all carry the script."""

    @pytest.mark.parametrize(
        "command",
        [
            "cat > t.sh <<-'EOF'\n\tpytest -q\n\tEOF\nbash t.sh | tail -5",
            "cat > t.sh <<EOF\npytest -q\nEOF\nbash t.sh | tail -5",
            "cat > a.sh <<'A'\necho hi\nA\ncat > t.sh <<'B'\npytest -q\nB\nbash t.sh | tail -5",
            "cat > t.sh <<'A' && cat > u.sh <<'B'\npytest -q\nA\necho hi\nB\nbash t.sh | tail",
        ],
        ids=["dash-quoted", "unquoted", "two-heredocs-second", "two-heredocs-one-line"],
    )
    def test_denies(self, handler: PipeBlockerHandler, command: str) -> None:
        assert handler.handle(_event(command)).decision == Decision.DENY


class TestLegacyPyTestEntryPointWrapped:
    """Review Minor-5: `py.test` behind env, a path and `bash -c` is still pytest."""

    @pytest.mark.parametrize(
        "command",
        [
            "env py.test | tail",
            "env FOO=1 py.test tests/ | tail -5",
            ".venv/bin/py.test | tail",
            "/usr/bin/py.test -q | head -3",
            "bash -c 'py.test -q | tail -5'",
        ],
    )
    def test_denies(self, handler: PipeBlockerHandler, command: str) -> None:
        assert handler.handle(_event(command)).decision == Decision.DENY
