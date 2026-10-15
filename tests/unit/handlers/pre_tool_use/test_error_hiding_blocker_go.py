"""error_hiding_blocker on idiomatic Go (Plan 00527 Phase 4).

Every form in the GO-AUDIT.md blank-identifier table is pinned here.
"""

from typing import Any

import pytest

from claude_code_hooks_daemon.handlers.pre_tool_use.error_hiding_blocker import (
    ErrorHidingBlockerHandler,
)


@pytest.fixture
def handler() -> ErrorHidingBlockerHandler:
    return ErrorHidingBlockerHandler()


def _write(content: str, path: str = "/tmp/app/main.go") -> dict[str, Any]:
    return {"tool_name": "Write", "tool_input": {"file_path": path, "content": content}}


def _edit(new_string: str) -> dict[str, Any]:
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/tmp/app/main.go",
            "old_string": "x",
            "new_string": new_string,
        },
    }


ALLOWED = [
    pytest.param("v, _ := m[k]", id="map-lookup"),
    pytest.param("x, _ := y.(T)", id="type-assertion"),
    pytest.param("s, _ := ctx.Value(k).(string)", id="type-assertion-on-call"),
    pytest.param("v, _ := f(x)[k]", id="index-of-call-result"),
    pytest.param("for i, _ := range xs {\n}", id="range-with-blank-value"),
    pytest.param('_, _ = fmt.Fprintf(w, "x")', id="explicit-discard-assign"),
    pytest.param("v, _ := <-ch", id="channel-receive"),
    pytest.param("v, ok := x.(T)", id="comma-ok"),
    pytest.param("for _, v := range xs {\n}", id="range-blank-index"),
    pytest.param("_, err := f()", id="blank-first"),
    pytest.param("x, _, err := f()", id="blank-middle"),
    pytest.param("// n, _ := strconv.Atoi(s)", id="line-comment"),
    pytest.param("/* n, _ := strconv.Atoi(s) */", id="block-comment"),
    pytest.param("x := 1 // n, _ := strconv.Atoi(s)", id="trailing-comment"),
    pytest.param('msg := "n, _ := strconv.Atoi(s)"', id="interpreted-string"),
    pytest.param('msg := "say \\"n, _ := f()\\""', id="string-with-escaped-quotes"),
    pytest.param("re := `n, _ := strconv.Atoi(s)`", id="raw-string"),
    pytest.param("doc := `\nn, _ := strconv.Atoi(s)\nif err != nil {}\n`", id="multiline-raw"),
    pytest.param('q := \'"\'\nm := "if err != nil {}"', id="rune-quote-then-string"),
    pytest.param("// if err != nil {}", id="empty-check-in-comment"),
    pytest.param("if err != nil {\n\treturn err\n}", id="handled"),
]

BLOCKED = [
    pytest.param("n, _ := strconv.Atoi(s)", id="atoi"),
    pytest.param("a, b, _ := f()", id="three-values"),
    pytest.param("v, _ := pkg.Func(x)", id="qualified-call"),
    pytest.param("result, _ := riskyCall()", id="plain-call"),
    pytest.param("_, _ := riskyCall()", id="all-blank-define"),
    pytest.param("v, _ = os.Open(p)", id="assign-not-define"),
    pytest.param("if err != nil {}", id="empty-check"),
    pytest.param("if err != nil {  }", id="empty-check-spaces"),
    pytest.param("if err != nil {\n\t// ignore\n}", id="comment-only-body"),
    pytest.param("if err != nil { /* ignore */ }", id="block-comment-only-body"),
    pytest.param("if err != nil {\n\t// ignore\n\t// really\n}", id="two-comments-body"),
    pytest.param("x := `raw`\nn, _ := strconv.Atoi(s)", id="after-raw-string"),
    pytest.param("// note\nn, _ := strconv.Atoi(s)", id="after-comment"),
    pytest.param(
        't.Run("a", func(t *testing.T) {\n\tn, _ := strconv.Atoi("1")\n})', id="in-closure"
    ),
]


@pytest.mark.parametrize("content", ALLOWED)
def test_idiomatic_go_is_not_blocked(handler: ErrorHidingBlockerHandler, content: str) -> None:
    assert handler.matches(_write(content)) is False


@pytest.mark.parametrize("content", BLOCKED)
def test_error_hiding_go_is_blocked(handler: ErrorHidingBlockerHandler, content: str) -> None:
    assert handler.matches(_write(content)) is True


@pytest.mark.parametrize("content", ALLOWED[:6])
def test_edit_fragments_follow_the_same_rules_allowed(
    handler: ErrorHidingBlockerHandler, content: str
) -> None:
    assert handler.matches(_edit(content)) is False


def test_edit_fragment_with_unterminated_string_does_not_raise(
    handler: ErrorHidingBlockerHandler,
) -> None:
    assert handler.matches(_edit('x := "unterminated\nn, _ := f()')) is True


def test_unterminated_block_comment_swallows_rest(handler: ErrorHidingBlockerHandler) -> None:
    assert handler.matches(_edit("/* open\nn, _ := f()")) is False


def test_unterminated_raw_string_swallows_rest(handler: ErrorHidingBlockerHandler) -> None:
    assert handler.matches(_edit("x := `open\nn, _ := f()")) is False


def test_denial_names_the_empty_check_for_a_comment_body(
    handler: ErrorHidingBlockerHandler,
) -> None:
    result = handler.handle(_write("if err != nil {\n\t// ignore\n}"))
    assert result.decision == "deny"
    assert "empty error check" in result.reason


def test_other_languages_are_unaffected(handler: ErrorHidingBlockerHandler) -> None:
    py = {
        "tool_name": "Write",
        "tool_input": {"file_path": "/tmp/a.py", "content": "try:\n    x()\nexcept:\n    pass\n"},
    }
    assert handler.matches(py) is True
