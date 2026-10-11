"""Ledger N408: the gh view comment guards judge what a command RUNS.

Both handlers denied a command that only mentioned `gh issue view` /
`gh pr view`, denied the `--json=comments` spelling, and cut the view segment at
a `|` inside a quoted `--jq` value.
"""

from __future__ import annotations

from typing import Any

import pytest

from claude_code_hooks_daemon.core.data_layer import reset_data_layer
from claude_code_hooks_daemon.core.hook_result import Decision
from claude_code_hooks_daemon.handlers.pre_tool_use.gh_issue_comments import GhIssueCommentsHandler
from claude_code_hooks_daemon.handlers.pre_tool_use.gh_pr_comments import GhPrCommentsHandler

_HANDLERS = [("issue", GhIssueCommentsHandler), ("pr", GhPrCommentsHandler)]


@pytest.fixture(autouse=True)
def _reset_disclosure_tracker() -> Any:
    reset_data_layer()
    yield
    reset_data_layer()


def _bash(command: str) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


@pytest.fixture(params=_HANDLERS, ids=[noun for noun, _ in _HANDLERS])
def noun_handler(request: pytest.FixtureRequest) -> tuple[str, Any]:
    noun, cls = request.param
    return noun, cls()


def _mentions(view: str) -> list[str]:
    return [
        f'echo "{view} 5"',
        f"echo '{view} 5'",
        f"grep -rn '{view}' docs/",
        f'rg "{view}" src/',
        f'git commit -m "docs: always add --comments to {view} 5"',
        f"git commit -m 'docs: {view} 5 is blocked'",
        f'gh issue comment 7 --body "{view} 5 was denied"',
        f"true # {view} 5",
        f"cat > notes.md <<'EOF'\n{view} 5\nEOF",
        f"cat <<'EOF'\n{view} 5\nEOF",
    ]


def _denied(view: str) -> list[str]:
    return [
        f"{view} 5",
        f"{view} 5 --repo o/r",
        f"if true; then {view} 5; fi",
        f'bash -c "{view} 5"',
        f"bash -c '{view} 5'",
        f"bash -n -c '{view} 999999999'",
        f'eval "{view} 5"',
        f"env FOO=1 {view} 5",
        f"nohup {view} 5",
        f"timeout 5 {view} 5",
        f"true && {view} 5",
        f"true; {view} 5",
        f"({view} 5)",
        f"echo $({view} 5)",
        f"echo `{view} 5`",
        f"sleep 1 & {view} 5",
        f"! {view} 5",
        f"/usr/bin/{view} 5",
        f"cat <<'EOF' | bash\n{view} 5\nEOF",
        f"bash <<'EOF'\n{view} 5\nEOF",
        f"{view} 5 --json title,body",
        f"{view} 5 --json=title,body",
        f'{view} 5 --json title --jq ".title | length"',
        f'echo "{view} 5"; {view} 5',
        f"{view} 5 && echo '--comments'",
    ]


def _allowed(view: str) -> list[str]:
    return [
        f"{view} 5 --comments",
        f"{view} 5 --json comments",
        f"{view} 5 --json title,comments",
        f"{view} 5 --json=comments",
        f"{view} 5 --json=title,comments",
        f"{view} 5 --json title,comments | jq .comments",
        f"{view} 5 --json comments --jq '.comments | length'",
        f"{view} 5 --json=comments --jq '.comments | length'",
        f'{view} 5 --json=comments --jq ".comments | map(.body)"',
        f"{view} 5 --jq '.comments | length' --json comments",
        f"{view} 5 --comments --jq '.a | .b'",
    ]


class TestGhViewCommandPosition:
    def test_mention_is_allowed(self, noun_handler: tuple[str, Any]) -> None:
        noun, handler = noun_handler
        for command in _mentions(f"gh {noun} view"):
            assert handler.matches(_bash(command)) is False, command

    def test_real_view_without_comments_is_denied(self, noun_handler: tuple[str, Any]) -> None:
        noun, handler = noun_handler
        for command in _denied(f"gh {noun} view"):
            assert handler.matches(_bash(command)) is True, command

    def test_view_with_comments_is_allowed(self, noun_handler: tuple[str, Any]) -> None:
        noun, handler = noun_handler
        for command in _allowed(f"gh {noun} view"):
            assert handler.matches(_bash(command)) is False, command

    def test_handle_suggests_fix_for_the_real_segment_not_the_mention(
        self, noun_handler: tuple[str, Any]
    ) -> None:
        noun, handler = noun_handler
        view = f"gh {noun} view"
        result = handler.handle(_bash(f'echo "{view} 1"; {view} 2'))
        assert result.decision == Decision.DENY
        assert f"{view} 2 --comments" in result.reason

    def test_handle_extends_json_equals_field_list(self, noun_handler: tuple[str, Any]) -> None:
        noun, handler = noun_handler
        view = f"gh {noun} view"
        result = handler.handle(_bash(f"{view} 2 --json=title"))
        assert f"{view} 2 --json=title,comments" in result.reason

    def test_handle_keeps_quoted_jq_pipe_in_suggestion(self, noun_handler: tuple[str, Any]) -> None:
        noun, handler = noun_handler
        view = f"gh {noun} view"
        result = handler.handle(_bash(f"{view} 2 --jq '.a | .b'"))
        assert f"{view} 2 --jq '.a | .b' --comments" in result.reason

    def test_acceptance_test_is_parse_only(self, noun_handler: tuple[str, Any]) -> None:
        _noun, handler = noun_handler
        for test in handler.get_acceptance_tests():
            assert test.command.startswith("bash -n -c '")
            assert handler.matches(_bash(test.command)) is True
