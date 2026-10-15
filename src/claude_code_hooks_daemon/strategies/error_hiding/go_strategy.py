"""Go error-hiding strategy - patterns that suppress errors in Go code."""

import re
from typing import Any

from claude_code_hooks_daemon.strategies.error_hiding.protocol import ErrorHidingPattern
from claude_code_hooks_daemon.utils.scratch_dir import acceptance_path

_LANGUAGE_NAME = "Go"
#: Acceptance-test fixture directory, below the gitignored acceptance root.
_FIXTURE_DIR = "acceptance-test-error-hiding-go"
_EXTENSIONS: tuple[str, ...] = (".go",)

#: A call expression's head: `f(`, `pkg.Func(`, `a.b.C(`. A type assertion
#: `y.(T)` and a map lookup `m[k]` have no such head, which is what keeps the
#: comma-ok forms out of the rule below.
_CALL_HEAD = r"\w+(?:\s*\.\s*\w+)*\s*\("

#: The two shapes of "an error is thrown away by a trailing blank":
#: - some named target, then a trailing `_`, assigned from a call
#:   (`n, _ := f()`, `a, b, _ := f()`, `v, _ = f()`);
#: - `_, _ :=` from a call. The `=` spelling is the explicit-discard idiom
#:   errcheck accepts (`_, _ = fmt.Fprintf(...)`) and is left alone.
_BLANK_LAST_FROM_CALL = (
    r"(?:\b(?:_\s*,\s*)*(?!_\b)[A-Za-z]\w*(?:\s*,\s*\w+)*\s*,\s*_\s*:?="
    r"|\b_(?:\s*,\s*_)+\s*:=)"
    r"(?!=)\s*" + _CALL_HEAD
)

_BLANK = " "
_NEWLINE = "\n"
_OPEN_PAREN = "("
_CLOSE_PAREN = ")"
_RAW_QUOTE = "`"
_QUOTES = ('"', "'")
_ESCAPE = "\\"
_LINE_COMMENT = "//"
_BLOCK_COMMENT_OPEN = "/*"
_BLOCK_COMMENT_CLOSE = "*/"
#: What may follow a call's `)` for the expression to stop being "the call's
#: result": a type assertion on it or an index into it.
_NOT_A_BARE_CALL_RESULT = re.compile(r"\s*(?:\.\s*\(|\[)")

_PATTERNS: tuple[ErrorHidingPattern, ...] = (
    ErrorHidingPattern(
        name="empty error check",
        regex=r"if\s+err\s*!=\s*nil\s*\{\s*\}",
        example="if err != nil {}",
        suggestion="Return or handle the error; never ignore it",
    ),
    ErrorHidingPattern(
        name="blank identifier discards error",
        # Only a blank in the LAST position, assigned from a FUNCTION CALL,
        # hides an error: Go returns the error last, so `n, _ := f()` throws
        # it away, while `_, err :=` captures it and the comma-ok forms
        # (`m[k]`, `y.(T)`, `range`) have no error to hide.
        regex=_BLANK_LAST_FROM_CALL,
        example="result, _ := riskyCall()",
        suggestion="Capture and check the error return value",
    ),
)


def _blank_out(text: str) -> str:
    """``text`` with every character but newlines replaced by a space."""
    return "".join(ch if ch == _NEWLINE else _BLANK for ch in text)


def _blank_comments_and_strings(source: str) -> str:
    """Blank the body of every comment, string and rune literal in ``source``.

    Quotes are kept and newlines are preserved, so what remains is code only
    and the offsets of everything else are unchanged. An unterminated literal
    runs to the end of its line (to the end of the text for a raw string or a
    block comment), since an Edit fragment may start or stop mid-literal.
    """
    out: list[str] = []
    i = 0
    size = len(source)
    while i < size:
        ch = source[i]
        if source.startswith(_LINE_COMMENT, i):
            end = source.find(_NEWLINE, i)
            end = size if end == -1 else end
            out.append(_blank_out(source[i:end]))
        elif source.startswith(_BLOCK_COMMENT_OPEN, i):
            close = source.find(_BLOCK_COMMENT_CLOSE, i + len(_BLOCK_COMMENT_OPEN))
            end = size if close == -1 else close + len(_BLOCK_COMMENT_CLOSE)
            out.append(_blank_out(source[i:end]))
        elif ch == _RAW_QUOTE:
            close = source.find(_RAW_QUOTE, i + 1)
            end = size if close == -1 else close + 1
            out.append(_RAW_QUOTE + _blank_out(source[i + 1 : end - 1]) + source[end - 1 : end])
        elif ch in _QUOTES:
            end = _quoted_literal_end(source, i)
            closed = end - 1 > i and source[end - 1] == ch
            body_end = end - 1 if closed else end
            out.append(ch + _blank_out(source[i + 1 : body_end]) + (ch if closed else ""))
        else:
            out.append(ch)
            end = i + 1
        i = end
    return "".join(out)


def _quoted_literal_end(source: str, start: int) -> int:
    """Index just past the `"..."` or `'...'` literal opening at ``start``."""
    quote = source[start]
    size = len(source)
    i = start + 1
    while i < size and source[i] != quote and source[i] != _NEWLINE:
        i += 2 if source[i] == _ESCAPE else 1
    i = min(i, size)
    return i + 1 if i < size and source[i] == quote else i


def _neutralise_call_results_used_as_values(code: str) -> str:
    """Un-call `f(x)` in `f(x).(T)` and `f(x)[k]`: those are comma-ok forms, not calls.

    ``v, _ := ctx.Value(k).(string)`` is a type assertion whose operand happens
    to be a call, and ``v, _ := f(x)[k]`` a map lookup. Their opening paren is
    replaced by a space so the call-shaped regex cannot see a call there.
    """
    chars = list(code)
    opens: list[int] = []
    for index, ch in enumerate(code):
        if ch == _OPEN_PAREN:
            opens.append(index)
        elif ch == _CLOSE_PAREN and opens:
            open_index = opens.pop()
            if _NOT_A_BARE_CALL_RESULT.match(code, index + 1):
                chars[open_index] = _BLANK
    return "".join(chars)


class GoErrorHidingStrategy:
    """Error-hiding strategy for Go source files (.go)."""

    @property
    def language_name(self) -> str:
        return _LANGUAGE_NAME

    @property
    def extensions(self) -> tuple[str, ...]:
        return _EXTENSIONS

    @property
    def patterns(self) -> tuple[ErrorHidingPattern, ...]:
        return _PATTERNS

    def prepare_content(self, content: str) -> str:
        """Reduce Go source to the code the patterns should judge.

        Comments and string/rune/raw-string literals are blanked, so a pattern
        quoted in either is ignored and a comment-only `if err != nil` body
        reads as empty.
        """
        return _neutralise_call_results_used_as_values(_blank_comments_and_strings(content))

    def get_acceptance_tests(self) -> list[Any]:
        """Return acceptance tests for Go error-hiding strategy."""
        from claude_code_hooks_daemon.constants.tools import ToolName
        from claude_code_hooks_daemon.core import (
            AcceptanceTest,
            Decision,
            RecommendedModel,
            TestType,
            ToolPayload,
        )

        fixture_root = acceptance_path(_FIXTURE_DIR)

        # Stated once; the prose is rendered from it (Plan 00345 Phase 2).
        # A WRITE payload, not Bash: these read as `Write(...)` call syntax,
        # and a Bash payload would probe a string no file-write handler
        # matches -- the deny test would then see ALLOW-by-not-matching and
        # pass while testing nothing.
        bad_probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": acceptance_path(_FIXTURE_DIR, "bad.go"),
                "content": "package main\nfunc main() { if err != nil {} }",
            },
        )
        good_probe = ToolPayload(
            tool_name=ToolName.WRITE,
            tool_input={
                "file_path": acceptance_path(_FIXTURE_DIR, "good.go"),
                "content": (
                    'package main\nimport ("fmt"; "os")\n'
                    "func main() {\n"
                    '  if _, err := os.Open("f"); err != nil { fmt.Println(err) }\n'
                    "}"
                ),
            },
        )

        return [
            AcceptanceTest(
                title="Go: empty error check ignores error value",
                command=bad_probe.as_instruction(),
                tool_payload=bad_probe,
                description=("Blocks Go file with empty error check written via Write tool"),
                expected_decision=Decision.DENY,
                expected_message_patterns=[
                    r"BLOCKED \[R-ERROR-HIDING\]",
                    r"empty error check",
                ],
                safety_notes="Inside the gitignored acceptance directory - safe",
                test_type=TestType.BLOCKING,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.HAIKU,
                requires_main_thread=False,
            ),
            AcceptanceTest(
                title="Go: proper error handling is allowed",
                command=good_probe.as_instruction(),
                tool_payload=good_probe,
                description=("Allows Go file with proper error handling via Write tool"),
                expected_decision=Decision.ALLOW,
                expected_message_patterns=[],
                safety_notes="Inside the gitignored acceptance directory - safe",
                test_type=TestType.ADVISORY,
                setup_commands=[f"mkdir -p {fixture_root}"],
                cleanup_commands=[f"rm -rf {fixture_root}"],
                recommended_model=RecommendedModel.SONNET,
                requires_main_thread=False,
            ),
        ]
